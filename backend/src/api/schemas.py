"""
backend/src/api/schemas.py — Pydantic request/response models
"""
from pydantic import BaseModel, Field
from typing import Optional, List


class PredictRequest(BaseModel):
    lead_time_days:      int   = Field(..., example=30)
    LF_by_date:          float = Field(..., ge=0, le=1, example=0.65)
    LF_by_fare:          float = Field(..., ge=0, le=1, example=0.40)
    booking_velocity_3d: float = Field(..., example=0.02)
    booking_velocity_7d: float = Field(..., example=0.05)
    Weekday:             int   = Field(..., example=4)
    IsHoliday:           int   = Field(0, example=0)
    is_oneway:           int   = Field(1, example=1)
    lng_fuel:            float = Field(..., example=93.86)
    capacity:            int   = Field(..., gt=0, example=230)
    count_sked:          int   = Field(3, example=3)
    fare_family:         str   = Field(..., example="Eco")
    fare_category:       str   = Field(..., example="B  ")
    dep:                 str   = Field(..., example="SGN")
    arr:                 str   = Field(..., example="HAN")
    model_name:          Optional[str]   = Field(None, example="XGBoost")
    competitor_price:    Optional[float] = Field(None, example=1200000.0)


class OptimizeRequest(BaseModel):
    base_price:       float          = Field(..., gt=0, example=950000)
    base_lf:          float          = Field(..., ge=0, le=1, example=0.55)
    capacity:         int           = Field(..., gt=0, example=230)


class SimulateRequest(BaseModel):
    base_price: float = Field(..., gt=0, example=950000)
    base_lf:    float = Field(..., ge=0, le=1, example=0.55)
    capacity:   int   = Field(..., gt=0, example=230)
    from_pct:   float = Field(-30, example=-30)
    to_pct:     float = Field(50,  example=50)


class EnsembleRequest(BaseModel):
    lead_time_days:      int   = Field(..., example=30)
    LF_by_date:          float = Field(..., ge=0, le=1, example=0.65)
    LF_by_fare:          float = Field(..., ge=0, le=1, example=0.40)
    booking_velocity_3d: float = Field(..., example=0.02)
    booking_velocity_7d: float = Field(..., example=0.05)
    Weekday:             int   = Field(..., example=4)
    IsHoliday:           int   = Field(0, example=0)
    is_oneway:           int   = Field(1, example=1)
    lng_fuel:            float = Field(..., example=93.86)
    capacity:            int   = Field(..., gt=0, example=230)
    count_sked:          int   = Field(3, example=3)
    fare_family:         str   = Field(..., example="Eco")
    fare_category:       str   = Field(..., example="B  ")
    dep:                 str   = Field(..., example="SGN")
    arr:                 str   = Field(..., example="HAN")
    strategy:            str   = Field("weighted_perf", example="weighted_perf")
    competitor_price:    Optional[float] = Field(None, example=1200000.0)
    # strategy options: "average" | "weighted_perf" | "top3"


class ApplyRequest(BaseModel):
    applied_price: float = Field(..., gt=0, example=1050000)
    model_used: Optional[str] = Field(None, example="XGBoost")


class AgentChatRequest(BaseModel):
    query: str
    session_id: Optional[int] = None


class FlightPredictItem(BaseModel):
    id: int
    lead_time_days: int = 30
    LF_by_date: float = Field(0.65, ge=0, le=1)
    LF_by_fare: float = Field(0.40, ge=0, le=1)
    booking_velocity_3d: float = 0.02
    booking_velocity_7d: float = 0.05
    Weekday: int = 4
    IsHoliday: int = 0
    is_oneway: int = 1
    lng_fuel: float = 93.86
    capacity: int = Field(230, gt=0)
    count_sked: int = 3
    fare_family: str = "Eco"
    fare_category: str = "B"
    dep: str = "SGN"
    arr: str = "HAN"
    current_price: Optional[float] = None   # used for sanity-bounding the prediction
    competitor_price: Optional[float] = None


class BatchPredictRequest(BaseModel):
    model_name: Optional[str] = None   # None => best model
    flights: List[FlightPredictItem]


class FareUpdateItem(BaseModel):
    id: int
    price: float = Field(..., gt=0)
    lf: float = Field(..., ge=0, le=1)


class BulkFareUpdateRequest(BaseModel):
    updates: list[FareUpdateItem]
