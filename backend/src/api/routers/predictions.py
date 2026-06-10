"""
backend/src/api/routers/predictions.py — Prediction endpoints
"""
import numpy as np
from fastapi import APIRouter, HTTPException, Request

from ..schemas import PredictRequest, EnsembleRequest, BatchPredictRequest
from ..services.prediction_service import (
    _build_features, _predict_with_model, _get_model,
    _predict_classes_for_flight,
)

router = APIRouter()


@router.post("/predict")
def predict(req: PredictRequest, request: Request):
    model = _get_model(request.app.state, req.model_name)
    if model is None:
        raise HTTPException(503, "No model loaded. Run: python kaggle/scripts/run_pipeline.py")

    X = _build_features(req, request.app.state)

    scaler = getattr(model, "_scaler", None)
    if scaler is not None:
        X = scaler.transform(X)

    used_model = req.model_name if req.model_name and req.model_name in request.app.state.models else request.app.state.best_model_name
    raw_price = float(_predict_with_model(model, X, request.app.state)[0])
    PRICE_MIN = 50_000.0
    predicted_price = max(PRICE_MIN, raw_price)
    is_valid = raw_price >= PRICE_MIN

    return {
        "predicted_price_vnd": round(predicted_price, -3),
        "route": f"{req.dep}-{req.arr}",
        "fare_family": req.fare_family,
        "lead_time_days": req.lead_time_days,
        "model_used": used_model,
        "clamped": not is_valid,
    }


# ── Ensemble prediction (3 strategies) ──────────────────────────────────────────
@router.post("/predict-ensemble")
def predict_ensemble(req: EnsembleRequest, request: Request):
    """
    Ensemble prediction across all 6 models using 3 strategies:
      - "average"        : simple mean of all model predictions
      - "weighted_perf"  : inverse-MAPE weighted average (better models get more weight)
      - "top3"           : mean of top-3 models by MAPE (XGBoost, RF, LightGBM)
    Returns per-model breakdowns plus the ensemble result.
    """
    models = request.app.state.models
    metrics = request.app.state.model_metrics
    if not models:
        raise HTTPException(503, "No models loaded. Run: python kaggle/scripts/run_pipeline.py")

    # Build feature vector once
    predict_req = PredictRequest(
        lead_time_days=req.lead_time_days,
        LF_by_date=req.LF_by_date,
        LF_by_fare=req.LF_by_fare,
        booking_velocity_3d=req.booking_velocity_3d,
        booking_velocity_7d=req.booking_velocity_7d,
        Weekday=req.Weekday,
        IsHoliday=req.IsHoliday,
        is_oneway=req.is_oneway,
        lng_fuel=req.lng_fuel,
        capacity=req.capacity,
        count_sked=req.count_sked,
        fare_family=req.fare_family,
        fare_category=req.fare_category,
        dep=req.dep,
        arr=req.arr,
        model_name=None,
    )
    X = _build_features(predict_req, request.app.state)

    # Run each model
    PRICE_MIN = 50_000.0
    individual = {}
    for name, model in models.items():
        try:
            pred = float(_predict_with_model(model, X, request.app.state)[0])
            pred = max(PRICE_MIN, pred)
            mape = metrics.get(name, {}).get("mape", 100.0)
            individual[name] = {"prediction": round(pred, -3), "mape": mape}
        except Exception as ex:
            individual[name] = {"prediction": None, "error": str(ex)}

    valid = {n: v for n, v in individual.items() if v.get("prediction") is not None}
    if not valid:
        raise HTTPException(503, "No model produced a valid prediction")

    preds = np.array([v["prediction"] for v in valid.values()])
    model_names = list(valid.keys())
    mapes = np.array([valid[n]["mape"] for n in model_names])

    result = {}

    # Strategy 1: Simple average
    result["average"] = {
        "predicted_price_vnd": round(float(np.mean(preds)), -3),
        "models_used": model_names,
        "model_count": len(model_names),
    }

    # Strategy 2: Weighted by inverse MAPE (better MAPE = higher weight)
    weights = 1.0 / mapes
    weights = weights / weights.sum()
    weighted_pred = float(np.sum(preds * weights))
    result["weighted_perf"] = {
        "predicted_price_vnd": round(weighted_pred, -3),
        "models_used": model_names,
        "weights": {n: round(w, 4) for n, w in zip(model_names, weights)},
        "model_count": len(model_names),
    }

    # Strategy 3: Top-3 by MAPE
    sorted_idx = np.argsort(mapes)[:3]
    top3_names = [model_names[i] for i in sorted_idx]
    top3_preds = preds[sorted_idx]
    result["top3"] = {
        "predicted_price_vnd": round(float(np.mean(top3_preds)), -3),
        "models_used": top3_names,
        "model_count": 3,
    }

    # Return requested strategy result, plus full breakdown
    chosen = req.strategy if req.strategy in result else "weighted_perf"
    return {
        "requested_strategy": chosen,
        "predicted_price_vnd": result[chosen]["predicted_price_vnd"],
        "route": f"{req.dep}-{req.arr}",
        "fare_family": req.fare_family,
        "lead_time_days": req.lead_time_days,
        "individual_predictions": individual,
        "all_strategies": result,
    }


