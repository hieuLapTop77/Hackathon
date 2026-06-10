"""
kaggle/src/visualizer.py — Visualization charts for all 6 models.
"""
import os
import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

_KAGGLE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_KAGGLE_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from kaggle.src.config import OUTPUT_DIR
from kaggle.src.trainer import predict_with_model

sns.set_theme(style="whitegrid", palette="muted")


def plot_mape_r2_comparison(results_df: pd.DataFrame, save: bool = True):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax = axes[0]
    colors = plt.cm.RdYlGn_r(np.linspace(0.1, 0.9, len(results_df)))
    bars = ax.barh(results_df["model"], results_df["mape"], color=colors)
    ax.set_xlabel("MAPE (%)")
    ax.set_title("Test MAPE -- Lower is Better")
    ax.invert_yaxis()
    for bar, val in zip(bars, results_df["mape"]):
        ax.text(val + 0.02, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}%", va="center", fontsize=10)
    ax.set_xlim(0, results_df["mape"].max() * 1.25)

    ax2 = axes[1]
    colors2 = plt.cm.RdYlGn(np.linspace(0.1, 0.9, len(results_df)))
    bars2 = ax2.barh(results_df["model"], results_df["r2"], color=colors2)
    ax2.set_xlabel("R2 Score")
    ax2.set_title("Test R2 -- Higher is Better (max 1.0)")
    ax2.invert_yaxis()
    for bar, val in zip(bars2, results_df["r2"]):
        ax2.text(val + 0.01, bar.get_y() + bar.get_height() / 2,
                  f"{val:.4f}", va="center", fontsize=10)
    ax2.set_xlim(0, 1.05)

    plt.suptitle("Model Performance Comparison -- Test Set", fontsize=14, fontweight="bold")
    plt.tight_layout()
    if save:
        path = os.path.join(OUTPUT_DIR, "model_mape_comparison.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        print(f"[visualizer] Saved: {path}")
    plt.show()


def plot_actual_vs_predicted(models_dict: dict, X_test, y_test,
                              results_df: pd.DataFrame, save: bool = True):
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    axes = axes.flatten()

    y_test_arr = np.array(y_test)
    sample_size = min(2000, len(y_test))
    sample_idx = np.random.choice(len(y_test), sample_size, replace=False)

    for idx, (name, model) in enumerate(models_dict.items()):
        ax = axes[idx]
        pred = predict_with_model(model, X_test)
        y_t = y_test_arr[sample_idx] / 1e6
        y_p = pred[sample_idx] / 1e6

        ax.scatter(y_t, y_p, alpha=0.2, s=10, color="#4C72B0")
        lims = [min(y_t.min(), y_p.min()), max(y_t.max(), y_p.max())]
        ax.plot(lims, lims, "r--", lw=1.5)
        ax.set_xlabel("Actual (trieu VND)")
        ax.set_ylabel("Predicted (trieu VND)")
        ax.set_title(name)

        row = results_df[results_df["model"] == name].iloc[0]
        ax.text(0.05, 0.95, f"MAPE: {row['mape']:.2f}%\nR2: {row['r2']:.4f}",
                transform=ax.transAxes, va="top",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    plt.suptitle("Actual vs Predicted -- All Models", fontsize=14, fontweight="bold")
    plt.tight_layout()
    if save:
        path = os.path.join(OUTPUT_DIR, "all_models_actual_vs_predicted.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        print(f"[visualizer] Saved: {path}")
    plt.show()


def plot_feature_importance(models_dict: dict, feature_names: list, save: bool = True):
    tree_models = ["XGBoost", "LightGBM", "RandomForest"]
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    for ax, name in zip(axes, tree_models):
        model = models_dict.get(name)
        if model is None or not hasattr(model, "feature_importances_"):
            ax.axis("off")
            continue
        fi = pd.Series(model.feature_importances_, index=feature_names) \
               .sort_values(ascending=True).tail(15)
        fi.plot(kind="barh", ax=ax, color="#4C72B0", alpha=0.85)
        ax.set_title(f"{name} -- Top 15 Features")
        ax.set_xlabel("Importance")

    plt.suptitle("Feature Importance Comparison", fontsize=14, fontweight="bold")
    plt.tight_layout()
    if save:
        path = os.path.join(OUTPUT_DIR, "feature_importance_comparison.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        print(f"[visualizer] Saved: {path}")
    plt.show()


def plot_training_time(results_df: pd.DataFrame, save: bool = True):
    fig, ax = plt.subplots(figsize=(10, 4))
    time_df = results_df.sort_values("time_sec")
    colors = plt.cm.Blues(np.linspace(0.4, 0.9, len(time_df)))
    bars = ax.barh(time_df["model"], time_df["time_sec"], color=colors)
    ax.set_xlabel("Training Time (seconds)")
    ax.set_title("Training Time Comparison")

    for bar, val in zip(bars, time_df["time_sec"]):
        ax.text(val + 1, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}s", va="center", fontsize=10)

    plt.tight_layout()
    if save:
        path = os.path.join(OUTPUT_DIR, "training_time_comparison.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        print(f"[visualizer] Saved: {path}")
    plt.show()


def run(models_dict: dict, X_test, y_test,
        results_df: pd.DataFrame, feature_names: list):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("\n[visualizer] Generating charts...")
    plot_mape_r2_comparison(results_df)
    plot_actual_vs_predicted(models_dict, X_test, y_test, results_df)
    plot_feature_importance(models_dict, feature_names)
    plot_training_time(results_df)
    print("[visualizer] All charts saved.")
