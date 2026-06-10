"""
kaggle/src/tuner.py — Hyperparameter tuning with Optuna.
Run this script to find optimal hyperparameters, then update config.py.
Usage: python -m kaggle.src.tuner [--n-trials 50]
"""
import os
import sys
import time
import argparse
import warnings
warnings.filterwarnings("ignore")

import numpy as np

_KAGGLE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_KAGGLE_DIR)
sys.path.insert(0, _PROJECT_ROOT)

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("Optuna not installed. Run: pip install optuna")
    sys.exit(1)

import xgboost as xgb
import lightgbm as lgb
from catboost import CatBoostRegressor
from sklearn.metrics import mean_absolute_percentage_error

from kaggle.src.config import OUTPUT_DIR, RANDOM_STATE
from kaggle.src.data_loader import load
from kaggle.src.preprocessor import preprocess
from kaggle.src.trainer import prepare_data, _fit_target_transformer, _transform_target, _inverse_transform_target


def xgb_objective(trial, X_train, y_tr, X_valid, y_vl, y_valid_orig, qt):
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 500, 2000, step=100),
        "max_depth": trial.suggest_int("max_depth", 4, 10),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 20),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.001, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 0.001, 10.0, log=True),
        "random_state": RANDOM_STATE,
        "n_jobs": -1,
        "tree_method": "hist",
    }
    model = xgb.XGBRegressor(**params)
    model.set_params(early_stopping_rounds=50, eval_metric="rmse")
    model.fit(X_train, y_tr, eval_set=[(X_valid, y_vl)], verbose=False)

    preds_raw = model.predict(X_valid)
    preds = np.clip(_inverse_transform_target(qt, preds_raw), 0, None)
    return mean_absolute_percentage_error(y_valid_orig, preds)


def lgb_objective(trial, X_train, y_tr, X_valid, y_vl, y_valid_orig, qt):
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 500, 2000, step=100),
        "max_depth": trial.suggest_int("max_depth", 4, 10),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 15, 127),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.001, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 0.001, 10.0, log=True),
        "random_state": RANDOM_STATE,
        "n_jobs": -1,
        "verbose": -1,
    }
    model = lgb.LGBMRegressor(**params)
    model.fit(
        X_train, y_tr,
        eval_set=[(X_valid, y_vl)],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

    preds_raw = model.predict(X_valid)
    preds = np.clip(_inverse_transform_target(qt, preds_raw), 0, None)
    return mean_absolute_percentage_error(y_valid_orig, preds)


def cb_objective(trial, X_train, y_tr, X_valid, y_vl, y_valid_orig, qt):
    params = {
        "iterations": trial.suggest_int("iterations", 400, 1500, step=100),
        "depth": trial.suggest_int("depth", 4, 10),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
        "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 0.1, 10.0, log=True),
        "random_seed": RANDOM_STATE,
        "verbose": 0,
        "thread_count": -1,
    }
    model = CatBoostRegressor(**params)
    model.fit(X_train, y_tr, eval_set=(X_valid, y_vl), early_stopping_rounds=50)

    preds_raw = model.predict(X_valid)
    preds = np.clip(_inverse_transform_target(qt, preds_raw), 0, None)
    return mean_absolute_percentage_error(y_valid_orig, preds)


def run_tuning(n_trials=50):
    print("=" * 60)
    print(f"HYPERPARAMETER TUNING with Optuna ({n_trials} trials per model)")
    print("=" * 60)

    # Load and preprocess data
    print("\n[tuner] Loading and preprocessing data...")
    df = load()
    df_clean, feats = preprocess(df)

    (X_train, X_valid, _,
     y_train, y_valid, _,
     _, _,
     _) = prepare_data(df_clean, feats)

    # Fit QuantileTransformer
    qt = _fit_target_transformer(y_train)
    y_tr = _transform_target(qt, y_train)
    y_vl = _transform_target(qt, y_valid)

    best_params = {}

    # --- Tune XGBoost ---
    print("\n" + "=" * 40)
    print("Tuning XGBoost...")
    print("=" * 40)
    t0 = time.time()
    study_xgb = optuna.create_study(direction="minimize")
    study_xgb.optimize(
        lambda trial: xgb_objective(trial, X_train, y_tr, X_valid, y_vl, y_valid, qt),
        n_trials=n_trials,
    )
    best_params["XGBoost"] = study_xgb.best_params
    print(f"XGBoost best MAPE: {study_xgb.best_value * 100:.2f}% ({time.time()-t0:.0f}s)")
    print(f"Best params: {study_xgb.best_params}")

    # --- Tune LightGBM ---
    print("\n" + "=" * 40)
    print("Tuning LightGBM...")
    print("=" * 40)
    t0 = time.time()
    study_lgb = optuna.create_study(direction="minimize")
    study_lgb.optimize(
        lambda trial: lgb_objective(trial, X_train, y_tr, X_valid, y_vl, y_valid, qt),
        n_trials=n_trials,
    )
    best_params["LightGBM"] = study_lgb.best_params
    print(f"LightGBM best MAPE: {study_lgb.best_value * 100:.2f}% ({time.time()-t0:.0f}s)")
    print(f"Best params: {study_lgb.best_params}")

    # --- Tune CatBoost ---
    print("\n" + "=" * 40)
    print("Tuning CatBoost...")
    print("=" * 40)
    t0 = time.time()
    study_cb = optuna.create_study(direction="minimize")
    study_cb.optimize(
        lambda trial: cb_objective(trial, X_train, y_tr, X_valid, y_vl, y_valid, qt),
        n_trials=n_trials,
    )
    best_params["CatBoost"] = study_cb.best_params
    print(f"CatBoost best MAPE: {study_cb.best_value * 100:.2f}% ({time.time()-t0:.0f}s)")
    print(f"Best params: {study_cb.best_params}")

    # Save results
    import json
    output_path = os.path.join(OUTPUT_DIR, "optuna_best_params.json")
    with open(output_path, "w") as f:
        json.dump(best_params, f, indent=2)
    print(f"\n[tuner] Best params saved to: {output_path}")

    print("\n" + "=" * 60)
    print("TUNING COMPLETE — Update config.py with these params:")
    print("=" * 60)
    for model_name, params in best_params.items():
        print(f"\n{model_name}:")
        for k, v in params.items():
            print(f"  {k} = {v}")

    return best_params


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hyperparameter tuning with Optuna")
    parser.add_argument("--n-trials", type=int, default=50, help="Number of trials per model")
    args = parser.parse_args()
    run_tuning(args.n_trials)
