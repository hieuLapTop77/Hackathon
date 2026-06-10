"""
backend/src/api/routers/optimization.py — Revenue optimization endpoints
"""
from fastapi import APIRouter

from ..schemas import OptimizeRequest, SimulateRequest
from backend.src.models.optimizer import optimize_flight, simulate_range

router = APIRouter()


@router.post("/optimize")
def optimize(req: OptimizeRequest):
    result = optimize_flight(
        base_price = req.base_price,
        base_lf   = req.base_lf,
        capacity  = req.capacity,
    )
    return result


@router.post("/simulate")
def simulate(req: SimulateRequest):
    df = simulate_range(
        base_price = req.base_price,
        base_lf    = req.base_lf,
        capacity   = req.capacity,
        from_pct   = req.from_pct,
        to_pct     = req.to_pct,
    )
    return df.to_dict(orient="records")


@router.get("/competitor-prices")
def get_competitor_prices(route: str, base_price: float, flight_date: str = None, fare_class: str = "Eco"):
    from backend.src.api.competitor_service import CompetitorService
    comp_svc = CompetitorService()
    prices = comp_svc.get_prices(
        route=route,
        base_price=base_price,
        flight_date=flight_date,
        fare_class=fare_class,
    )
    return comp_svc.to_dict_list(prices)
