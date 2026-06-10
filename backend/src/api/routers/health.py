"""
backend/src/api/routers/health.py — Health check and model info endpoints
"""
from datetime import datetime
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "models_loaded": list(request.app.state.models.keys()),
        "best_model": request.app.state.best_model_name,
    }


@router.get("/models")
def get_models(request: Request):
    result = []
    for name, model in request.app.state.models.items():
        if model is not None:
            metrics = request.app.state.model_metrics.get(name, {})
            result.append({
                "name": name,
                "best": name == request.app.state.best_model_name,
                "type": type(model).__name__,
                "mape": metrics.get("mape"),
                "r2":   metrics.get("r2"),
            })
    return {"models": result, "best_model": request.app.state.best_model_name}
