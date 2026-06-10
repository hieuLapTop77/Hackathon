"""
backend/src/api/routers/dashboard.py — Dashboard summary, routes, airports endpoints
"""
import pandas as pd
from fastapi import APIRouter

from backend.src.models.optimizer import optimize_flight
from backend.src.db import sqlserver

router = APIRouter()


@router.get("/routes")
def get_routes(flight_date: str | None = None, dep: str | None = None, arr: str | None = None):
    raw_routes = sqlserver.get_routes(flight_date=flight_date, dep=dep, arr=arr)
    if not raw_routes:
        return []
    result = []
    for r in raw_routes:
        avg_price_val = r.get("avg_price")
        avg_price = float(avg_price_val) if pd.notna(avg_price_val) else 0.0
        
        avg_lf_val = r.get("avg_lf")
        avg_lf = float(avg_lf_val) if pd.notna(avg_lf_val) else 0.0
        
        min_price_val = r.get("min_price")
        min_price = float(min_price_val) if pd.notna(min_price_val) else 0.0
        
        max_price_val = r.get("max_price")
        max_price = float(max_price_val) if pd.notna(max_price_val) else 0.0

        opt = optimize_flight(avg_price, avg_lf, 230)
        result.append({
            "route":             r.get("route"),
            "count":             int(r.get("count", 0)),
            "avg_price":         round(avg_price, -3),
            "avg_lf":            round(avg_lf, 4),
            "min_price":         round(min_price, -3),
            "max_price":         round(max_price, -3),
            "optimal_price":     opt["optimal_price"],
            "optimal_lf":        round(opt["optimal_lf"], 4),
            "price_change_pct":  opt["price_change_pct"],
            "revenue_delta_pct": opt["revenue_delta_pct"],
        })
    return result


@router.get("/airports")
def get_airports():
    """Return distinct departure and arrival airports."""
    try:
        airports = sqlserver.get_distinct_airports()
        return airports
    except Exception as e:
        return {"error": str(e)}


@router.get("/summary")
def get_summary(
    dep:        str | None = None,
    arr:        str | None = None,
    flight_date: str | None = None,
    flight_no:  str | None = None,
    fare_family: str | None = None,
):
    # Do not restrict date if explicitly empty or omitted
    query_date = flight_date if flight_date else None

    try:
        df = sqlserver.load_flights(
            dep=dep, arr=arr,
            flight_date=query_date,
            flight_no=flight_no,
            fare_family=fare_family,
            page_size=500,
        )
    except Exception as ex:
        print(f"[get_summary] DB query failed ({ex})")
        df = pd.DataFrame()

    if df.empty:
        return {
            "base_revenue_vnd":     0.0,
            "ai_revenue_vnd":       0.0,
            "revenue_delta_pct":    0.0,
            "avg_load_factor":      0.0,
            "flights_total":        0,
            "flights_need_action":  0,
        }

    flights = []
    for _, r in df.iterrows():
        price_val = r.get("price")
        price = float(price_val) if pd.notna(price_val) else 0.0

        lf_val = r.get("lf")
        lf = float(lf_val) if pd.notna(lf_val) else 0.0

        opt   = optimize_flight(price, lf, 230)
        status = "high" if lf > 0.75 else "ok" if lf > 0.55 else "mid" if lf > 0.40 else "low"
        flights.append({**opt, "price": price, "lf": lf, "status": status})

    base_rev  = sum(f["price"] * 230 * f["lf"] for f in flights)
    ai_rev    = sum(f["optimal_price"] * 230 * f["optimal_lf"] for f in flights)
    avg_lf    = sum(f["lf"] for f in flights) / len(flights)
    needs_opt = sum(1 for f in flights if f["status"] in ["low", "mid"])
    return {
        "base_revenue_vnd":     round(base_rev, -6),
        "ai_revenue_vnd":       round(ai_rev, -6),
        "revenue_delta_pct":    round((ai_rev - base_rev) / base_rev * 100, 2) if base_rev else 0,
        "avg_load_factor":      round(avg_lf, 4),
        "flights_total":        len(flights),
        "flights_need_action":  needs_opt,
    }
