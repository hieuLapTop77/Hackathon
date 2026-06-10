"""
kaggle/src/shap_analysis.py — SHAP feature importance for the best model.
"""
import os
import sys
import warnings
warnings.filterwarnings("ignore")

import matplotlib.pyplot as plt
import shap

_KAGGLE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_KAGGLE_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from kaggle.src.config import OUTPUT_DIR, RANDOM_STATE


def run_shap(models_dict: dict, X_test, feature_names: list,
             best_model_name: str = None, save: bool = True):
    model_to_explain = None
    explain_model_name = best_model_name

    if explain_model_name and explain_model_name in models_dict:
        model = models_dict[explain_model_name]
        # TreeExplainer is only compatible with models having feature_importances_ or specific tree ensembles
        if hasattr(model, "feature_importances_"):
            model_to_explain = model
        else:
            print(f"[shap] Model '{explain_model_name}' is not tree-based. TreeExplainer cannot be used.")

    if model_to_explain is None:
        # Fallback to the first tree-based model in standard models
        for name in ["XGBoost", "LightGBM", "CatBoost", "RandomForest", "GradientBoosting"]:
            if name in models_dict and hasattr(models_dict[name], "feature_importances_"):
                model_to_explain = models_dict[name]
                explain_model_name = name
                print(f"[shap] Falling back to tree-based model '{explain_model_name}' for SHAP analysis.")
                break

    if model_to_explain is None:
        # Fallback to any model in the dictionary that has feature_importances_
        for name, m in models_dict.items():
            if hasattr(m, "feature_importances_"):
                model_to_explain = m
                explain_model_name = name
                print(f"[shap] Falling back to tree-based model '{explain_model_name}' for SHAP analysis.")
                break

    if model_to_explain is None:
        print("[shap] No tree-based model available. Skipping SHAP.")
        return None

    print(f"\n[shap] Computing SHAP values for: {explain_model_name}")

    sample = X_test.sample(min(500, len(X_test)), random_state=RANDOM_STATE)
    explainer = shap.TreeExplainer(model_to_explain)
    shap_values = explainer.shap_values(sample)

    plt.figure(figsize=(12, 7))
    shap.summary_plot(shap_values, sample, feature_names=feature_names,
                      show=False, max_display=15)
    plt.title(f"SHAP Feature Impact -- {explain_model_name} (Tree Model)", fontsize=13)
    plt.tight_layout()

    if save:
        path = os.path.join(OUTPUT_DIR, "shap_summary_best_model.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        print(f"[shap] Saved: {path}")

    plt.show()
    return shap_values
