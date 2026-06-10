"""
kaggle/src/trainer.py — Train & evaluate 6 models.
Inductive preprocessing: split FIRST, then fit imputation/encoding on Train only.
Uses QuantileTransformer for target normalization and weighted ensemble.
"""
import os
import sys
import time
import json
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import joblib
import xgboost as xgb
import lightgbm as lgb
from catboost import CatBoostRegressor
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from backend.src.models.pytorch_mlp import PyTorchMLPRegressor
from sklearn.preprocessing import StandardScaler, LabelEncoder, QuantileTransformer
from scipy.optimize import minimize

from sklearn.metrics import (
    mean_absolute_percentage_error,
    mean_squared_error,
    r2_score,
    mean_absolute_error,
)

_KAGGLE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_KAGGLE_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from kaggle.src.config import (
    OUTPUT_DIR, TARGET_COL,
    TEST_SIZE, VALID_SIZE, RANDOM_STATE,
    XGB_PARAMS, LGB_PARAMS, CB_PARAMS,
    RF_PARAMS, GB_PARAMS, MLP_PARAMS,
    CUDA_AVAILABLE,
)

# Tích hợp RAPIDS cuML cho mô hình Random Forest trên GPU khi khả dụng
USE_CUML = False
if CUDA_AVAILABLE:
    try:
        from cuml.ensemble import RandomForestRegressor as cuMLRandomForestRegressor
        USE_CUML = True
        print("[trainer] Phát hiện thư viện RAPIDS cuML! Tự động bật tăng tốc GPU cho Random Forest.")
    except ImportError:
        print("[trainer] Không phát hiện RAPIDS cuML. Chạy Random Forest mặc định trên CPU.")


def compute_metrics(y_true, y_pred) -> dict:
    return {
        "mape": float(mean_absolute_percentage_error(y_true, y_pred) * 100),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae":  float(mean_absolute_error(y_true, y_pred)),
        "r2":   float(r2_score(y_true, y_pred)),
    }


def _imputation_stats(series: pd.Series) -> str:
    if series.dtype in ["int64", "float64"]:
        return "median" if series.dropna().skew() >= 0.5 else "mean"
    return "mode"


def prepare_data(df_clean: pd.DataFrame, feature_cols: list) -> tuple:
    print("\n" + "=" * 60)
    print("INDUCTIVE PREPROCESSING (no data leakage)")
    print("=" * 60)

    target = TARGET_COL
    df = df_clean.copy()

    null_target = df[target].isnull().sum()
    if null_target > 0:
        print(f"[prepare] Dropping {null_target:,} rows with null target")
        df = df.dropna(subset=[target])

    # --- Temporal split (airline pricing is time-series data) ---
    # Sort by date to avoid temporal leakage: training on past, testing on future
    date_col = None
    for candidate in ["departure_date", "booking_date", "flight_date"]:
        if candidate in df.columns:
            date_col = candidate
            break

    if date_col:
        print(f"[prepare] Using temporal split on '{date_col}'")
        df = df.sort_values(date_col).reset_index(drop=True)
    else:
        print(f"[prepare] WARNING: No date column found, falling back to random split")
        df = df.sample(frac=1, random_state=RANDOM_STATE).reset_index(drop=True)

    n = len(df)
    test_start = int(n * (1 - TEST_SIZE))
    valid_start = int(test_start * (1 - VALID_SIZE / (1 - TEST_SIZE)))

    X_train = df.iloc[:valid_start].copy()
    X_valid = df.iloc[valid_start:test_start].copy()
    X_test  = df.iloc[test_start:].copy()
    y_train = X_train[target]
    y_valid = X_valid[target]
    y_test  = X_test[target]

    print(f"[prepare] Split: Train={len(X_train):,} | Valid={len(X_valid):,} | Test={len(X_test):,}")

    imputation_values = {}
    print("\n[prepare] Inductive numeric imputation (fit on Train only):")
    for col in X_train.select_dtypes(include=[np.number]).columns:
        strategy = _imputation_stats(X_train[col])
        fill_val = X_train[col].median() if strategy == "median" else X_train[col].mean()
        imputation_values[col] = {"strategy": strategy, "fill_value": fill_val}
        X_train[col] = X_train[col].fillna(fill_val)
        X_valid[col] = X_valid[col].fillna(fill_val)
        X_test[col]  = X_test[col].fillna(fill_val)
        print(f"  [impute] {col}: {strategy}={fill_val:,.2f}")

    encoders = {}
    print("\n[prepare] Inductive LabelEncoder (fit on Train only):")
    for raw_col, enc_col in [
        ("fare_family",     "fare_family_enc"),
        ("fare_category",   "fare_category_enc"),
        ("route",           "route_enc"),
        ("agency_currency", "agency_currency_enc"),
    ]:
        if raw_col not in X_train.columns:
            continue
        le = LabelEncoder()
        X_train[enc_col] = le.fit_transform(X_train[raw_col].astype(str))
        
        # Optimize row-by-row le.transform with vectorized dictionary mapping
        mapping = {cls: idx for idx, cls in enumerate(le.classes_)}
        X_valid[enc_col] = X_valid[raw_col].astype(str).map(mapping).fillna(-1).astype(int)
        X_test[enc_col]  = X_test[raw_col].astype(str).map(mapping).fillna(-1).astype(int)
        
        encoders[raw_col] = le
        print(f"  [encode] {raw_col}: {len(le.classes_)} classes")

    available = [c for c in feature_cols if c in X_train.columns]
    X_train_feat = X_train[available].fillna(0)
    X_valid_feat = X_valid[available].fillna(0)
    X_test_feat  = X_test[available].fillna(0)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    joblib.dump(encoders, f"{OUTPUT_DIR}/label_encoders.pkl")
    joblib.dump(imputation_values, f"{OUTPUT_DIR}/imputation_values.pkl")

    print(f"\n[prepare] Feature matrix: {X_train_feat.shape[1]} features")
    print(f"[prepare] Encoders saved -> {OUTPUT_DIR}/label_encoders.pkl")

    return (
        X_train_feat, X_valid_feat, X_test_feat,
        y_train.reset_index(drop=True),
        y_valid.reset_index(drop=True),
        y_test.reset_index(drop=True),
        encoders, imputation_values, available,
    )


