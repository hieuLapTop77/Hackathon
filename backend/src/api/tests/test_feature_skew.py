"""
backend/src/api/tests/test_feature_skew.py
==========================================
Integration test to check for training-serving feature engineering skew.
Processes mock flight inputs through:
  1. kaggle/src/preprocessor.py (Training pipeline)
  2. backend/src/api/services/prediction_service.py (Serving pipeline)
And asserts that the generated feature columns, values, and types match exactly.
"""
import os
import sys
import joblib
import pandas as pd
import numpy as np

# Set project root to sys.path
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, _PROJECT_ROOT)

from kaggle.src.preprocessor import rename_columns, clip_load_factors, create_time_features, create_data_features, create_derived_features
from backend.src.api.services.prediction_service import _build_features_df


# ── Mock App State mimicking FastAPI startup ──────────────────────────────────
class MockAppState:
    def __init__(self):
        outputs_dir = os.path.join(_PROJECT_ROOT, "outputs")
        
        enc_path = os.path.join(outputs_dir, "label_encoders.pkl")
        if os.path.exists(enc_path):
            self.label_encoders = joblib.load(enc_path)
            print(f"[test_skew] Loaded label encoders from {enc_path}")
        else:
            self.label_encoders = {}
            print("[test_skew] Warning: label_encoders.pkl not found, using empty encoders")

        fn_path = os.path.join(outputs_dir, "feature_names.txt")
        if os.path.exists(fn_path):
            with open(fn_path) as f:
                self.feature_names = [l.strip() for l in f if l.strip()]
            print(f"[test_skew] Loaded {len(self.feature_names)} features from {fn_path}")
        else:
            self.feature_names = []
            print("[test_skew] Warning: feature_names.txt not found, using empty feature list")


# ── Running Training Preprocessing Pipeline ───────────────────────────────────
def preprocess_train_style(df: pd.DataFrame, app_state: MockAppState) -> pd.DataFrame:
    """Preprocess df using the training pipeline logic (excluding row filters)."""
    df = df.copy()
    df = rename_columns(df)
    df = clip_load_factors(df)
    df = create_time_features(df)
    df = create_data_features(df)
    df = create_derived_features(df)
    
    # Run Label Encoders (from outputs/label_encoders.pkl) to mimic trainer.py encoding
    label_encoders = app_state.label_encoders
    for col, enc_col in [
        ("fare_family",     "fare_family_enc"),
        ("fare_category",   "fare_category_enc"),
        ("route",           "route_enc"),
        ("agency_currency", "agency_currency_enc"),
    ]:
        if col in df.columns and label_encoders.get(col):
            le = label_encoders[col]
            mapping = {str(cls).strip(): int(idx) for idx, cls in enumerate(le.classes_)}
            
            # Helper logic to clean fare_category just like prediction_service does
            if col == "fare_category":
                from backend.src.api.services.prediction_service import clean_fare_category
                df[enc_col] = df[col].astype(str).apply(lambda x: mapping.get(clean_fare_category(x).strip(), -1))
            else:
                df[enc_col] = df[col].astype(str).map(mapping).fillna(-1).astype(int)
        else:
            df[enc_col] = -1

    # Keep only the target features in correct order
    feature_names = app_state.feature_names
    if feature_names:
        for col in feature_names:
            if col not in df.columns:
                df[col] = 0
        return df[feature_names]
    
    return df


