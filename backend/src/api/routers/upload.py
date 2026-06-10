"""
backend/src/api/routers/upload.py — File upload + predict endpoints
"""
import pandas as pd
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, UploadFile, File

from ..services.prediction_service import _predict_and_format_results, _get_model
from backend.src.db import sqlserver

router = APIRouter()


@router.post("/upload-predict")
async def upload_predict(request: Request, file: UploadFile = File(...), model_name: Optional[str] = None):
    """
    Upload a CSV/Excel file and get fare predictions for all rows.
    """
    suffix = file.filename.split(".")[-1].lower()
    if suffix not in ("csv", "xlsx", "xls"):
        raise HTTPException(400, f"Unsupported file type: {suffix}. Use .csv or .xlsx")

    try:
        contents = await file.read()
        await file.seek(0)
        if suffix == "csv":
            df = pd.read_csv(pd.io.common.BytesIO(contents))
        else:
            df = pd.read_excel(pd.io.common.BytesIO(contents), engine="openpyxl")
    except Exception as e:
        raise HTTPException(400, f"Failed to read file: {e}")

    model = _get_model(request.app.state, model_name)
    if model is None:
        print("[upload-predict] WARNING: No model loaded. Using actual prices as preview fallback.")
    return _predict_and_format_results(df, model, request.app.state, file.filename)


# ── Combined: Predict + Save to DB (single endpoint) ─────────────────────────
@router.post("/upload-predict-and-save")
async def upload_predict_and_save(request: Request, file: UploadFile = File(...), model_name: Optional[str] = None):
    """
    Upload a CSV/Excel file, get fare predictions, AND save to SQL Server.
    """
    suffix = file.filename.split(".")[-1].lower()
    if suffix not in ("csv", "xlsx", "xls"):
        raise HTTPException(400, f"Unsupported file type: {suffix}. Use .csv or .xlsx")

    try:
        contents = await file.read()
        print(f"[upload-predict-and-save] Read {len(contents)} bytes from {file.filename}")
        if suffix == "csv":
            df = pd.read_csv(pd.io.common.BytesIO(contents))
        else:
            df = pd.read_excel(pd.io.common.BytesIO(contents), engine="openpyxl")
        print(f"[upload-predict-and-save] DataFrame shape: {df.shape}")
        print(f"[upload-predict-and-save] Columns: {list(df.columns)}")
    except Exception as e:
        raise HTTPException(400, f"Failed to read file: {e}")

    # Normalize column names for DB
    rename_map = {
        "dep": "str_Dep",
        "arr": "str_Arr",
        "price": "mny_GL_Charges_Total",
        "lf": "LF_by_date",
        "lf_fare": "LF_by_fare",
        "fuel_price": "lng_fuel",
        "str_Fare_Class_Short": "str_Fare_Category",
        "str_Fare_Family_Ident": "fare_family",
        "str_Fare_Category_Ident": "str_Fare_Category",
    }
    df_for_db = df.rename(columns=rename_map)
    
    # Extract flight_date from dtm_Local_ETD_Date if present
    if "dtm_Local_ETD_Date" in df_for_db.columns:
        df_for_db["flight_date"] = pd.to_datetime(df_for_db["dtm_Local_ETD_Date"], errors="coerce").dt.date
    elif "dtm_Creation_Date" in df_for_db.columns:
        df_for_db["flight_date"] = pd.to_datetime(df_for_db["dtm_Creation_Date"], errors="coerce").dt.date
    else:
        df_for_db["flight_date"] = pd.Timestamp.today().date()
        print(f"[upload-predict-and-save] WARNING: No date column found, using today")

    # Save to DB
    db_result = {"inserted": 0, "updated": 0}
    if "str_Dep" in df_for_db.columns and "str_Arr" in df_for_db.columns:
        try:
            db_result = sqlserver.upsert_flights(df_for_db)
            print(f"[upload-predict-and-save] DB result: {db_result}")
        except Exception as ex:
            print(f"[upload-predict-and-save] DB error: {ex}")

    model = _get_model(request.app.state, model_name)
    if model is None:
        print("[upload-predict-and-save] WARNING: No model loaded. Using actual prices as preview fallback.")
    return _predict_and_format_results(df, model, request.app.state, file.filename, db_result=db_result)
