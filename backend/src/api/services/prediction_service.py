"""
backend/src/api/services/prediction_service.py — Shared prediction helpers
"""
import numpy as np
import pandas as pd
from typing import Optional

from ..schemas import PredictRequest


def _days_bucket(lead_time_days: int) -> int:
    """Match training preprocessor.py pd.cut bins: [-1, 3, 7, 14, 30, 60, 90, 365]"""
    if lead_time_days <= 3:
        return 0
    elif lead_time_days <= 7:
        return 1
    elif lead_time_days <= 14:
        return 2
    elif lead_time_days <= 30:
        return 3
    elif lead_time_days <= 60:
        return 4
    elif lead_time_days <= 90:
        return 5
    else:
        return 6


def clean_fare_category(val: str) -> str:
    val = str(val).strip()
    for prefix in ["D1", "D2", "FF", "GR", "P6", "Ps"]:
        if val.startswith(prefix):
            return prefix + " "
    if val:
        return val[0] + "  "
    return "B  "


def _build_features(req: PredictRequest, app_state) -> pd.DataFrame:
    route = f"{req.dep}-{req.arr}"

    urgency_score        = round(req.LF_by_date / (req.lead_time_days + 1), 6)
    velocity_ratio       = req.booking_velocity_3d / (req.booking_velocity_7d + 1e-6)
    velocity_ratio       = round(min(10.0, max(0.0, velocity_ratio)), 4)
    seats_remaining      = max(0, int(req.capacity * (1 - req.LF_by_date)))
    is_weekend          = int(req.Weekday in [5, 6])
    days_bucket         = _days_bucket(req.lead_time_days)
    log_lead_time       = round(float(np.log1p(req.lead_time_days)), 4)
    lf_velocity_interact = round(req.LF_by_date * req.booking_velocity_7d, 4)
    expected_sold        = int(round(req.capacity * req.LF_by_date, 0))

    # Time-based features matching preprocessor
    today = pd.Timestamp.now().normalize()
    booking_date = today
    departure_date = today + pd.Timedelta(days=req.lead_time_days)
    
    booking_month = booking_date.month
    dep_month = departure_date.month
    dep_quarter = departure_date.quarter
    dep_day_of_month = departure_date.day
    is_peak_season = int(dep_month in [1, 2, 6, 7, 8])

    # Unused column features
    str_Gender = 1
    seats_sold = 1
    occupancy_rate = round(seats_sold / max(1, req.capacity), 4)

    row = {
        "lead_time_days":        req.lead_time_days,
        "LF_by_date":            req.LF_by_date,
        "LF_by_fare":            req.LF_by_fare,
        "booking_velocity_3d":   req.booking_velocity_3d,
        "booking_velocity_7d":   req.booking_velocity_7d,
        "Weekday":               req.Weekday,
        "IsHoliday":             req.IsHoliday,
        "is_oneway":             req.is_oneway,
        "fuel_price":            req.lng_fuel,
        "capacity":              req.capacity,
        "count_sked":            req.count_sked,
        "urgency_score":         urgency_score,
        "velocity_ratio":        velocity_ratio,
        "seats_remaining":       seats_remaining,
        "is_weekend":            is_weekend,
        "days_bucket":           days_bucket,
        "log_lead_time":         log_lead_time,
        "lf_velocity_interact":   lf_velocity_interact,
        "expected_sold":         expected_sold,
        "dep_month":             dep_month,
        "dep_quarter":           dep_quarter,
        "dep_day_of_month":      dep_day_of_month,
        "booking_month":         booking_month,
        "is_peak_season":        is_peak_season,
        "str_Gender":            str_Gender,
        "occupancy_rate":        occupancy_rate,
        "competitor_price":      getattr(req, "competitor_price", None) if getattr(req, "competitor_price", None) is not None else np.nan,
    }

    label_encoders = getattr(app_state, "label_encoders", {}) or {}
    feature_names = getattr(app_state, "feature_names", []) or []

    for col, enc_col, val in [
        ("fare_family",  "fare_family_enc",  req.fare_family),
        ("fare_category","fare_category_enc", clean_fare_category(req.fare_category)),
        ("route",        "route_enc",        route),
        ("agency_currency", "agency_currency_enc", "VND"),
    ]:
        le = label_encoders.get(col)
        if le:
            val_str = str(val).strip()
            matched_class = None
            for c in le.classes_:
                if str(c).strip() == val_str:
                    matched_class = c
                    break
            if matched_class is not None:
                row[enc_col] = int(le.transform([matched_class])[0])
            else:
                row[enc_col] = -1

    X = pd.DataFrame([row])

    if feature_names:
        for c in feature_names:
            if c not in X.columns:
                X[c] = 0
        X = X[feature_names]
    else:
        models = getattr(app_state, "models", {}) or {}
        best = getattr(app_state, "best_model_name", "XGBoost")
        ref_model = models.get(best) or list(models.values())[0] if models else None
        if ref_model and hasattr(ref_model, "feature_names_in_"):
            for c in ref_model.feature_names_in_:
                if c not in X.columns:
                    X[c] = 0
            X = X[ref_model.feature_names_in_]

    return X


