"""
backend/src/models/optimizer.py
================================
Revenue Pricing Optimizer with Data-Driven Elasticity.

Tier 3 Upgrade: Replaces hardcoded elasticity (-1.2) with route/season-specific
values computed from historical booking data via log-log regression.

Elasticity estimation:
  ln(demand) = α + ε × ln(price)
  where ε (elasticity) varies by route, fare class, and season.
"""
import os
import numpy as np
import pandas as pd
import logging
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LinearRegression

from backend.config import PRICE_LOWER_BOUND_PCT, PRICE_UPPER_BOUND_PCT

logger = logging.getLogger(__name__)

# ── Default elasticity values by route type ──────────────────────────────────
# These are used as fallbacks when insufficient data exists for regression.
# Derived from aviation industry research: domestic short-haul ≈ -1.1 to -1.5
DEFAULT_ELASTICITIES = {
    # Trunk routes (high frequency, business travelers → less elastic)
    "SGN-HAN": -1.05,
    "HAN-SGN": -1.05,
    # Tourist routes (leisure travelers → more elastic)
    "SGN-DAD": -1.30,
    "HAN-DAD": -1.25,
    "SGN-CXR": -1.40,
    "SGN-PQC": -1.45,
    "HAN-PQC": -1.50,
    # Default
    "_default": -1.20,
}

# Seasonal elasticity adjustments (peak season → less elastic)
SEASONAL_ELASTICITY_ADJUSTMENT = {
    1: 0.15,    # Tết — very inelastic (people must travel)
    2: 0.10,    # Post-Tết
    3: -0.05,   # Low season — more elastic
    4: -0.05,
    5: 0.0,
    6: 0.10,    # Summer — less elastic
    7: 0.12,
    8: 0.10,
    9: -0.10,   # Lowest season — most elastic
    10: -0.05,
    11: 0.0,
    12: 0.05,
}

# Minimum data points needed for reliable regression
MIN_DATA_POINTS = 30

# Cache for computed elasticities (invalidated periodically)
_elasticity_cache: dict[str, float] = {}
_elasticity_sources: dict[str, str] = {}


def estimate_elasticity(route: str = None, fare_class: str = None,
                        month: int = None) -> float:
    """
    Estimate price elasticity of demand for a specific route/class/season.
    
    Uses log-log regression on historical data when available,
    falls back to calibrated defaults otherwise.
    
    Args:
        route: e.g. "SGN-HAN"
        fare_class: e.g. "Eco", "Deluxe", "SkyBoss"
        month: 1-12 for seasonal adjustment
    
    Returns:
        Elasticity value (negative float, typically -0.5 to -2.0)
    """
    cache_key = f"{route}_{fare_class}_{month}"
    if cache_key in _elasticity_cache:
        return _elasticity_cache[cache_key]

    # Try data-driven estimation
    data_elasticity = _estimate_from_data(route, fare_class)
    
    if data_elasticity is not None:
        elasticity = data_elasticity
        source = "data"
        logger.info(f"Data-driven elasticity for {route}/{fare_class}: {elasticity:.3f}")
    else:
        source = "calibrated"
        # Fallback to calibrated defaults
        elasticity = DEFAULT_ELASTICITIES.get(route, DEFAULT_ELASTICITIES["_default"])
        
        # Fare class adjustment (business/premium classes are less elastic)
        fare_adjustments = {
            "Eco": 0.0,
            "Deluxe": 0.15,      # Less elastic (willing to pay more)
            "SkyBoss": 0.30,     # Much less elastic
            "Business": 0.35,    # Least elastic
        }
        if fare_class:
            elasticity += fare_adjustments.get(fare_class, 0.0)

    # Seasonal adjustment
    if month:
        seasonal_adj = SEASONAL_ELASTICITY_ADJUSTMENT.get(month, 0.0)
        elasticity += seasonal_adj

    # Clamp to reasonable range
    elasticity = max(-2.5, min(-0.3, elasticity))

    _elasticity_cache[cache_key] = elasticity
    _elasticity_sources[cache_key] = source
    return elasticity


