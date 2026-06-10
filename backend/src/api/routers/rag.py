"""
backend/src/api/routers/rag.py — RAG market intelligence management endpoints
"""
import logging
from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_token
from ..rag_service import QdrantRAGService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/rag/refresh")
def refresh_rag_intelligence(user: dict = Depends(verify_token)):
    """
    Trigger dynamic refresh of market intelligence (fuel price, weather, seasonal events) in Qdrant.
    Secured by JWT Authentication.
    """
    try:
        rag_service = QdrantRAGService()
        if not rag_service.enabled:
            raise HTTPException(status_code=503, detail="Qdrant RAG Service is currently unavailable or disabled")
        
        result = rag_service.refresh_market_intelligence()
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message"))
            
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RAG refresh endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
