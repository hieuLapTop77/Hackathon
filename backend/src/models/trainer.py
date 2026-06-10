"""
backend/src/models/trainer.py
==============================
Helper functions to load trained machine learning models.
"""
import os
import json
import joblib
from backend.config import OUTPUTS_DIR

def load_kaggle_models() -> dict:
    """
    Loads all trained model checkpoints from outputs directory.
    Supports combined all_models.pkl and individual models.
    """
    models = {}
    
    # Try loading combined models dictionary first
    all_models_path = os.path.join(OUTPUTS_DIR, "all_models.pkl")
    if os.path.exists(all_models_path):
        try:
            models = joblib.load(all_models_path)
            print(f"[models] Successfully loaded all models from {all_models_path}")
            return models
        except Exception as e:
            print(f"[models] Error loading {all_models_path}: {e}")
            
    # Fallback to individual pkl files
    model_files = {
        "XGBoost": "xgboost_model.pkl",
        "LightGBM": "lightgbm_model.pkl",
        "CatBoost": "catboost_model.pkl",
        "RandomForest": "random_forest_model.pkl",
        "GradientBoosting": "gradient_boosting_model.pkl",
        "MLP": "mlp_model.pkl"
    }
    
    for name, filename in model_files.items():
        path = os.path.join(OUTPUTS_DIR, filename)
        if os.path.exists(path):
            try:
                models[name] = joblib.load(path)
                print(f"[models] Loaded model {name} from {path}")
            except Exception as e:
                print(f"[models] Error loading {name} from {path}: {e}")
                
    return models

def get_best_model_name() -> str:
    """
    Finds the best model name by reading the final training report.
    Defaults to 'XGBoost'.
    """
    report_path = os.path.join(OUTPUTS_DIR, "final_report.json")
    if os.path.exists(report_path):
        try:
            with open(report_path) as f:
                report = json.load(f)
                best_model = report.get("best_model", "XGBoost")
                # If the overall best is Ensemble, return XGBoost or the ensemble strategy.
                if best_model == "WeightedEnsemble":
                    return "XGBoost"  # fallback to best individual model
                return best_model
        except Exception:
            pass
            
    return "XGBoost"
