"""
kaggle/scripts/predict.py — Inference script using trained models.

Usage:
    python kaggle/scripts/predict.py --model xgboost --input data.csv --output predictions.csv
"""
import argparse
import os
import sys

_KAGGLE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_KAGGLE_DIR)
sys.path.insert(0, _PROJECT_ROOT)

import joblib
import pandas as pd
import numpy as np

from kaggle.src.config import OUTPUT_DIR, FEATURE_COLS


MODEL_MAP = {
    "xgboost":         "xgboost_model.pkl",
    "lightgbm":         "lightgbm_model.pkl",
    "catboost":         "catboost_model.pkl",
    "randomforest":     "randomforest_model.pkl",
    "gradientboosting": "gradientboosting_model.pkl",
    "mlp":              "mlp_model.pkl",
}


def load_model(name: str, models_dir: str = None):
    mdir = models_dir or OUTPUT_DIR
    filename = MODEL_MAP.get(name.lower())
    if not filename:
        raise ValueError(f"Unknown model: {name}. Available: {list(MODEL_MAP.keys())}")
    path = os.path.join(mdir, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Model not found: {path}")
    return joblib.load(path)


def load_preprocessing_artifacts(models_dir: str = None):
    """Load imputation values, label encoders, and feature names saved during training."""
    mdir = models_dir or OUTPUT_DIR
    artifacts = {}

    # Imputation values
    imp_path = os.path.join(mdir, "imputation_values.pkl")
    if os.path.exists(imp_path):
        artifacts["imputation"] = joblib.load(imp_path)
        print(f"[predict] Loaded imputation values ({len(artifacts['imputation'])} columns)")
    else:
        print(f"[predict] WARNING: imputation_values.pkl not found at {imp_path}")
        artifacts["imputation"] = {}

    # Label encoders
    le_path = os.path.join(mdir, "label_encoders.pkl")
    if os.path.exists(le_path):
        artifacts["encoders"] = joblib.load(le_path)
        print(f"[predict] Loaded label encoders ({list(artifacts['encoders'].keys())})")
    else:
        print(f"[predict] WARNING: label_encoders.pkl not found at {le_path}")
        artifacts["encoders"] = {}

    # Feature names
    fn_path = os.path.join(mdir, "feature_names.txt")
    if os.path.exists(fn_path):
        with open(fn_path) as f:
            artifacts["feature_names"] = [line.strip() for line in f if line.strip()]
        print(f"[predict] Loaded {len(artifacts['feature_names'])} feature names")
    else:
        artifacts["feature_names"] = FEATURE_COLS

    return artifacts


def preprocess_input(df: pd.DataFrame, artifacts: dict) -> pd.DataFrame:
    """Apply the same preprocessing as training: imputation + label encoding."""
    df = df.copy()

    # Apply imputation (same values as fitted on training set)
    imputation = artifacts.get("imputation", {})
    for col, info in imputation.items():
        if col in df.columns and df[col].isnull().any():
            df[col] = df[col].fillna(info["fill_value"])

    # Apply label encoding with unknown -> -1
    encoders = artifacts.get("encoders", {})
    for raw_col, le in encoders.items():
        enc_col = f"{raw_col}_enc"
        if raw_col in df.columns:
            # Optimize row-by-row le.transform with vectorized dictionary mapping
            mapping = {cls: idx for idx, cls in enumerate(le.classes_)}
            df[enc_col] = df[raw_col].astype(str).map(mapping).fillna(-1).astype(int)

    # Select features in the correct order
    feature_names = artifacts.get("feature_names", FEATURE_COLS)
    available = [c for c in feature_names if c in df.columns]
    missing = [c for c in feature_names if c not in df.columns]

    if missing:
        print(f"[predict] WARNING — missing features (will use 0): {missing}")
        for col in missing:
            df[col] = 0

    X = df[feature_names].fillna(0)
    return X


def predict(model, X: pd.DataFrame) -> np.ndarray:
    """Run prediction, handling MLP scaler and target transformation if present."""
    scaler = getattr(model, "_scaler", None)
    if scaler is not None:
        X = scaler.transform(X)
    raw_pred = model.predict(X)
    
    qt = getattr(model, "_target_transformer", None)
    if qt is not None:
        preds = qt.inverse_transform(raw_pred.reshape(-1, 1)).ravel()
        return np.clip(preds, 0, None)
    elif getattr(model, "_is_log_target", False):
        return np.expm1(raw_pred)
    return raw_pred


def main():
    parser = argparse.ArgumentParser(description="Predict ticket prices using trained models")
    parser.add_argument("--model",   default="xgboost",  help=f"Model name: {list(MODEL_MAP.keys())}")
    parser.add_argument("--input",   required=True,      help="Input CSV with features")
    parser.add_argument("--output",  default="predictions.csv", help="Output CSV path")
    parser.add_argument("--models-dir", default=None,     help="Override models directory")
    args = parser.parse_args()

    models_dir = args.models_dir

    print(f"[predict] Loading model: {args.model}")
    model = load_model(args.model, models_dir)

    print(f"[predict] Loading preprocessing artifacts...")
    artifacts = load_preprocessing_artifacts(models_dir)

    print(f"[predict] Loading input: {args.input}")
    df = pd.read_csv(args.input)

    print(f"[predict] Preprocessing input data...")
    X = preprocess_input(df, artifacts)

    print(f"[predict] Input shape: {X.shape} | Features: {X.shape[1]}")
    preds = predict(model, X)

    out = df.copy()
    out["predicted_price"] = preds
    out.to_csv(args.output, index=False)
    print(f"[predict] Saved {len(preds):,} predictions -> {args.output}")


if __name__ == "__main__":
    main()