def _build_features_df(df: pd.DataFrame, app_state) -> pd.DataFrame:
    df = df.copy()

    # Normalize column names to standard names and fill defaults if missing
    defaults = {
        "lead_time_days": 30,
        "LF_by_date": 0.65,
        "LF_by_fare": 0.40,
        "booking_velocity_3d": 0.02,
        "booking_velocity_7d": 0.05,
        "Weekday": 4,
        "IsHoliday": 0,
        "is_oneway": 1,
        "lng_fuel": 93.86,
        "capacity": 230,
        "count_sked": 3,
        "fare_family": "Eco",
        "fare_category": "B",
        "dep": "SGN",
        "arr": "HAN",
        "agency_currency": "VND",
        "competitor_price": np.nan,
    }
    
    for col, val in defaults.items():
        if col not in df.columns:
            df[col] = val
        else:
            if col in ["fare_family", "fare_category", "dep", "arr", "agency_currency"]:
                df[col] = df[col].fillna(val).astype(str)
            else:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(val)

    # Clean/clip values like training
    df["LF_by_date"] = df["LF_by_date"].clip(0.0, 1.0)
    df["LF_by_fare"] = df["LF_by_fare"].clip(0.0, 1.0)

    # Derived features matching preprocessor.py & _build_features
    df["route"] = df["dep"] + "-" + df["arr"]
    df["urgency_score"] = (df["LF_by_date"] / (df["lead_time_days"] + 1)).round(6)
    df["velocity_ratio"] = (df["booking_velocity_3d"] / (df["booking_velocity_7d"] + 1e-6)).clip(0.0, 10.0).round(4)
    df["seats_remaining"] = (df["capacity"] * (1.0 - df["LF_by_date"])).clip(lower=0).astype(int)
    df["is_weekend"] = df["Weekday"].isin([5, 6]).astype(int)
    
    # days_bucket bins
    def get_days_bucket_val(lt):
        if lt <= 3: return 0
        elif lt <= 7: return 1
        elif lt <= 14: return 2
        elif lt <= 30: return 3
        elif lt <= 60: return 4
        elif lt <= 90: return 5
        else: return 6
    df["days_bucket"] = df["lead_time_days"].apply(get_days_bucket_val)
    
    df["log_lead_time"] = np.log1p(df["lead_time_days"]).round(4)
    df["lf_velocity_interact"] = (df["LF_by_date"] * df["booking_velocity_7d"]).round(4)
    df["expected_sold"] = (df["capacity"] * df["LF_by_date"]).round(0)
    
    # In training, fuel_price maps from lng_fuel
    df["fuel_price"] = df["lng_fuel"]

    # Time-based features from dates if present
    if "booking_date" in df.columns:
        b_dt = pd.to_datetime(df["booking_date"], errors="coerce")
    else:
        b_dt = pd.Series([pd.Timestamp.now().normalize()] * len(df))
        
    if "departure_date" in df.columns:
        d_dt = pd.to_datetime(df["departure_date"], errors="coerce")
    else:
        d_dt = b_dt + pd.to_timedelta(df["lead_time_days"], unit="D")
        
    b_dt = b_dt.fillna(pd.Timestamp.now().normalize())
    d_dt = d_dt.fillna(b_dt + pd.to_timedelta(df["lead_time_days"], unit="D"))
    
    df["booking_month"] = b_dt.dt.month.fillna(0).astype(int)
    df["dep_month"] = d_dt.dt.month.fillna(0).astype(int)
    df["dep_quarter"] = d_dt.dt.quarter.fillna(0).astype(int)
    df["dep_day_of_month"] = d_dt.dt.day.fillna(0).astype(int)
    df["is_peak_season"] = df["dep_month"].isin([1, 2, 6, 7, 8]).astype(int)

    # Data-derived features
    if "str_Gender" not in df.columns:
        df["str_Gender"] = 1
    else:
        df["str_Gender"] = pd.to_numeric(df["str_Gender"], errors="coerce").fillna(1).astype(int)
        
    if "seats_sold" not in df.columns:
        df["seats_sold"] = 1
    else:
        df["seats_sold"] = pd.to_numeric(df["seats_sold"], errors="coerce").fillna(1).astype(int)
        
    df["occupancy_rate"] = (df["seats_sold"] / df["capacity"].replace(0, 1)).clip(0.0, 1.0).round(4)

    # Encode categorical fields using label encoders
    label_encoders = getattr(app_state, "label_encoders", {}) or {}
    for col, enc_col in [
        ("fare_family", "fare_family_enc"),
        ("fare_category", "fare_category_enc"),
        ("route", "route_enc"),
        ("agency_currency", "agency_currency_enc"),
    ]:
        le = label_encoders.get(col)
        if le:
            class_map = {str(c).strip(): int(le.transform([c])[0]) for c in le.classes_}
            if col == "fare_category":
                df[enc_col] = df[col].apply(lambda x: class_map.get(clean_fare_category(x).strip(), -1))
            else:
                df[enc_col] = df[col].apply(lambda x: class_map.get(str(x).strip(), -1))
        else:
            df[enc_col] = -1

    # Keep only the target training features in correct order
    feature_names = getattr(app_state, "feature_names", []) or []
    if feature_names:
        for col in feature_names:
            if col not in df.columns:
                df[col] = 0
        X = df[feature_names]
    else:
        # Fallback to model's feature names
        models = getattr(app_state, "models", {}) or {}
        best = getattr(app_state, "best_model_name", "XGBoost")
        ref_model = models.get(best) or list(models.values())[0] if models else None
        if ref_model and hasattr(ref_model, "feature_names_in_"):
            for c in ref_model.feature_names_in_:
                if c not in df.columns:
                    df[c] = 0
            X = df[ref_model.feature_names_in_]
        else:
            X = df
            
    return X


