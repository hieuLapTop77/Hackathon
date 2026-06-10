"""
backend/src/api/routers/flights.py — Flight CRUD and listing endpoints
"""
import json
import os
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Request, Query, UploadFile, File, Depends

from ..auth import verify_token
from ..schemas import PredictRequest, ApplyRequest, BulkFareUpdateRequest
from ..services.prediction_service import (
    _build_features, _predict_with_model, _get_model,
    _predict_classes_for_flight,
)
from backend.src.models.optimizer import optimize_flight
from backend.src.db import sqlserver
from backend.config import OUTPUTS_DIR

router = APIRouter()


@router.get("/flights")
def get_flights(
    dep:        str | None = None,
    arr:        str | None = None,
    flight_date: str | None = None,
    flight_no:  str | None = None,
    fare_family: str | None = None,
    sort_by:    str = "flight_date",
    sort_dir:   str = "asc",
    page:       int = Query(1, ge=1),
    page_size:  int = Query(15, ge=1, le=100),
    request: Request = None,
):
    """
    Query flight records from SQL Server with dep/arr/date filters and pagination.
    Returns {items: [...], total: N}.
    Uses ML model prediction for AI Suggestion (optimal_price).
    """
    # Do not restrict date if explicitly empty or omitted
    query_date = flight_date if flight_date else None

    try:
        total = sqlserver.count_flights(
            dep=dep, arr=arr,
            flight_date=query_date,
            flight_no=flight_no,
            fare_family=fare_family,
        )
        df = sqlserver.load_flights(
            dep=dep, arr=arr,
            flight_date=query_date,
            flight_no=flight_no,
            fare_family=fare_family,
            sort_by=sort_by, sort_dir=sort_dir,
            page=page, page_size=page_size,
        )
    except Exception as ex:
        print(f"[get_flights] DB query failed ({ex})")
        return {"items": [], "total": 0}

    if df.empty:
        return {"items": [], "total": total}

    # Get ML model for prediction
    app_state = request.app.state if request else None
    model = _get_model(app_state) if app_state else None
    has_model = model is not None

    flights = []
    for i, (_, r) in enumerate(df.iterrows()):
        price_val = r.get("price")
        price = float(price_val) if pd.notna(price_val) else 0.0

        lf_val = r.get("lf")
        lf = float(lf_val) if pd.notna(lf_val) else 0.0

        capacity_val = r.get("lng_Capacity")
        capacity = int(capacity_val) if pd.notna(capacity_val) else 230

        # Use ML model prediction for AI Suggestion
        if has_model:
            ai_suggestions = _predict_classes_for_flight(r, model, app_state)
            optimal_price = ai_suggestions.get(r.get("fare_family", "Eco"), price)
            if optimal_price is None:
                optimal_price = price
            price_change_pct = round((optimal_price / price - 1) * 100, 2) if price > 0 else 0.0
            
            flight_date_val_temp = r.get("flight_date")
            date_str = str(flight_date_val_temp.isoformat()) if hasattr(flight_date_val_temp, 'isoformat') else str(flight_date_val_temp)
            recommendation = f"Dự đoán: {optimal_price:,.0f} VND (Hạng: {r.get('fare_family', 'Eco')}, Ngày: {date_str}, Tuyến: {r.get('str_Dep', 'SGN')}-{r.get('str_Arr', 'HAN')})"
            optimal_lf = lf
        else:
            # Fallback to math optimizer if no model
            opt = optimize_flight(price, lf, capacity)
            optimal_price = opt["optimal_price"]
            price_change_pct = opt["price_change_pct"]
            optimal_lf = opt["optimal_lf"]
            
            # Fallback suggestions based on pricing ratios
            ai_suggestions = {
                "Eco": round(optimal_price, -3),
                "Deluxe": round(optimal_price * 1.4, -3),
                "SkyBoss": round(optimal_price * 2.2, -3),
                "GDS": round(optimal_price * 3.0, -3)
            }
            
            fare_family_val = str(r.get("fare_family", "Eco") or "Eco")[:20]
            dep_code_temp = str(r.get("str_Dep", "SGN"))
            arr_code_temp = str(r.get("str_Arr", "HAN"))
            flight_date_val_temp = r.get("flight_date")
            date_str = str(flight_date_val_temp.isoformat()) if hasattr(flight_date_val_temp, 'isoformat') else str(flight_date_val_temp)
            recommendation = f"Đề xuất: {optimal_price:,.0f} VND (Hạng: {fare_family_val}, Ngày: {date_str}, Tuyến: {dep_code_temp}-{arr_code_temp})"

        base_rev = price * capacity * lf
        new_rev  = optimal_price * capacity * optimal_lf
        rev_delta = ((new_rev - base_rev) / base_rev * 100) if base_rev > 0 else 0
        status = "high" if lf > 0.75 else "ok" if lf > 0.55 else "mid" if lf > 0.40 else "low"
        dep_code = str(r.get("str_Dep", ""))
        arr_code = str(r.get("str_Arr", ""))
        flight_date_val = r.get("flight_date")
        if hasattr(flight_date_val, 'isoformat'):
            flight_date_val = flight_date_val.isoformat()
        flights.append({
            "id":                int(r.get("id", 100 + i)),
            "flight_no":         r.get("flight_no") or f"A{capacity:03d}",
            "route":             f"{dep_code}->{arr_code}",
            "dep":               dep_code,
            "arr":               arr_code,
            "flight_date":       str(flight_date_val) if flight_date_val else None,
            "lf":                round(lf, 4),
            "price":             round(price, -3),
            "optimal_price":     optimal_price,
            "price_change_pct":  price_change_pct,
            "optimal_lf":        round(optimal_lf, 4),
            "revenue_delta_pct": round(rev_delta, 2),
            "recommendation":    recommendation,
            "status":            status,
            "fare_family":       r.get("fare_family", ""),
            "fare_category":     r.get("str_Fare_Category", ""),
            "capacity":          capacity,
            "ml_model_used":     has_model,
            "lead_time_days":    int(r.get("lead_time_days", 30)) if pd.notna(r.get("lead_time_days")) else 30,
            "LF_by_fare":        float(r.get("LF_by_fare", lf)) if pd.notna(r.get("LF_by_fare")) else lf,
            "booking_velocity_3d": float(r.get("booking_velocity_3d", 0.02)) if pd.notna(r.get("booking_velocity_3d")) else 0.02,
            "booking_velocity_7d": float(r.get("booking_velocity_7d", 0.05)) if pd.notna(r.get("booking_velocity_7d")) else 0.05,
            "Weekday":           int(r.get("Weekday", 4)) if pd.notna(r.get("Weekday")) else 4,
            "IsHoliday":         int(r.get("IsHoliday", 0)) if pd.notna(r.get("IsHoliday")) else 0,
            "is_oneway":         int(r.get("is_oneway", 1)) if pd.notna(r.get("is_oneway")) else 1,
            "lng_fuel":          float(r.get("lng_fuel", 93.86)) if pd.notna(r.get("lng_fuel")) else 93.86,
            "count_sked":        int(r.get("count_sked", 3)) if pd.notna(r.get("count_sked")) else 3,
            "ai_suggestions":    ai_suggestions,
        })
    return {"items": flights, "total": total}


