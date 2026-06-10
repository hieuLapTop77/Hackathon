"""
backend/src/api/main.py — FastAPI Backend (Refactored)
======================================================
App configuration, lifespan, and router mounting.
All endpoint logic has been moved to routers/ for maintainability.

Routers:
  - health.py        : /health, /models
  - predictions.py   : /predict, /predict-ensemble, /predict-for-flights
  - optimization.py  : /optimize, /simulate
  - flights.py       : /flights, /flights/{id}, /flights/{id}/apply, /flights/{id}/fares, /flights/upload
  - dashboard.py     : /routes, /airports, /summary
  - upload.py        : /upload-predict, /upload-predict-and-save
  - agent.py         : /agent/chat, /agent/status
  - db_ops.py        : /db/seed, /db/routes
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
import glob
import pandas as pd
import joblib

# Project root is two levels up from this file
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from backend.config import OUTPUTS_DIR
from backend.src.models.trainer import load_kaggle_models, get_best_model_name
from backend.src.db import sqlserver


# ── Data loading helper (used by lifespan and db_ops router) ─────────────────
def _load_data():
    """
    Load all CSV and Excel files from data/raw/ and concatenate them.
    Falls back to ai.xlsx if no other files found.
    """
    raw_dir = os.path.join(_PROJECT_ROOT, "data", "raw")
    csv_files  = glob.glob(os.path.join(raw_dir, "*.csv"))
    xlsx_files = glob.glob(os.path.join(raw_dir, "*.xlsx")) + glob.glob(os.path.join(raw_dir, "*.xls"))
    all_files  = csv_files + xlsx_files

    if not all_files:
        raise FileNotFoundError(f"No CSV or Excel files found in {raw_dir}")

    dfs = []
    for fp in sorted(all_files):
        try:
            if fp.lower().endswith(".csv"):
                dfs.append(pd.read_csv(fp))
            else:
                dfs.append(pd.read_excel(fp, engine="openpyxl"))
            print(f"[_load_data] Loaded: {os.path.basename(fp)}")
        except Exception as e:
            print(f"[_load_data] Skipped {fp}: {e}")

    df = pd.concat(dfs, ignore_index=True)

    # Normalize capacity alias
    if "capacity" not in df.columns and "lng_Capacity" in df.columns:
        df["capacity"] = df["lng_Capacity"]

    # Filter obviously bad rows if the columns exist
    if "lead_time_days" in df.columns:
        df = df[df["lead_time_days"] >= 0]
    if "mny_GL_Charges_Total" in df.columns:
        df = df[df["mny_GL_Charges_Total"] >= 50000]

    # Add route column if dep/arr columns exist
    if "str_Dep" in df.columns and "str_Arr" in df.columns:
        df["route"] = df["str_Dep"] + "-" + df["str_Arr"]

    print(f"[_load_data] Total rows after concat+filter: {len(df)}")
    return df.copy()


# ── App lifespan: load artifacts once, store in app.state ─────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQL Server DB (create DB + table if not exist)
    try:
        sqlserver.init_db()
        
        # Check if flights table is empty and auto-seed if it is
        conn = sqlserver._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM flights")
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        
        if count == 0:
            print("[startup] Flights table is empty. Auto-seeding from raw data...")
            try:
                df = _load_data()
                result = sqlserver.upsert_flights(df)
                print(f"[startup] Auto-seeded {result['inserted']} rows.")
            except FileNotFoundError as fnf_err:
                print(f"[startup] Auto-seeding skipped: {fnf_err}. (Flights table remains empty, you can upload or seed data via API later.)", file=sys.stderr)
            except Exception as seed_err:
                print(f"[startup] Auto-seeding failed: {seed_err}. (Flights table remains empty.)", file=sys.stderr)
    except Exception as ex:
        print(f"[startup] DB init failed: {ex}", file=sys.stderr)
        raise ex  # Fail fast!

    enc_path = os.path.join(OUTPUTS_DIR, "label_encoders.pkl")
    if os.path.exists(enc_path):
        app.state.label_encoders = joblib.load(enc_path)
        print(f"Encoders loaded: {enc_path}")
    else:
        app.state.label_encoders = {}
        print("Warning: Label encoders not found")

    qt_path = os.path.join(OUTPUTS_DIR, "target_transformer.pkl")
    if os.path.exists(qt_path):
        app.state.target_transformer = joblib.load(qt_path)
        print(f"Target transformer loaded: {qt_path}")
    else:
        app.state.target_transformer = None
        print("Warning: Target transformer (QuantileTransformer) not found")

    fn_path = os.path.join(OUTPUTS_DIR, "feature_names.txt")
    if os.path.exists(fn_path):
        with open(fn_path) as f:
            app.state.feature_names = [l.strip() for l in f if l.strip()]
        print(f"Feature names loaded: {len(app.state.feature_names)} features")
    else:
        app.state.feature_names = []

    app.state.models = load_kaggle_models()
    app.state.best_model_name = "XGBoost"
    app.state.model_metrics = {}

    if app.state.models:
        app.state.best_model_name = get_best_model_name()
        print(f"Models loaded: {list(app.state.models.keys())}")
        print(f"Best model: {app.state.best_model_name}")

        cmp_path = os.path.join(OUTPUTS_DIR, "model_comparison.csv")
        if os.path.exists(cmp_path):
            import csv as _csv
            with open(cmp_path) as f:
                for row in _csv.DictReader(f):
                    app.state.model_metrics[row["model"]] = {
                        "mape": float(row["mape"]),
                        "rmse": float(row["rmse"]),
                        "mae":  float(row["mae"]),
                        "r2":   float(row["r2"]),
                    }
            print(f"Metrics loaded from: {cmp_path}")
    else:
        print("Warning: No models found -- run: python kaggle/scripts/run_pipeline.py")

    yield  # app runs here

    # Cleanup (if needed)
    app.state.models = {}
    app.state.label_encoders = {}


# ── App creation ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="Airline Revenue Optimizer API",
    description="AI-powered pricing recommendations for airline revenue management",
    version="2.0.0",
    lifespan=lifespan,
)

IS_PROD = os.getenv("ENV", "development").lower() == "production"
cors_origins_str = os.getenv("CORS_ORIGINS", "")
if cors_origins_str:
    origins = [o.strip() for o in cors_origins_str.split(",") if o.strip()]
else:
    if IS_PROD:
        origins = []  # Secure default for production, must configure CORS_ORIGINS
    else:
        origins = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://127.0.0.1:3000"]

# In development, dynamically allow any origin (e.g. from server's IP address)
allow_origin_regex = None if IS_PROD else r"https?://.*"

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Mount routers ────────────────────────────────────────────────────────────
from backend.src.api.routers import health, predictions, optimization, flights, dashboard, upload, agent, db_ops, rag

# Mount each router with "/api" prefix only to keep route table clean and avoid duplication
for r in [health.router, predictions.router, optimization.router, flights.router, dashboard.router, upload.router, agent.router, db_ops.router, rag.router]:
    app.include_router(r, prefix="/api")