def _predict_with_model(model, X, app_state=None):
    """Predict with model and perform correct inverse target transformation."""
    if hasattr(model, "models_dict") and hasattr(model, "weights"):
        preds = []
        total_w = 0
        for name, sub_model in model.models_dict.items():
            w = model.weights.get(name, 0)
            if w > 0:
                p = _predict_with_model(sub_model, X, app_state)
                preds.append(p * w)
                total_w += w
        if total_w > 0:
            return np.sum(preds, axis=0)
        else:
            first_model = list(model.models_dict.values())[0]
            return _predict_with_model(first_model, X, app_state)

    scaler = getattr(model, "_scaler", None)
    if scaler is not None:
        X = scaler.transform(X)
        
    raw_pred = model.predict(X)
    
    qt = getattr(model, "_target_transformer", None)
    if qt is None and app_state is not None:
        qt = getattr(app_state, "target_transformer", None)
        
    if qt is not None:
        if hasattr(raw_pred, "reshape"):
            raw_pred_2d = raw_pred.reshape(-1, 1)
            pred = qt.inverse_transform(raw_pred_2d).ravel()
        else:
            pred = qt.inverse_transform(np.array([[raw_pred]])).ravel()
        return np.clip(pred, 0, None)
        
    is_log = getattr(model, "_is_log_target", False) or (np.mean(raw_pred) < 20.0)
    if is_log:
        return np.expm1(raw_pred)
        
    return raw_pred