def _fit_target_transformer(y_train):
    """Fit QuantileTransformer on training target for better normalization."""
    qt = QuantileTransformer(
        n_quantiles=min(10000, len(y_train)),
        output_distribution="normal",
        random_state=RANDOM_STATE,
    )
    qt.fit(y_train.values.reshape(-1, 1))
    return qt


def _transform_target(qt, y):
    return qt.transform(y.values.reshape(-1, 1)).ravel()


def _inverse_transform_target(qt, y_transformed):
    return qt.inverse_transform(y_transformed.reshape(-1, 1)).ravel()


def train_xgboost(X_train, y_train, X_valid, y_valid, X_test, y_test, target_transformer=None):
    print("\n" + "-" * 40)
    print("Training XGBoost (QuantileTransformer Target)...")
    print("-" * 40)
    t0 = time.time()
    if target_transformer is not None:
        y_tr = _transform_target(target_transformer, y_train)
        y_vl = _transform_target(target_transformer, y_valid)
    else:
        y_tr = np.log1p(y_train)
        y_vl = np.log1p(y_valid)
    model = xgb.XGBRegressor(**XGB_PARAMS)
    model.set_params(early_stopping_rounds=50, eval_metric="rmse")
    model.fit(X_train, y_tr, eval_set=[(X_valid, y_vl)], verbose=100)
    model._target_transformer = target_transformer
    model._is_log_target = (target_transformer is None)
    elapsed = time.time() - t0
    preds_raw = model.predict(X_test)
    if target_transformer is not None:
        preds = _inverse_transform_target(target_transformer, preds_raw)
    else:
        preds = np.expm1(preds_raw)
    preds = np.clip(preds, 0, None)
    metrics = compute_metrics(y_test, preds)
    metrics["time_sec"] = elapsed
    metrics["model"] = "XGBoost"
    print(f"XGBoost done in {elapsed:.1f}s | MAPE: {metrics['mape']:.2f}% | R2: {metrics['r2']:.4f}")
    return model, metrics


