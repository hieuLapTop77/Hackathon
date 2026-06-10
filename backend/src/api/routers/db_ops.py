"""
backend/src/api/routers/db_ops.py — Database operations endpoints (seed, routes)
"""
from fastapi import APIRouter, HTTPException

from backend.src.db import sqlserver

router = APIRouter()


@router.get("/db/routes")
def get_db_routes():
    """Return distinct routes stored in SQL Server."""
    try:
        return sqlserver.get_distinct_routes()
    except Exception as ex:
        raise HTTPException(500, f"DB error: {ex}")


@router.post("/db/seed")
def seed_db_from_excel():
    """Seed: upsert all rows from data files into SQL Server. Idempotent."""
    # Import _load_data from main module to avoid circular dependency
    from ..main import _load_data
    try:
        df = _load_data()
        result = sqlserver.upsert_flights(df)
        return {
            "status": "ok",
            "rows_inserted": result["inserted"],
            "rows_updated": result["updated"],
        }
    except Exception as ex:
        raise HTTPException(500, f"Seed failed: {ex}")


@router.post("/db/clean-agent")
def run_data_cleaner_agent():
    """
    Run the autonomous Data Cleaning Agent to process raw Vietjet SQL Server tables
    and materialize the cleaned data into the flights table.
    """
    from backend.src.api.services.data_cleaner_agent import DataCleaningAgent
    try:
        agent = DataCleaningAgent()
        result = agent.run_cleaning_and_materialization()
        if result.get("status") == "error":
            raise HTTPException(500, result.get("message"))
        return {
            "status": "ok",
            "agent_logs": agent.logs,
            "statistics": result
        }
    except Exception as ex:
        raise HTTPException(500, f"Data cleaning agent failed: {ex}")