def _predict_and_format_results(df: pd.DataFrame, model, app_state, filename: str, db_result: dict = None) -> dict:
    # Rename maps for columns to support multiple input file schemas
    rename_map = {
        "capacity": "capacity",
        "lng_Capacity": "capacity",
        "fare_family": "fare_family",
        "str_Fare_Family_Ident": "fare_family",
        "fare_category": "fare_category",
        "str_Fare_Category_Ident": "fare_category",
        "str_Fare_Class_Short": "fare_category",
        "dep": "dep",
        "str_Dep": "dep",
        "arr": "arr",
        "str_Arr": "arr",
        "fuel_price": "lng_fuel",
        "lng_fuel": "lng_fuel",
        "lf": "LF_by_date",
        "LF_by_date": "LF_by_date",
        "lf_fare": "LF_by_fare",
        "LF_by_fare": "LF_by_fare",
        "dtm_Creation_Date": "booking_date",
        "booking_date": "booking_date",
        "dtm_Local_ETD_Date": "departure_date",
        "departure_date": "departure_date",
        "str_Currency_Ident": "agency_currency",
        "agency_currency": "agency_currency",
        "str_Gender": "str_Gender",
        "lng_Seats": "seats_sold",
        "seats_sold": "seats_sold",
    }
    
    df_rename = {}
    for col in df.columns:
        if col in rename_map:
            df_rename[col] = rename_map[col]
    if df_rename:
        df_norm = df.rename(columns=df_rename)
    else:
        df_norm = df.copy()

    df_norm = df_norm.loc[:, ~df_norm.columns.duplicated()]

    X = _build_features_df(df_norm, app_state)

    def _safe_float(v):
        try:
            import math
            f = float(v)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except Exception:
            return None

    PRICE_MIN = 50_000.0
    df_result = df.copy()

    if model is not None:
        preds = _predict_with_model(model, X, app_state)
        preds = np.maximum(preds, PRICE_MIN)
        df_result["predicted_fare_vnd"] = np.round(preds, -3).astype(int)
        
        mean_pred   = _safe_float(np.round(np.mean(preds), -3))
        median_pred = _safe_float(np.round(np.median(preds), -3))
        min_pred    = _safe_float(np.round(np.min(preds), -3))
        max_pred    = _safe_float(np.round(np.max(preds), -3))
        model_name  = model.__class__.__name__
    else:
        # Fallback if no model is loaded: use actual price or default
        actual_col = "mny_GL_Charges_Total" if "mny_GL_Charges_Total" in df_result.columns else "price" if "price" in df_result.columns else None
        if actual_col:
            prices = pd.to_numeric(df_result[actual_col], errors="coerce").fillna(PRICE_MIN)
            df_result["predicted_fare_vnd"] = np.round(prices, -3).astype(int)
            mean_pred   = _safe_float(np.round(np.mean(prices), -3))
            median_pred = _safe_float(np.round(np.median(prices), -3))
            min_pred    = _safe_float(np.round(np.min(prices), -3))
            max_pred    = _safe_float(np.round(np.max(prices), -3))
        else:
            df_result["predicted_fare_vnd"] = int(PRICE_MIN)
            mean_pred   = PRICE_MIN
            median_pred = PRICE_MIN
            min_pred    = PRICE_MIN
            max_pred    = PRICE_MIN
        model_name  = "None (No model loaded)"

    if "mny_GL_Charges_Total" in df_result.columns:
        df_result["actual_fare_vnd"] = df_result["mny_GL_Charges_Total"]

    def _sanitize_row(row: dict) -> dict:
        out = {}
        for k, v in row.items():
            if isinstance(v, float):
                out[k] = _safe_float(v)
            elif hasattr(v, 'item'):
                out[k] = _safe_float(v.item())
            else:
                out[k] = v
        return out

    preview_rows = [_sanitize_row(r) for r in df_result.head(20).to_dict(orient="records")]
    
    inserted = db_result.get("inserted", 0) if db_result else 0
    updated = db_result.get("updated", 0) if db_result else 0

    return {
        "model_used": model_name,
        "rows_total": len(df_result),
        "preview": preview_rows,
        "summary": {
            "mean_predicted":   mean_pred,
            "median_predicted": median_pred,
            "min_predicted":    min_pred,
            "max_predicted":    max_pred,
        },
        "filename": filename,
        "rows_inserted": inserted,
        "rows_updated": updated,
    }


def _get_model(app_state, model_name: Optional[str] = None):
    models = getattr(app_state, "models", {}) or {}
    best   = getattr(app_state, "best_model_name", "XGBoost")
    if model_name and model_name in models:
        return models[model_name]
    return models.get(best)