# ── Main Test Script ──────────────────────────────────────────────────────────
def test_feature_engineering_alignment():
    print("\n" + "=" * 60)
    print("TEST: FEATURE ENGINEERING ALIGNMENT (TRAINING VS INFERENCE)")
    print("=" * 60)

    # 1. Initialize Mock App State
    app_state = MockAppState()

    # 2. Define diverse, edge-case test flight inputs (original raw columns)
    mock_data = [
        # Normal domestic flight
        {
            "dtm_Creation_Date": "2026-06-01T08:00:00",
            "dtm_Local_ETD_Date": "2026-06-15T12:00:00",
            "lead_time_days": 14,
            "LF_by_date": 0.65,
            "LF_by_fare": 0.45,
            "booking_velocity_3d": 0.03,
            "booking_velocity_7d": 0.08,
            "Weekday": 2,
            "IsHoliday": 0,
            "is_oneway": 1,
            "lng_fuel": 95.5,
            "lng_Capacity": 230,
            "count_sked": 4,
            "str_Fare_Family_Ident": "Eco",
            "str_Fare_Category_Ident": "B12",
            "str_Dep": "SGN",
            "str_Arr": "HAN",
            "str_Currency_Ident": "VND",
            "str_Gender": 1,
            "lng_Seats": 12,
        },
        # High load factor, peak season holiday, SkyBoss class
        {
            "dtm_Creation_Date": "2026-06-01T10:00:00",
            "dtm_Local_ETD_Date": "2026-06-02T10:00:00",
            "lead_time_days": 1,
            "LF_by_date": 0.98,
            "LF_by_fare": 0.95,
            "booking_velocity_3d": 0.15,
            "booking_velocity_7d": 0.25,
            "Weekday": 5, # Saturday
            "IsHoliday": 1,
            "is_oneway": 1,
            "lng_fuel": 95.5,
            "lng_Capacity": 180,
            "count_sked": 2,
            "str_Fare_Family_Ident": "SkyBoss",
            "str_Fare_Category_Ident": "S1",
            "str_Dep": "HAN",
            "str_Arr": "DAD",
            "str_Currency_Ident": "VND",
            "str_Gender": 0,
            "lng_Seats": 2,
        },
        # Zero load factor edge case
        {
            "dtm_Creation_Date": "2026-06-01T08:00:00",
            "dtm_Local_ETD_Date": "2026-07-01T08:00:00",
            "lead_time_days": 30,
            "LF_by_date": 0.0,
            "LF_by_fare": 0.0,
            "booking_velocity_3d": 0.0,
            "booking_velocity_7d": 0.0,
            "Weekday": 1,
            "IsHoliday": 0,
            "is_oneway": 0,
            "lng_fuel": 92.0,
            "lng_Capacity": 230,
            "count_sked": 3,
            "str_Fare_Family_Ident": "Deluxe",
            "str_Fare_Category_Ident": "D1",
            "str_Dep": "SGN",
            "str_Arr": "PQC",
            "str_Currency_Ident": "VND",
            "str_Gender": 1,
            "lng_Seats": 0,
        }
    ]

    df_raw = pd.DataFrame(mock_data)

    # 3. Process with Training Preprocessor
    X_train_processed = preprocess_train_style(df_raw, app_state)

    # 4. Process with Backend prediction_service (rename columns first like _predict_and_format_results does)
    rename_map = {
        "capacity": "capacity",
        "lng_Capacity": "capacity",
        "fare_family": "fare_family",
        "str_Fare_Family_Ident": "fare_family",
        "fare_category": "fare_category",
        "str_Fare_Category_Ident": "fare_category",
        "str_Fare_Class_Short": "fare_category",
        "dep": "dep",
        "str_Dep": "dep",
        "arr": "arr",
        "str_Arr": "arr",
        "fuel_price": "lng_fuel",
        "lng_fuel": "lng_fuel",
        "lf": "LF_by_date",
        "LF_by_date": "LF_by_date",
        "lf_fare": "LF_by_fare",
        "LF_by_fare": "LF_by_fare",
        "dtm_Creation_Date": "booking_date",
        "booking_date": "booking_date",
        "dtm_Local_ETD_Date": "departure_date",
        "departure_date": "departure_date",
        "str_Currency_Ident": "agency_currency",
        "agency_currency": "agency_currency",
        "str_Gender": "str_Gender",
        "lng_Seats": "seats_sold",
        "seats_sold": "seats_sold",
    }
    df_rename = {col: rename_map[col] for col in df_raw.columns if col in rename_map}
    df_norm = df_raw.rename(columns=df_rename)
    df_norm = df_norm.loc[:, ~df_norm.columns.duplicated()]

    X_serving_processed = _build_features_df(df_norm, app_state)

    # 5. Assertions
    # A. Check shape
    assert X_train_processed.shape == X_serving_processed.shape, \
        f"Shape mismatch: Training shape {X_train_processed.shape} != Serving shape {X_serving_processed.shape}"

    # B. Check column alignment
    train_cols = list(X_train_processed.columns)
    serving_cols = list(X_serving_processed.columns)
    assert train_cols == serving_cols, \
        f"Column alignment mismatch:\nTrain columns: {train_cols}\nServing columns: {serving_cols}"

    # C. Value comparison row-by-row, cell-by-cell
    mismatches = []
    for row_idx in range(len(df_raw)):
        for col in train_cols:
            val_train = X_train_processed.iloc[row_idx][col]
            val_serving = X_serving_processed.iloc[row_idx][col]

            # Use approximate float equality
            if isinstance(val_train, (float, np.floating)):
                is_equal = np.isclose(val_train, val_serving, atol=1e-5)
            else:
                is_equal = (val_train == val_serving)

            if not is_equal:
                mismatches.append(
                    f"Row {row_idx}, Col '{col}': Train={val_train} ({type(val_train)}) != Serving={val_serving} ({type(val_serving)})"
                )

    if mismatches:
        print("\n[ERROR] FEATURE SKEW DETECTED:")
        for m in mismatches[:10]:
            print(f"  - {m}")
        if len(mismatches) > 10:
            print(f"  - ... and {len(mismatches) - 10} more mismatches")
        sys.exit(1)
    else:
        print("\n[SUCCESS] Training and serving feature engineering pipelines are perfectly aligned!")
        print(f"Verified features: {len(train_cols)}")
        for idx, col in enumerate(train_cols):
            print(f"  {idx+1:02d}. {col}")
        sys.exit(0)


if __name__ == "__main__":
    test_feature_engineering_alignment()