def train_lightgbm(X_train, y_train, X_valid, y_valid, X_test, y_test, target_transformer=None):
    print("\n" + "-" * 40)
    print("Training LightGBM (QuantileTransformer Target)...")
    print("-" * 40)
    t0 = time.time()
    if target_transformer is not None:
        y_tr = _transform_target(target_transformer, y_train)
        y_vl = _transform_target(target_transformer, y_valid)
    else:
        y_tr = np.log1p(y_train)
        y_vl = np.log1p(y_valid)
    model = lgb.LGBMRegressor(**LGB_PARAMS)
    model.fit(
        X_train, y_tr,
        eval_set=[(X_train, y_tr), (X_valid, y_vl)],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)],
    )
    model._target_transformer = target_transformer
    model._is_log_target = (target_transformer is None)
    elapsed = time.time() - t0
    preds_raw = model.predict(X_test)
    if target_transformer is not None:
        preds = _inverse_transform_target(target_transformer, preds_raw)
    else:
        preds = np.expm1(preds_raw)
    preds = np.clip(preds, 0, None)
    metrics = compute_metrics(y_test, preds)
    metrics["time_sec"] = elapsed
    metrics["model"] = "LightGBM"
    print(f"LightGBM done in {elapsed:.1f}s | MAPE: {metrics['mape']:.2f}% | R2: {metrics['r2']:.4f}")
    return model, metrics


def train_catboost(X_train, y_train, X_valid, y_valid, X_test, y_test, target_transformer=None):
    print("\n" + "-" * 40)
    print("Training CatBoost (QuantileTransformer Target)...")
    print("-" * 40)
    t0 = time.time()
    if target_transformer is not None:
        y_tr = _transform_target(target_transformer, y_train)
        y_vl = _transform_target(target_transformer, y_valid)
    else:
        y_tr = np.log1p(y_train)
        y_vl = np.log1p(y_valid)
    model = CatBoostRegressor(**CB_PARAMS)
    model.fit(X_train, y_tr, eval_set=(X_valid, y_vl), early_stopping_rounds=50)
    model._target_transformer = target_transformer
    model._is_log_target = (target_transformer is None)
    elapsed = time.time() - t0
    preds_raw = model.predict(X_test)
    if target_transformer is not None:
        preds = _inverse_transform_target(target_transformer, preds_raw)
    else:
        preds = np.expm1(preds_raw)
    preds = np.clip(preds, 0, None)
    metrics = compute_metrics(y_test, preds)
    metrics["time_sec"] = elapsed
    metrics["model"] = "CatBoost"
    print(f"CatBoost done in {elapsed:.1f}s | MAPE: {metrics['mape']:.2f}% | R2: {metrics['r2']:.4f}")
    return model, metrics


def train_random_forest(X_train, y_train, X_test, y_test):
    print("\n" + "-" * 40)
    print(f"Training Random Forest ({'GPU via cuML' if USE_CUML else 'CPU via sklearn'})...")
    print("-" * 40)
    t0 = time.time()
    if USE_CUML:
        # Chuyển đổi dữ liệu sang float32 để cuML tối ưu tốt nhất trên GPU
        X_tr = X_train.astype(np.float32)
        y_tr = y_train.astype(np.float32)
        X_te = X_test.astype(np.float32)
        model = cuMLRandomForestRegressor(**RF_PARAMS)
        model.fit(X_tr, y_tr)
        preds = model.predict(X_te)
        if hasattr(preds, "to_numpy"):
            preds = preds.to_numpy()
        else:
            preds = np.asarray(preds)
    else:
        model = RandomForestRegressor(**RF_PARAMS)
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
    elapsed = time.time() - t0
    metrics = compute_metrics(y_test, preds)
    metrics["time_sec"] = elapsed
    metrics["model"] = "RandomForest"
    print(f"Random Forest done in {elapsed:.1f}s | MAPE: {metrics['mape']:.2f}% | R2: {metrics['r2']:.4f}")
    return model, metrics


def train_gradient_boosting(X_train, y_train, X_test, y_test):
    print("\n" + "-" * 40)
    print("Training Gradient Boosting (sklearn)...")
    print("-" * 40)
    t0 = time.time()
    model = GradientBoostingRegressor(**GB_PARAMS)
    model.fit(X_train, y_train)
    elapsed = time.time() - t0
    metrics = compute_metrics(y_test, model.predict(X_test))
    metrics["time_sec"] = elapsed
    metrics["model"] = "GradientBoosting"
    print(f"Gradient Boosting done in {elapsed:.1f}s | MAPE: {metrics['mape']:.2f}% | R2: {metrics['r2']:.4f}")
    return model, metrics