def _predict_classes_for_flight(row, model, app_state) -> dict:
    """
    Predict ticket prices for Eco, Deluxe, SkyBoss, and GDS (Business)
    for a single flight record features.
    Returns: { "Eco": float, "Deluxe": float, "SkyBoss": float, "GDS": float }
    """
    PRICE_MIN = 50_000.0

    classes_to_predict = {
        "Eco": "Eco",
        "Deluxe": "Deluxe",
        "SkyBoss": "SkyBoss",
        "GDS": "Business"
    }

    predictions = {}
    lf = float(row.get("lf", 0.65) if row.get("lf") is not None else 0.65)
    price = float(row.get("price", 0.0) if row.get("price") is not None else 0.0)

    for ui_name, model_class in classes_to_predict.items():
        try:
            pred_req = PredictRequest(
                lead_time_days      = int(row.get("lead_time_days", 30)) if pd.notna(row.get("lead_time_days")) else 30,
                LF_by_date          = lf,
                LF_by_fare          = float(row.get("LF_by_fare", lf)) if pd.notna(row.get("LF_by_fare")) else lf,
                booking_velocity_3d = float(row.get("booking_velocity_3d", 0.02)) if pd.notna(row.get("booking_velocity_3d")) else 0.02,
                booking_velocity_7d = float(row.get("booking_velocity_7d", 0.05)) if pd.notna(row.get("booking_velocity_7d")) else 0.05,
                Weekday             = int(row.get("Weekday", 4)) if pd.notna(row.get("Weekday")) else 4,
                IsHoliday           = int(row.get("IsHoliday", 0)) if pd.notna(row.get("IsHoliday")) else 0,
                is_oneway           = int(row.get("is_oneway", 1)) if pd.notna(row.get("is_oneway")) else 1,
                lng_fuel            = float(row.get("lng_fuel", 93.86)) if pd.notna(row.get("lng_fuel")) else 93.86,
                capacity            = int(row.get("lng_Capacity", 230)) if pd.notna(row.get("lng_Capacity")) else 230,
                count_sked          = int(row.get("count_sked", 3)) if pd.notna(row.get("count_sked")) else 3,
                fare_family         = model_class,
                fare_category       = str(row.get("str_Fare_Category", "B") or "B")[:10],
                dep                 = str(row.get("str_Dep", "SGN")),
                arr                 = str(row.get("str_Arr", "HAN")),
            )
            X = _build_features(pred_req, app_state)
            scaler = getattr(model, "_scaler", None)
            predicted_price = float(_predict_with_model(model, X, app_state)[0])
            predicted_price = max(PRICE_MIN, predicted_price)
            
            # Apply typical bounds relative to current price to prevent extreme model output
            actual_class = row.get("fare_family", "")
            if price > 0 and actual_class == model_class:
                predicted_price = max(price * 0.20, min(price * 4.0, predicted_price))
                
            predictions[ui_name] = round(predicted_price, -3)
        except Exception:
            # Ratios for fallback if prediction fails
            ratios = {"Eco": 1.0, "Deluxe": 1.4, "SkyBoss": 2.2, "GDS": 3.0}
            ref_val = price if price > 0 else 1000000.0
            predictions[ui_name] = round(ref_val * ratios[ui_name], -3)

    # Enforce the fare-class ladder (Eco < Deluxe < SkyBoss). Each class is
    # predicted independently by swapping the fare_family feature, and the
    # model's signal for rare premium classes is weak — SkyBoss came out below
    # Deluxe on ~half the flights. Only true inversions are corrected (raised
    # to a 5% minimum premium over the class below); "ladder_adjusted" lists
    # the corrected classes so reports can disclose the calibration.
    LADDER_MIN_STEP = 1.05
    ladder_adjusted = []
    if predictions.get("Deluxe") and predictions.get("Eco") and predictions["Deluxe"] < predictions["Eco"]:
        predictions["Deluxe"] = round(predictions["Eco"] * LADDER_MIN_STEP, -3)
        ladder_adjusted.append("Deluxe")
    if predictions.get("SkyBoss") and predictions.get("Deluxe") and predictions["SkyBoss"] < predictions["Deluxe"]:
        predictions["SkyBoss"] = round(predictions["Deluxe"] * LADDER_MIN_STEP, -3)
        ladder_adjusted.append("SkyBoss")
    predictions["ladder_adjusted"] = ladder_adjusted

    return predictions
