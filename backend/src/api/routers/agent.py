"""
backend/src/api/routers/agent.py — LLM Copilot agent endpoints
Uses LangGraph-based copilot (agent_graph.py) with Langfuse tracing.
Falls back to legacy agent_workflow.py if LangGraph is not available.
"""
import os
import requests
import logging
import threading
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from ..auth import verify_token, rate_limit_copilot

from ..schemas import AgentChatRequest
from backend.src.db import sqlserver

logger = logging.getLogger(__name__)

# Try to import LangGraph agent first, fallback to legacy
_use_langgraph = True
try:
    from ..agent_graph import run_copilot_graph, VLLM_URL, LLM_MODEL
    logger.info("Using LangGraph-based copilot agent")
except ImportError as e:
    logger.warning(f"LangGraph not available ({e}). Falling back to legacy agent.")
    from ..agent_workflow import RevenueCopilotAgent, VLLM_URL, LLM_MODEL
    _use_langgraph = False

router = APIRouter()
security_basic = HTTPBasic(auto_error=False)


@router.post("/agent/token")
def get_token(
    username: str = "vj_user",
    role: str = "admin",
    credentials: HTTPBasicCredentials = Depends(security_basic)
):
    """Generate a JWT token for testing/integration purposes."""
    # Restrict roles
    allowed_roles = {"admin", "viewer", "user"}
    if role not in allowed_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Allowed roles are: {', '.join(allowed_roles)}"
        )

    # Authenticate basic credentials
    token_gen_user = os.getenv("TOKEN_GEN_USER", "vj_admin")
    token_gen_password = os.getenv("TOKEN_GEN_PASSWORD")
    if not token_gen_password:
        raise HTTPException(
            status_code=500,
            detail="Server configuration error: TOKEN_GEN_PASSWORD is not set"
        )

    if not credentials or credentials.username != token_gen_user or credentials.password != token_gen_password:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    from ..auth import create_access_token
    token = create_access_token({"sub": username, "role": role})
    return {"access_token": token, "token_type": "bearer"}


# Retraining safety guards
_retraining_lock = threading.Lock()
_is_retraining = False


def trigger_model_retraining():
    """Triggers the ML model training pipeline asynchronously and reloads models into memory."""
    global _is_retraining
    if _retraining_lock.locked() or _is_retraining:
        logger.info("[Background Task] Model retraining is already in progress. Skipping concurrent run.")
        return

    with _retraining_lock:
        _is_retraining = True
        try:
            logger.info("[Background Task] Starting model retraining pipeline...")
            from kaggle.scripts.run_pipeline import main as run_train_pipeline
            # Run retraining pipeline
            run_train_pipeline()
            logger.info("[Background Task] Model retraining completed successfully.")
            
            # Reload models into the FastAPI application state
            from backend.src.api.main import app
            from backend.src.models.trainer import load_kaggle_models, get_best_model_name
            import csv as _csv
            
            logger.info("[Background Task] Reloading trained models into application state...")
            app.state.models = load_kaggle_models()
            app.state.best_model_name = get_best_model_name()
            
            cmp_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "outputs", "model_comparison.csv")
            if os.path.exists(cmp_path):
                with open(cmp_path) as f:
                    for row in _csv.DictReader(f):
                        app.state.model_metrics[row["model"]] = {
                            "mape": float(row["mape"]),
                            "rmse": float(row["rmse"]),
                            "mae":  float(row["mae"]),
                            "r2":   float(row["r2"]),
                        }
            logger.info("[Background Task] Models successfully reloaded in memory.")
        except Exception as ex:
            logger.error(f"[Background Task] Model retraining failed: {ex}")
        finally:
            _is_retraining = False


from fastapi import BackgroundTasks

@router.post("/agent/chat")
async def agent_chat(req: AgentChatRequest, background_tasks: BackgroundTasks, user: dict = Depends(verify_token), _=Depends(rate_limit_copilot)):
    try:
        session_id = req.session_id
        if not session_id:
            # Generate a friendly title from the query
            words = req.query.split()
            title = " ".join(words[:5]) + ("..." if len(words) > 5 else "")
            session_id = sqlserver.create_chat_session(title)

        # 1. Save user query to database
        sqlserver.save_chat_message(session_id, "user", req.query)

        # 2. Run agent graph
        if _use_langgraph:
            res = await run_copilot_graph(req.query)
        else:
            agent = RevenueCopilotAgent()
            res = await agent.run_copilot_flow(req.query)

        # 3. Save assistant response to database
        sqlserver.save_chat_message(
            session_id,
            "assistant",
            res.get("message", ""),
            thinking=res.get("thinking"),
            tools_called=res.get("tools_called"),
            action=res.get("action")
        )

        res["session_id"] = session_id
        
        return res
    except Exception as e:
        logger.error(f"Agent chat failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent/retrain")
def retrain_models(background_tasks: BackgroundTasks, user: dict = Depends(verify_token)):
    """Trigger ML models retraining asynchronously."""
    global _is_retraining
    if _is_retraining:
        raise HTTPException(status_code=409, detail="Model retraining is already in progress.")
    
    background_tasks.add_task(trigger_model_retraining)
    return {"status": "ok", "message": "Model retraining triggered in the background."}


@router.get("/agent/sessions")
def get_sessions(user: dict = Depends(verify_token)):
    """Get all chat sessions sorted by last updated."""
    return sqlserver.get_chat_sessions()


@router.get("/agent/sessions/{session_id}/messages")
def get_session_messages(session_id: int, user: dict = Depends(verify_token)):
    """Get all messages for a specific chat session."""
    return sqlserver.get_chat_messages(session_id)


@router.delete("/agent/sessions/{session_id}")
def delete_session(session_id: int, user: dict = Depends(verify_token)):
    """Delete a chat session and all its messages."""
    success = sqlserver.delete_chat_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {"status": "success", "message": f"Deleted chat session ID {session_id}"}


@router.put("/agent/sessions/{session_id}")
def rename_session(session_id: int, title: str, user: dict = Depends(verify_token)):
    """Rename a chat session."""
    success = sqlserver.rename_chat_session(session_id, title)
    if not success:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {"status": "success", "message": f"Renamed chat session ID {session_id} to '{title}'"}


@router.get("/agent/status")
def agent_status():
    vllm_ok = False
    vllm_model = LLM_MODEL
    try:
        headers = {}
        api_key = os.getenv("VLLM_API_KEY") or os.getenv("NVIDIA_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        logger.info(f"Checking LLM status at {VLLM_URL}/models ...")
        resp = requests.get(f"{VLLM_URL}/models", headers=headers, timeout=10)
        if resp.status_code == 200:
            vllm_ok = True
            models_data = resp.json()
            if "data" in models_data and len(models_data["data"]) > 0:
                vllm_model = models_data["data"][0]["id"]
        else:
            logger.warning(f"LLM status check returned status code {resp.status_code}: {resp.text[:200]}")
    except Exception as ex:
        logger.error(f"LLM status check failed: {ex}")

    return {
        "status": "ok",
        "vllm_connected": vllm_ok,
        "vllm_model": vllm_model,
        "vllm_url": VLLM_URL,
        "agent_type": "langgraph" if _use_langgraph else "legacy",
    }