@router.get("/flights/{flight_id}")
def get_flight_detail(flight_id: int):
    """Get detailed flight info including all fare families."""
    flight = sqlserver.load_flight_by_id(flight_id)
    if flight is None:
        raise HTTPException(404, f"Flight {flight_id} not found")

    # Convert numpy types to native Python
    def to_native(val):
        if hasattr(val, 'item'):
            return val.item()
        if hasattr(val, 'isoformat'):
            return str(val)
        return val

    flight = {k: to_native(v) for k, v in flight.items()}

    # Calculate optimal price
    price = float(flight.get("price", 0))
    lf = float(flight.get("lf", 0))
    opt = optimize_flight(price, lf, 230)

    return {
        **flight,
        "optimal_price": opt["optimal_price"],
        "optimal_lf": opt["optimal_lf"],
        "price_change_pct": opt["price_change_pct"],
        "revenue_delta_pct": opt["revenue_delta_pct"],
    }


@router.post("/flights/{flight_id}/apply")
def apply_price(flight_id: str, req: ApplyRequest, user: dict = Depends(verify_token)):
    store_path = os.path.join(OUTPUTS_DIR, "applied_prices.json")
    applied = {}
    if os.path.exists(store_path):
        try:
            with open(store_path, encoding="utf-8") as f:
                applied = json.load(f)
        except Exception:
            pass
    applied[flight_id] = {
        "applied_price": req.applied_price,
        "model_used": req.model_used,
        "saved_at": pd.Timestamp.now().isoformat(),
    }
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(applied, f, ensure_ascii=False, indent=2)
    return {"status": "ok", "flight_id": flight_id, "applied_price": req.applied_price, "model_used": req.model_used}


