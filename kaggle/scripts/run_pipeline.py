"""
kaggle/scripts/run_pipeline.py — Run the full Kaggle Option 1 pipeline.
Concatenates: load -> preprocess -> train -> visualize -> SHAP.

Usage:
    python kaggle/scripts/run_pipeline.py          # full pipeline
    python kaggle/scripts/run_pipeline.py --skip-train  # load + preprocess only
"""
import argparse
import sys
import os

# Project root is two levels up from kaggle/scripts/
_KAGGLE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # kaggle/
_PROJECT_ROOT = os.path.dirname(_KAGGLE_DIR)                                 # project root/
sys.path.insert(0, _PROJECT_ROOT)

from kaggle.src.data_loader import load
from kaggle.src.preprocessor import preprocess
from kaggle.src.trainer import train_all
from kaggle.src.visualizer import run as viz_run
from kaggle.src.shap_analysis import run_shap


def main(skip_train: bool = False):
    print("=" * 60)
    print("KAGGLE PIPELINE -- OPTION 1 (NO LEAKAGE)")
    print("=" * 60)

    print("\n[STEP 1] Loading data...")
    df = load()

    print("\n[STEP 2] Preprocessing (global, no split leakage)...")
    df_clean, feature_cols = preprocess(df)

    if skip_train:
        print("\n[SKIP] Training skipped (--skip-train)")
        return

    print("\n[STEP 3] Training 6 models (inductive preprocessing)...")
    (models_dict, results_df,
     X_train, X_valid, X_test,
     y_train, y_valid, y_test,
     feat_names, best_model_name) = train_all(df_clean, feature_cols)

    print("\n[STEP 4] Generating visualizations...")
    viz_run(models_dict, X_test, y_test, results_df, feat_names)

    print(f"\n[STEP 5] SHAP analysis (best model: {best_model_name})...")
    run_shap(models_dict, X_test, feat_names, best_model_name=best_model_name)

    best = results_df.iloc[0]
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"\nBest Model : {best['model']}")
    print(f"  MAPE     : {best['mape']:.2f}%")
    print(f"  RMSE     : {best['rmse']:,.0f} VND")
    print(f"  R2       : {best['r2']:.4f}")
    print(f"\nOutputs    -> {os.environ.get('OUTPUT_DIR', 'outputs/kaggle_models')}/")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-train", action="store_true",
        help="Load + preprocess only, skip training",
    )
    args = parser.parse_args()
    main(skip_train=args.skip_train)
