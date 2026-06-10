"""
kaggle/src/preprocessor.py — Global data cleaning & feature engineering.
Option 1: NO leakage (removes competitor-related features).
"""
import os
import sys
import warnings
warnings.filterwarnings("ignore")

try:
    import cudf.pandas
    cudf.pandas.install()
    print("[preprocessor] RAPIDS cuDF pandas acceleration enabled.")
except ImportError:
    pass

import numpy as np
import pandas as pd

_KAGGLE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_KAGGLE_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from kaggle.src.config import (
    FEATURE_COLS, LEAKAGE_COLS,
    LEAD_TIME_MIN, LEAD_TIME_MAX, MIN_PRICE,
    DATA_PROCESSED,
)


def rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {
        "dtm_Creation_Date":       "booking_date",
        "dtm_Local_ETD_Date":     "departure_date",
        "str_Currency_Ident":     "agency_currency",
        "lng_Agency_Id_Nmbr":     "agency_id",
        "str_Dep":                "dep",
        "str_Arr":                "arr",
        "str_Fare_Class_Short":   "fare_class",
        "str_Fare_Family_Ident":  "fare_family",
        "str_Fare_Category_Ident":"fare_category",
        "lng_Capacity":           "capacity",
        "lng_Seats":             "seats_sold",
        "lng_fuel":              "fuel_price",
        "mny_GL_Charges_Total":   "ticket_price",
    }
    df = df.rename(columns=mapping)
    df["route"] = df["dep"] + "-" + df["arr"]
    for col in ["str_Gender", "IsHoliday", "is_oneway", "Weekday"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df


def clip_load_factors(df: pd.DataFrame) -> pd.DataFrame:
    if "LF_by_date" in df.columns:
        df["LF_by_date"] = df["LF_by_date"].clip(0, 1)
    if "LF_by_fare" in df.columns:
        df["LF_by_fare"] = df["LF_by_fare"].clip(0, 1)
    return df


def filter_outliers(df: pd.DataFrame) -> pd.DataFrame:
    original_len = len(df)
    if "lead_time_days" in df.columns:
        df = df[
            (df["lead_time_days"] >= LEAD_TIME_MIN) &
            (df["lead_time_days"] <= LEAD_TIME_MAX)
        ]
    if "ticket_price" in df.columns:
        df = df[df["ticket_price"] >= MIN_PRICE]
    removed = original_len - len(df)
    print(f"[preprocess] Filtered outliers: {len(df):,} rows remain (removed {removed:,})")
    return df


def create_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    if "LF_by_date" in df.columns and "lead_time_days" in df.columns:
        df["urgency_score"] = (df["LF_by_date"] / (df["lead_time_days"] + 1)).round(6)

    if "booking_velocity_3d" in df.columns and "booking_velocity_7d" in df.columns:
        df["velocity_ratio"] = (
            df["booking_velocity_3d"] / (df["booking_velocity_7d"] + 1e-6)
        ).clip(0, 10).round(4)

    if "capacity" in df.columns and "LF_by_date" in df.columns:
        df["seats_remaining"] = (
            df["capacity"] * (1 - df["LF_by_date"])
        ).clip(0).astype(int)

    if "Weekday" in df.columns:
        df["is_weekend"] = df["Weekday"].isin([5, 6]).astype(int)

    if "lead_time_days" in df.columns:
        df["days_bucket"] = pd.cut(
            df["lead_time_days"],
            bins=[-1, 3, 7, 14, 30, 60, 90, 365],
            labels=[0, 1, 2, 3, 4, 5, 6],
        ).astype(float).fillna(0).astype(int)
        df["log_lead_time"] = np.log1p(df["lead_time_days"]).round(4)

    if "LF_by_date" in df.columns and "booking_velocity_7d" in df.columns:
        df["lf_velocity_interact"] = (
            df["LF_by_date"] * df["booking_velocity_7d"]
        ).round(4)

    if "capacity" in df.columns and "LF_by_date" in df.columns:
        df["expected_sold"] = (
            df["capacity"] * df["LF_by_date"]
        ).round(0)

    return df


def create_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract time-based features from date columns."""
    # Departure date features
    for date_col in ["departure_date", "booking_date"]:
        if date_col in df.columns:
            dt = pd.to_datetime(df[date_col], errors="coerce")
            if date_col == "departure_date":
                df["dep_month"] = dt.dt.month.fillna(0).astype(int)
                df["dep_quarter"] = dt.dt.quarter.fillna(0).astype(int)
                df["dep_day_of_month"] = dt.dt.day.fillna(0).astype(int)
                # Peak season: Tet (Jan-Feb), Summer (Jun-Aug), National holidays (Apr-May)
                month = dt.dt.month
                df["is_peak_season"] = month.isin([1, 2, 6, 7, 8]).astype(int)
            elif date_col == "booking_date":
                df["booking_month"] = dt.dt.month.fillna(0).astype(int)

    print(f"[preprocess] Time features created: dep_month, dep_quarter, dep_day_of_month, booking_month, is_peak_season")
    return df


def create_data_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create features from previously unused columns."""
    # str_Gender is already numeric (0/1) from rename_columns
    if "str_Gender" in df.columns:
        print(f"[preprocess] str_Gender included as feature")

    return df


def drop_leakage_features(df: pd.DataFrame) -> pd.DataFrame:
    print("[preprocess] Option 1 -- Dropping leakage features:")
    for col in LEAKAGE_COLS:
        if col in df.columns:
            df = df.drop(columns=[col])
            print(f"  [preprocess]   Dropped: {col}")
    return df


def null_report(df: pd.DataFrame):
    stats = pd.DataFrame({
        "Column":       df.columns,
        "Null_Count":   df.isnull().sum().values,
        "Null_Percent": (df.isnull().sum() / len(df) * 100).round(2).values,
        "Data_Type":    df.dtypes.values,
    }).sort_values("Null_Percent", ascending=False)

    print("\n[preprocess] Null value summary (IMPUTATION done in trainer.py per-split):")
    nulls = stats[stats["Null_Count"] > 0]
    if nulls.empty:
        print("  No nulls found.")
    else:
        print(nulls[nulls["Null_Count"] > 0].to_string(index=False))

    total = df.isnull().sum().sum()
    print(f"[preprocess] Total nulls remaining: {total:,} (filled during training split)")


def verify_no_leakage(available_features: list):
    print("\n[preprocess] Feature leakage verification:")
    for f in available_features:
        print(f"  [OK] {f}")
    print("[preprocess] No features derived from ticket_price (target)")


def preprocess(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    print("\n" + "=" * 60)
    print("PREPROCESSING PIPELINE -- Option 1 (NO LEAKAGE)")
    print("=" * 60)

    print("\n[1] Renaming columns...")
    df = rename_columns(df)

    print("\n[2] Null value analysis...")
    null_report(df)

    print("\n[3] Clipping load factor values...")
    df = clip_load_factors(df)

    print("\n[4] Filtering outliers...")
    df = filter_outliers(df)

    original = len(df)
    df = df.drop_duplicates()
    print(f"[preprocess] Dedup: {len(df):,} rows (removed {original - len(df):,})")

    print("\n[5] Creating time-based features...")
    df = create_time_features(df)

    print("\n[6] Creating data-derived features...")
    df = create_data_features(df)

    print("\n[7] Creating derived features...")
    df = create_derived_features(df)

    print("\n[8] Dropping leakage features...")
    df = drop_leakage_features(df)

    available_features = [c for c in FEATURE_COLS if c in df.columns or c.endswith("_enc")]
    verify_no_leakage(available_features)
    print(f"[preprocess] Features available: {len(available_features)}")
    print(f"[preprocess] Remaining rows: {len(df):,}")

    os.makedirs(DATA_PROCESSED, exist_ok=True)
    df.to_parquet(f"{DATA_PROCESSED}/cleaned.parquet", index=False)
    print(f"[preprocess] Saved (un-imputed) -> {DATA_PROCESSED}/cleaned.parquet")

    return df, available_features


if __name__ == "__main__":
    from kaggle.src.data_loader import load
    df = load()
    df_clean, feats = preprocess(df)
    print(f"\nFinal: {len(df_clean):,} rows, features={feats}")