def train_mlp(X_train, y_train, X_valid, y_valid, X_test, y_test, target_transformer=None):
    print("\n" + "-" * 40)
    print("Training PyTorch GPU MLP Neural Network (QuantileTransformer Target)...")
    print("-" * 40)
    scaler = StandardScaler()
    X_tr = scaler.fit_transform(X_train)
    X_vl = scaler.transform(X_valid)
    X_te = scaler.transform(X_test)
    t0 = time.time()
    
    if target_transformer is not None:
        y_tr = _transform_target(target_transformer, y_train)
        y_vl = _transform_target(target_transformer, y_valid)
    else:
        y_tr = np.log1p(y_train)
        y_vl = np.log1p(y_valid)
        
    model = PyTorchMLPRegressor(**MLP_PARAMS)
    model.fit(X_tr, y_tr, eval_set=(X_vl, y_vl))
    
    elapsed = time.time() - t0
    model._scaler = scaler
    model._target_transformer = target_transformer
    model._is_log_target = (target_transformer is None)
    
    preds_raw = model.predict(X_te)
    if target_transformer is not None:
        preds = _inverse_transform_target(target_transformer, preds_raw)
    else:
        preds = np.expm1(preds_raw)
    preds = np.clip(preds, 0, None)
    
    metrics = compute_metrics(y_test, preds)
    metrics["time_sec"] = elapsed
    metrics["model"] = "MLP"
    print(f"PyTorch GPU MLP done in {elapsed:.1f}s | MAPE: {metrics['mape']:.2f}% | R2: {metrics['r2']:.4f}")
    return model, metrics


def predict_with_model(model, X):
    """Predict with a single model, handling scaler and target transformation."""
    scaler = getattr(model, "_scaler", None)
    if scaler is not None:
        X = scaler.transform(X)
    raw_pred = model.predict(X)
    qt = getattr(model, "_target_transformer", None)
    if qt is not None:
        return np.clip(_inverse_transform_target(qt, raw_pred), 0, None)
    elif getattr(model, "_is_log_target", False):
        return np.expm1(raw_pred)
    return raw_pred


def _optimize_ensemble_weights(models_dict, X_valid, y_valid):
    """Find optimal ensemble weights using validation set."""
    print("\n" + "-" * 40)
    print("Optimizing Ensemble Weights...")
    print("-" * 40)

    model_names = list(models_dict.keys())
    preds_list = []
    for name in model_names:
        p = predict_with_model(models_dict[name], X_valid)
        preds_list.append(p)
    preds_matrix = np.column_stack(preds_list)

    def objective(weights):
        w = np.abs(weights) / np.abs(weights).sum()  # normalize
        ensemble_pred = preds_matrix @ w
        return mean_absolute_percentage_error(y_valid, ensemble_pred)

    n = len(model_names)
    x0 = np.ones(n) / n
    result = minimize(objective, x0, method="Nelder-Mead",
                      options={"maxiter": 1000, "xatol": 1e-6})
    optimal_weights = np.abs(result.x) / np.abs(result.x).sum()

    print("Optimal Ensemble Weights:")
    for name, w in zip(model_names, optimal_weights):
        print(f"  {name}: {w:.4f}")

    return dict(zip(model_names, optimal_weights))


def predict_ensemble(models_dict, weights, X):
    """Weighted ensemble prediction."""
    preds = []
    total_w = 0
    for name, model in models_dict.items():
        w = weights.get(name, 0)
        if w > 0:
            p = predict_with_model(model, X)
            preds.append(p * w)
            total_w += w
    return np.sum(preds, axis=0) / total_w if total_w > 0 else predict_with_model(list(models_dict.values())[0], X)


