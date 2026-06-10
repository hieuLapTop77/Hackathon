"""
config.py — Cấu hình tập trung cho backend
"""
import os

# ── Project Root (auto-detect) ────────────────────────────────────────────────
# backend/ is one level below project root
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT  = os.path.dirname(_BACKEND_DIR)   # goes up from backend/ to project root

# ── Paths ──────────────────────────────────────────────────────────────────────
DATA_RAW       = os.path.join(PROJECT_ROOT, "data", "raw", "ai.xlsx")
DATA_PROCESSED = os.path.join(PROJECT_ROOT, "data", "processed")
OUTPUTS_DIR    = os.path.join(PROJECT_ROOT, "outputs")

# ── Data Cleaning ──────────────────────────────────────────────────────────────
LEAD_TIME_MIN   = 0
LEAD_TIME_MAX   = 365
MIN_PRICE       = 50_000

FEATURE_COLS = [
    "lead_time_days",
    "booking_velocity_3d",
    "booking_velocity_7d",
    "LF_by_date",
    "LF_by_fare",
    "capacity",
    "Weekday",
    "IsHoliday",
    "is_oneway",
    "fuel_price",
    "count_sked",
    "fare_family_enc",
    "fare_category_enc",
    "route_enc",
]

TARGET_COL = "ticket_price"

# ── Optimizer ──────────────────────────────────────────────────────────────────
MIN_LOAD_FACTOR_TARGET = 0.70
PRICE_LOWER_BOUND_PCT  = 0.70
PRICE_UPPER_BOUND_PCT  = 1.50