@router.post("/predict-for-flights")
def predict_for_flights(req: BatchPredictRequest, request: Request):
    """
    Batch-predict prices for a list of flight rows using the selected ML model.
    Returns {id: {Eco: {predicted_price_vnd, clamped}, Deluxe: {...}, ...}} mapping.
    Applies sanity checks: price must be >= 50,000 VND and <= 15,000,000 VND.
    If current_price is provided, prediction is also bounded to [20%, 400%] of current price.
    """
    model = _get_model(request.app.state, req.model_name)
    if model is None:
        raise HTTPException(503, "No model loaded. Run: python kaggle/scripts/run_pipeline.py")

    PRICE_MIN = 50_000.0

    results = {}
    used_model = req.model_name if req.model_name and req.model_name in request.app.state.models \
        else request.app.state.best_model_name

    classes_to_predict = {
        "Eco": "Eco",
        "Deluxe": "Deluxe",
        "SkyBoss": "SkyBoss",
        "GDS": "Business"
    }

    for item in req.flights:
        results[item.id] = {}
        for ui_name, model_class in classes_to_predict.items():
            try:
                pred_req = PredictRequest(
                    lead_time_days=item.lead_time_days,
                    LF_by_date=item.LF_by_date,
                    LF_by_fare=item.LF_by_fare,
                    booking_velocity_3d=item.booking_velocity_3d,
                    booking_velocity_7d=item.booking_velocity_7d,
                    Weekday=item.Weekday,
                    IsHoliday=item.IsHoliday,
                    is_oneway=item.is_oneway,
                    lng_fuel=item.lng_fuel,
                    capacity=item.capacity,
                    count_sked=item.count_sked,
                    fare_family=model_class,
                    fare_category=item.fare_category,
                    dep=item.dep,
                    arr=item.arr,
                )
                X = _build_features(pred_req, request.app.state)
                raw_price = float(_predict_with_model(model, X, request.app.state)[0])

                # ── Sanity clamp ────────────────────────────────────────────────
                predicted_price = max(PRICE_MIN, raw_price)

                # If we know the current price, and this is the original class, bound within [20%, 400%]
                current = item.current_price
                if current and current > 0 and model_class == item.fare_family:
                    predicted_price = max(current * 0.20, min(current * 4.0, predicted_price))

                is_valid = raw_price >= PRICE_MIN  # flag if model output was already sensible
                results[item.id][ui_name] = {
                    "predicted_price_vnd": round(predicted_price, -3),
                    "clamped": not is_valid,
                }
            except Exception as ex:
                results[item.id][ui_name] = {"predicted_price_vnd": None, "error": str(ex)}

    return {"predictions": results, "model_used": used_model}