def _estimate_from_data(route: str = None, fare_class: str = None) -> float | None:
    """
    Estimate elasticity from historical booking data using log-log regression.
    
    Model: ln(LF) = α + ε × ln(price)
    where ε is the price elasticity of demand.
    
    Returns None if insufficient data.
    """
    try:
        from backend.src.db.sqlserver import _connect
        conn = _connect()
        cursor = conn.cursor()

        # Build query with optional filters
        conditions = ["mny_GL_Charges_Total > 50000", "LF_by_date > 0.01", "LF_by_date <= 1.0"]
        params = []

        if route:
            conditions.append("route = ?")
            params.append(route)
        if fare_class:
            conditions.append("fare_family = ?")
            params.append(fare_class)

        where_clause = " AND ".join(conditions)

        cursor.execute(f"""
            SELECT mny_GL_Charges_Total AS price, LF_by_date AS lf
            FROM flights
            WHERE {where_clause}
        """, tuple(params))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if len(rows) < MIN_DATA_POINTS:
            logger.debug(f"Insufficient data for elasticity ({len(rows)} rows < {MIN_DATA_POINTS})")
            return None

        prices = np.array([float(r[0]) for r in rows])
        lfs = np.array([float(r[1]) for r in rows])

        # Filter out zeros/negatives for log
        mask = (prices > 0) & (lfs > 0)
        prices = prices[mask]
        lfs = lfs[mask]

        if len(prices) < MIN_DATA_POINTS:
            return None

        # Log-log regression: ln(LF) = α + ε × ln(price)
        log_prices = np.log(prices).reshape(-1, 1)
        log_lfs = np.log(lfs)

        model = LinearRegression()
        model.fit(log_prices, log_lfs)

        elasticity = float(model.coef_[0])
        r_squared = model.score(log_prices, log_lfs)

        logger.info(f"Estimated elasticity for {route}/{fare_class}: ε={elasticity:.3f}, R²={r_squared:.3f}, N={len(prices)}")

        # Sanity check: elasticity should be negative (law of demand)
        # If positive, data quality is poor → fall back
        if elasticity >= 0:
            logger.warning(f"Positive elasticity ({elasticity:.3f}) detected — likely data quality issue. Ignoring.")
            return None

        # If R² is too low, regression is unreliable
        if r_squared < 0.01:
            logger.warning(f"Very low R² ({r_squared:.3f}) — regression unreliable. Ignoring.")
            return None

        return elasticity

    except Exception as e:
        logger.warning(f"Elasticity estimation from data failed: {e}")
        return None


def clear_elasticity_cache():
    """Clear the elasticity cache. Called after data changes."""
    global _elasticity_cache
    _elasticity_cache.clear()
    logger.info("Elasticity cache cleared")