@router.put("/flights/{flight_id}/fares")
def update_flight_fares(flight_id: int, req: BulkFareUpdateRequest, user: dict = Depends(verify_token)):
    """Update prices and load factors for one or more fare families of a flight."""
    updates = [{"id": u.id, "price": u.price, "lf": u.lf} for u in req.updates]
    result = sqlserver.bulk_update_flight_details(updates)
    return {
        "status": "ok",
        "flight_id": flight_id,
        "updated": result["updated"],
        "failed": result["failed"],
    }


@router.post("/flights/upload")
async def upload_flights_to_db(file: UploadFile = File(...), user: dict = Depends(verify_token)):
    """
    Upload a CSV/Excel file and save all rows to SQL Server.
    After upload, returns the count of rows inserted.
    """
    suffix = file.filename.split(".")[-1].lower()
    if suffix not in ("csv", "xlsx", "xls"):
        raise HTTPException(400, f"Unsupported file type: {suffix}. Use .csv or .xlsx")

    try:
        contents = await file.read()
        print(f"[upload] Read {len(contents)} bytes from {file.filename}")
        if suffix == "csv":
            df = pd.read_csv(pd.io.common.BytesIO(contents))
        else:
            df = pd.read_excel(pd.io.common.BytesIO(contents), engine="openpyxl")
        print(f"[upload] DataFrame shape: {df.shape}")
        print(f"[upload] Columns: {list(df.columns)}")
    except Exception as e:
        raise HTTPException(400, f"Failed to read file: {e}")

    # Normalize column names from upload to DB schema
    rename_map = {
        "dep":          "str_Dep",
        "arr":          "str_Arr",
        "price":        "mny_GL_Charges_Total",
        "lf":           "LF_by_date",
        "lf_fare":      "LF_by_fare",
        "fuel_price":   "lng_fuel",
        "str_Fare_Class_Short":   "str_Fare_Category",
        "str_Fare_Family_Ident":  "fare_family",
        "str_Fare_Category_Ident":"str_Fare_Category",
        "lng_Capacity": "lng_Capacity",
        "lng_Seats":    "lng_Seats",
    }
    df.rename(columns=rename_map, inplace=True)

    # Extract flight_date from dtm_Local_ETD_Date if present
    if "dtm_Local_ETD_Date" in df.columns:
        df["flight_date"] = pd.to_datetime(df["dtm_Local_ETD_Date"], errors="coerce").dt.date
    elif "dtm_Creation_Date" in df.columns:
        df["flight_date"] = pd.to_datetime(df["dtm_Creation_Date"], errors="coerce").dt.date

    # Ensure required columns exist
    if "str_Dep" not in df.columns or "str_Arr" not in df.columns:
        raise HTTPException(400, "File must contain 'dep' and 'arr' (or 'str_Dep'/'str_Arr') columns")

    # Add route column
    df["route"] = df["str_Dep"].astype(str) + "-" + df["str_Arr"].astype(str)

    try:
        result = sqlserver.upsert_flights(df)
        return {
            "status": "ok",
            "rows_inserted": result["inserted"],
            "rows_updated": result["updated"],
            "filename": file.filename,
        }
    except Exception as ex:
        raise HTTPException(500, f"Database error: {ex}")
