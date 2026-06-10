"""
kaggle/src/config.py — Configuration for Option 1 (No Leakage) pipeline.
"""
import os

# Project root is two levels up from kaggle/src/
_KAGGLE_DIR   = os.path.dirname(os.path.abspath(__file__))       # kaggle/src/
_KAGGLE_ROOT  = os.path.dirname(_KAGGLE_DIR)                      # kaggle/
PROJECT_ROOT   = os.path.dirname(_KAGGLE_ROOT)                    # project root/

# ── Data source ────────────────────────────────────────────────────────────────
GDRIVE_FILE_ID    = "1PE12XPZYKV8Rfn8KY9QTym69dYdxkFJk"
USE_DIRECT_UPLOAD  = False

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR       = os.environ.get("DATA_DIR",       os.path.join(PROJECT_ROOT, "data", "AI_hackathon"))
OUTPUT_DIR     = os.environ.get("OUTPUT_DIR",     os.path.join(PROJECT_ROOT, "outputs"))
DATA_PROCESSED = os.environ.get("DATA_PROCESSED", os.path.join(PROJECT_ROOT, "outputs", "processed"))

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_PROCESSED, exist_ok=True)

# ── Data filtering ────────────────────────────────────────────────────────────
LEAD_TIME_MIN = 0
LEAD_TIME_MAX = 365
MIN_PRICE     = 50_000

# ── Feature Engineering (Option 1 — NO LEAKAGE) ───────────────────────────────
FEATURE_COLS = [
    # ── Original features ──
    "lead_time_days", "booking_velocity_3d", "booking_velocity_7d",
    "LF_by_date", "LF_by_fare", "capacity",
    "Weekday", "IsHoliday", "is_oneway",
    "fuel_price", "count_sked",
    "fare_family_enc", "fare_category_enc", "route_enc",
    "urgency_score", "velocity_ratio", "seats_remaining",
    "is_weekend", "days_bucket",
    "log_lead_time", "lf_velocity_interact", "expected_sold",
    # ── NEW: Time-based features ──
    "dep_month", "dep_quarter", "dep_day_of_month",
    "booking_month", "is_peak_season",
    # ── NEW: Data-derived features ──
    "str_Gender", "agency_currency_enc",
    "competitor_price",
]

TARGET_COL = "ticket_price"

LEAKAGE_COLS = [
    "price_gap", "price_gap_pct",
    "price_advantage_pct", "competitor_name", "occupancy_rate",
]

# ── Train / Test Split ────────────────────────────────────────────────────────
TEST_SIZE    = 0.15
VALID_SIZE   = 0.15
RANDOM_STATE = 42

# ── GPU availability check ───────────────────────────────────────────────────
CUDA_AVAILABLE = False
try:
    import torch
    CUDA_AVAILABLE = torch.cuda.is_available()
except ImportError:
    pass

# ── Model Hyperparameters ────────────────────────────────────────────────────
XGB_PARAMS = dict(
    n_estimators=800, max_depth=6, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8,
    min_child_weight=5, reg_alpha=0.1, reg_lambda=1.0,
    random_state=RANDOM_STATE, n_jobs=-1, device="cuda" if CUDA_AVAILABLE else "cpu",
)

LGB_PARAMS = dict(
    n_estimators=800, max_depth=6, learning_rate=0.05,
    num_leaves=31, subsample=0.8, colsample_bytree=0.8,
    min_child_samples=20, reg_alpha=0.1, reg_lambda=1.0,
    random_state=RANDOM_STATE, n_jobs=-1, verbose=-1,
    device="gpu" if CUDA_AVAILABLE else "cpu",
)

CB_PARAMS = dict(
    iterations=600, depth=6, learning_rate=0.05,
    l2_leaf_reg=3.0, random_seed=RANDOM_STATE,
    verbose=100, task_type="GPU" if CUDA_AVAILABLE else "CPU",
)

RF_PARAMS = dict(
    n_estimators=300, max_depth=15,
    min_samples_split=10, min_samples_leaf=5,
    max_features=0.7, random_state=RANDOM_STATE, n_jobs=-1,
)

GB_PARAMS = dict(
    n_estimators=400, max_depth=5, learning_rate=0.05,
    subsample=0.8, min_samples_split=10, min_samples_leaf=5,
    random_state=RANDOM_STATE,
)

MLP_PARAMS = dict(
    hidden_layer_sizes=(128, 64, 32),
    learning_rate=0.001,
    epochs=40,
    batch_size=4096,
    random_state=RANDOM_STATE,
)