def optimize_flight(base_price: float, base_lf: float, capacity: int,
                    elasticity: float = None, route: str = None,
                    fare_class: str = None, month: int = None) -> dict:
    """
    Find optimal ticket price to maximize revenue using Constant-Elasticity Demand model.
    
    Tier 3 upgrade: Uses data-driven elasticity when available.
    
    Args:
        base_price: Current ticket price (VND)
        base_lf: Current load factor (0.0-1.0)
        capacity: Aircraft seat capacity
        elasticity: Override elasticity value (if None, auto-estimated)
        route: Route code for elasticity estimation (e.g. "SGN-HAN")
        fare_class: Fare class for elasticity estimation
        month: Month for seasonal elasticity adjustment
    """
    # Safe checks for inputs
    if base_price is None or pd.isna(base_price) or float(base_price) <= 0.0:
        base_price = 50000.0
    else:
        base_price = float(base_price)

    if base_lf is None or pd.isna(base_lf) or float(base_lf) <= 0.0:
        base_lf = 0.01
    else:
        base_lf = float(base_lf)

    if capacity is None or pd.isna(capacity) or int(capacity) <= 0:
        capacity = 230
    else:
        capacity = int(capacity)

    # Auto-estimate elasticity if not provided
    if elasticity is None:
        elasticity = estimate_elasticity(route=route, fare_class=fare_class, month=month)
        cache_key = f"{route}_{fare_class}_{month}"
        source = _elasticity_sources.get(cache_key, "calibrated")
    else:
        source = "override"

    lower_bound = base_price * PRICE_LOWER_BOUND_PCT
    upper_bound = base_price * PRICE_UPPER_BOUND_PCT

    # Minimize negative expected revenue
    def objective(price_candidate):
        lf_candidate = base_lf * ((price_candidate / base_price) ** elasticity)
        lf_clamped = min(1.0, max(0.0, lf_candidate))
        expected_revenue = price_candidate * capacity * lf_clamped
        return -expected_revenue

    res = minimize_scalar(objective, bounds=(lower_bound, upper_bound), method='bounded')

    optimal_price = float(res.x)
    optimal_lf = min(1.0, max(0.0, base_lf * ((optimal_price / base_price) ** elasticity)))

    base_revenue = base_price * capacity * base_lf
    optimal_revenue = optimal_price * capacity * optimal_lf

    revenue_delta = optimal_revenue - base_revenue
    revenue_delta_pct = (revenue_delta / base_revenue * 100.0) if base_revenue > 0 else 0.0
    price_change_pct = ((optimal_price - base_price) / base_price * 100.0)

    # Recommendation text
    price_diff = abs(optimal_price - base_price)
    if price_change_pct > 2.0:
        recommendation = f"Nhu cầu co giãn thuận lợi (ε={elasticity:.2f}). Khuyến nghị TĂNG giá bán lên {optimal_price:,.0f} VND (Tăng {price_diff:,.0f} VND, +{price_change_pct:.1f}%) để tối ưu doanh thu."
    elif price_change_pct < -2.0:
        recommendation = f"Hệ số lấp đầy thấp, nhu cầu nhạy cảm giá (ε={elasticity:.2f}). Khuyến nghị GIẢM giá xuống {optimal_price:,.0f} VND (Giảm {price_diff:,.0f} VND, {price_change_pct:.1f}%) để kích cầu."
    else:
        recommendation = f"Giá bán hiện tại đang gần tối ưu (ε={elasticity:.2f}). Giữ nguyên mức giá này."

    return {
        "base_price": round(base_price, -3),
        "base_lf": round(base_lf, 4),
        "optimal_price": round(optimal_price, -3),
        "optimal_lf": round(optimal_lf, 4),
        "price_change_pct": round(price_change_pct, 2),
        "revenue_delta_pct": round(revenue_delta_pct, 2),
        "recommendation": recommendation,
        "elasticity_used": round(elasticity, 3),
        "elasticity_source": source,
    }


def simulate_range(base_price: float, base_lf: float, capacity: int,
                   from_pct: float = -30.0, to_pct: float = 50.0,
                   elasticity: float = None, route: str = None,
                   fare_class: str = None, month: int = None) -> pd.DataFrame:
    """
    Simulates expected load factor and revenue changes across a range of pricing changes.
    Uses data-driven elasticity when available.
    """
    if base_lf <= 0.0:
        base_lf = 0.01
    base_price = float(base_price)
    base_lf = float(base_lf)
    capacity = int(capacity)

    if elasticity is None:
        elasticity = estimate_elasticity(route=route, fare_class=fare_class, month=month)

    steps = np.arange(from_pct, to_pct + 1.0, 5.0)
    records = []

    base_revenue = base_price * capacity * base_lf

    for pct in steps:
        price = base_price * (1.0 + pct / 100.0)
        lf = min(1.0, max(0.0, base_lf * ((price / base_price) ** elasticity)))
        revenue = price * capacity * lf
        rev_change_pct = ((revenue - base_revenue) / base_revenue * 100.0) if base_revenue > 0 else 0.0

        records.append({
            "price_change_pct": float(pct),
            "simulated_price": round(price, -3),
            "simulated_lf": round(lf, 4),
            "simulated_revenue": round(revenue, -3),
            "revenue_change_pct": round(rev_change_pct, 2)
        })

    return pd.DataFrame(records)