def train_all(df_clean: pd.DataFrame, feature_cols: list):
    print("\n" + "=" * 60)
    print("TRAINING ML MODELS (with QuantileTransformer + Ensemble)")
    print("=" * 60)

    (X_train, X_valid, X_test,
     y_train, y_valid, y_test,
     encoders, imputation_values,
     feature_names) = prepare_data(df_clean, feature_cols)

    # Fit QuantileTransformer on training target
    print("\n[trainer] Fitting QuantileTransformer on training target...")
    qt = _fit_target_transformer(y_train)
    joblib.dump(qt, f"{OUTPUT_DIR}/target_transformer.pkl")
    print(f"[trainer] QuantileTransformer saved -> {OUTPUT_DIR}/target_transformer.pkl")

    results = []
    models_dict = {}

    model_xgb, m = train_xgboost(X_train, y_train, X_valid, y_valid, X_test, y_test, qt)
    models_dict["XGBoost"] = model_xgb
    results.append(m)

    model_lgb, m = train_lightgbm(X_train, y_train, X_valid, y_valid, X_test, y_test, qt)
    models_dict["LightGBM"] = model_lgb
    results.append(m)

    model_cb, m = train_catboost(X_train, y_train, X_valid, y_valid, X_test, y_test, qt)
    models_dict["CatBoost"] = model_cb
    results.append(m)

    model_rf, m = train_random_forest(X_train, y_train, X_test, y_test)
    models_dict["RandomForest"] = model_rf
    results.append(m)

    model_gb, m = train_gradient_boosting(X_train, y_train, X_test, y_test)
    models_dict["GradientBoosting"] = model_gb
    results.append(m)

    model_mlp, m = train_mlp(X_train, y_train, X_valid, y_valid, X_test, y_test, qt)
    models_dict["MLP"] = model_mlp
    results.append(m)

    results_df = pd.DataFrame(results).sort_values("mape")
    print("\n" + "=" * 60)
    print("INDIVIDUAL MODEL COMPARISON (Test Set)")
    print("=" * 60)
    print(results_df[["model", "mape", "rmse", "mae", "r2", "time_sec"]].to_string(index=False))

    best = results_df.iloc[0]
    print(f"\nBest Individual: {best['model']} | MAPE: {best['mape']:.2f}% | R2: {best['r2']:.4f}")

    # --- Weighted Ensemble ---
    ensemble_weights = _optimize_ensemble_weights(models_dict, X_valid, y_valid)
    ensemble_preds = predict_ensemble(models_dict, ensemble_weights, X_test)
    ensemble_metrics = compute_metrics(y_test, ensemble_preds)
    ensemble_metrics["model"] = "WeightedEnsemble"
    ensemble_metrics["time_sec"] = 0
    results.append(ensemble_metrics)

    print("\n" + "=" * 60)
    print("ENSEMBLE RESULT (Test Set)")
    print("=" * 60)
    print(f"Ensemble MAPE: {ensemble_metrics['mape']:.2f}% | R2: {ensemble_metrics['r2']:.4f}")

    # Update results with ensemble
    results_df = pd.DataFrame(results).sort_values("mape")
    print("\n" + "=" * 60)
    print("FINAL MODEL COMPARISON (Test Set)")
    print("=" * 60)
    print(results_df[["model", "mape", "rmse", "mae", "r2", "time_sec"]].to_string(index=False))

    best = results_df.iloc[0]
    print(f"\nBest Overall: {best['model']} | MAPE: {best['mape']:.2f}% | R2: {best['r2']:.4f}")

    # --- Save artifacts ---
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for name, model in models_dict.items():
        safe = name.lower().replace(" ", "_")
        joblib.dump(model, f"{OUTPUT_DIR}/{safe}_model.pkl")
    joblib.dump(models_dict, f"{OUTPUT_DIR}/all_models.pkl")
    joblib.dump(ensemble_weights, f"{OUTPUT_DIR}/ensemble_weights.pkl")
    if "MLP" in models_dict:
        joblib.dump(models_dict["MLP"]._scaler, f"{OUTPUT_DIR}/mlp_scaler.pkl")

    results_df.to_csv(f"{OUTPUT_DIR}/model_comparison.csv", index=False)

    with open(f"{OUTPUT_DIR}/feature_names.txt", "w") as f:
        f.write("\n".join(feature_names))

    best_model_name = str(best["model"])
    final_report = {
        "best_model": best_model_name,
        "best_mape":  round(float(best["mape"]), 4),
        "best_rmse":  round(float(best["rmse"]), 2),
        "best_mae":   round(float(best["mae"]), 2),
        "best_r2":    round(float(best["r2"]), 6),
        "ensemble_weights": {k: round(v, 4) for k, v in ensemble_weights.items()},
        "all_models_ranked": results_df.to_dict("records"),
        "preprocessing": "inductive (fit on Train only)",
        "target_transformation": "QuantileTransformer(normal)",
        "training_summary": {
            "n_features":   len(feature_names),
            "train_rows":   len(X_train),
            "valid_rows":   len(X_valid),
            "test_rows":    len(X_test),
        },
    }
    with open(f"{OUTPUT_DIR}/final_report.json", "w") as f:
        json.dump(final_report, f, indent=2)

    print(f"\n[trainer] All artifacts saved to: {OUTPUT_DIR}/")
    return (
        models_dict, results_df,
        X_train, X_valid, X_test,
        y_train, y_valid, y_test,
        feature_names, best_model_name,
    )


if __name__ == "__main__":
    from kaggle.src.data_loader import load
    from kaggle.src.preprocessor import preprocess
    df = load()
    df_clean, feats = preprocess(df)
    train_all(df_clean, feats)
