"""
backend/src/api/agent_graph.py — LangGraph-based Revenue Copilot
================================================================
Replaces the linear hard-coded flow with a LangGraph state machine.

Architecture:
  - Supervisor node: LLM decides which tools to call based on the query
  - Tool nodes: DB query, SciPy optimizer, competitor check, RAG search, Price Comparison
  - Report node: LLM generates structured pricing report
  - All traced via Langfuse for observability
"""
import os
import re
import json
import logging
import asyncio
import httpx
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from dataclasses import dataclass, field

# All relative-date phrases ("hôm nay", "ngày mai") must resolve against
# Vietnam local time, not the container clock (usually UTC — 7h behind,
# which shifts "today" to yesterday every morning VN time).
VN_TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


def vn_now() -> datetime:
    """Current datetime in Vietnam local time (UTC+7)."""
    return datetime.now(tz=VN_TZ)


# ── Response language detection ──────────────────────────────────────────────
# The copilot answers in the user's language: Vietnamese question → Vietnamese
# answer, English question → English answer. Ambiguous queries default to vi
# (primary user base is Vietjet fare-control staff).

_VI_CHARS_RE = re.compile(
    r"[ăđơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]"
)
# Vietnamese typed without diacritics still counts as Vietnamese
_VI_HINTS = (
    "gia ve", "ve may bay", "chuyen bay", "chang bay", "hom nay", "ngay mai",
    "cho toi", "bao nhieu", "doi thu", "du bao", "du doan", "toi uu",
    "lap day", "so sanh", "khuyen nghi", "hang ve",
)
_EN_HINTS = (
    "the", "what", "how", "give", "show", "me", "price", "prices", "fare",
    "fares", "flight", "flights", "today", "tomorrow", "compare", "forecast",
    "predict", "please", "from", "revenue", "load", "factor",
)


def detect_lang(text: str) -> str:
    """Detect the query language ('vi' or 'en') so the answer matches it."""
    t = (text or "").lower()
    if _VI_CHARS_RE.search(t):
        return "vi"
    if any(h in t for h in _VI_HINTS):
        return "vi"
    words = set(re.findall(r"[a-z]+", t))
    return "en" if len(words & set(_EN_HINTS)) >= 2 else "vi"

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from backend.src.db.sqlserver import _connect
from backend.src.models.optimizer import optimize_flight
from backend.src.api.rag_service import QdrantRAGService
from backend.src.api.semantic_cache import get_cache
from backend.src.api.guardrails import get_guardrails
from backend.src.api.competitor_service import CompetitorService

logger = logging.getLogger(__name__)

VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8001/v1")
if VLLM_URL.endswith("/"):
    VLLM_URL = VLLM_URL[:-1]
LLM_MODEL = os.getenv("LLM_MODEL", "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4")
VLLM_API_KEY = os.getenv("VLLM_API_KEY") or os.getenv("NVIDIA_API_KEY")

# Langfuse integration (graceful fallback if not available)
_langfuse = None
try:
    from langfuse import Langfuse
    _langfuse = Langfuse(
        host=os.getenv("LANGFUSE_HOST", "http://localhost:4000"),
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-default"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-default"),
    )
    logger.info("Langfuse initialized successfully")
except Exception as e:
    logger.warning(f"Langfuse not available ({e}). Running without tracing.")


def load_agent_prompt(filename: str, **kwargs) -> str:
    """Load prompt template from Markdown file and replace placeholders."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "agents", "prompts", filename)
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()
        for k, v in kwargs.items():
            content = content.replace(f"{{{k}}}", str(v))
        return content
    except Exception as e:
        logger.error(f"Failed to load agent prompt from {prompt_path}: {e}")
        raise FileNotFoundError(f"Agent prompt file {filename} not found: {e}")


def load_agent_registry() -> str:
    """Loads all agent skill and rule files and formats them for the Supervisor Prompt."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    registry_dir = os.path.join(current_dir, "agents", "registry")
    
    if not os.path.exists(registry_dir):
        return "No agents registered."
        
    compiled_descriptions = []
    
    for filename in sorted(os.listdir(registry_dir)):
        if filename.endswith(".md"):
            # Extract agent name from filename, e.g. database_agent.md -> DatabaseAgent
            base_name = filename.replace(".md", "")
            agent_name = "".join([part.capitalize() for part in base_name.split("_")])
            filepath = os.path.join(registry_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                    
                # Extract Identity & Purpose or short description
                purpose_match = re.search(r"## Identity & Purpose\n(.*?)(?=\n##|$)", content, re.DOTALL)
                purpose = purpose_match.group(1).strip() if purpose_match else "No description available."
                purpose = re.sub(r"\s+", " ", purpose)
                
                compiled_descriptions.append(f'- **"{agent_name}"**: {purpose}')
            except Exception as e:
                logger.error(f"Failed to read registry file {filename}: {e}")
                
    return "\n".join(compiled_descriptions)



# ── JSON Schema for Structured Output ─────────────────────────────────────────
PRICING_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {
            "type": "string",
            "description": "Tóm tắt điều hành: đánh giá tổng quan và khuyến nghị chính (2-3 câu)"
        },
        "current_assessment": {
            "type": "string",
            "description": "Phân tích hiệu suất hiện tại: load factor, giá vé, so sánh với benchmark"
        },
        "competitor_analysis": {
            "type": "string",
            "description": "Phân tích cạnh tranh và bối cảnh thị trường"
        },
        "mathematical_basis": {
            "type": "string",
            "description": "Giải thích cơ sở toán học (demand elasticity, revenue optimization)"
        },
        "recommended_price": {
            "type": "number",
            "description": "Giá vé đề xuất tối ưu (VND)"
        },
        "price_change_pct": {
            "type": "number",
            "description": "Phần trạng thay đổi giá so với hiện tại"
        },
        "confidence_level": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": "Mức độ tin cậy của khuyến nghị"
        },
        "risk_factors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Danh sách yếu tố rủi ro cần lưu ý"
        },
        "action_items": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Các bước hành động cụ thể đề xuất"
        }
    },
    "required": [
        "executive_summary", "current_assessment", "recommended_price",
        "confidence_level", "risk_factors"
    ]
}


# ── JSON Schema for Market Factor Extraction (Optimizer adjustments) ──────────
MARKET_FACTORS_SCHEMA = {
    "type": "object",
    "properties": {
        "factors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Tên ngắn gọn của yếu tố thị trường"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["demand", "price_sensitivity", "cost"],
                        "description": "Loại tác động: nhu cầu / độ nhạy giá / chi phí khai thác"
                    },
                    "direction": {
                        "type": "integer",
                        "enum": [-1, 1],
                        "description": "Hướng tác động: 1 = tăng, -1 = giảm"
                    },
                    "magnitude": {
                        "type": "number",
                        "description": "Độ lớn tác động (0.0 - 1.0)"
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Độ tin cậy của nhận định (0.0 - 1.0)"
                    }
                },
                "required": ["name", "type", "direction", "magnitude", "confidence"]
            }
        }
    },
    "required": ["factors"]
}


# ── Reducer Functions for Parallel Node Execution ─────────────────────────────
def reduce_tools_called(left: list, right: list) -> list:
    """Merge tools_called list, preserving order and removing duplicates."""
    combined = list(left) if left else []
    if not right:
        return combined
    for item in right:
        if item not in combined:
            combined.append(item)
    return combined


def reduce_error(left: str | None, right: str | None) -> str | None:
    """Combine non-None error strings if multiple errors occur."""
    if left and right:
        return f"{left}; {right}"
    return right if right is not None else left


# ── Agent State Definition ────────────────────────────────────────────────────
class AgentState(TypedDict):
    """Typed state shared across all LangGraph nodes."""
    # Input
    user_query: str
    search_term: str

    # Tool results
    flight_data: dict | None
    optimizer_result: dict | None
    competitor_data: list | None
    rag_context: str | None
    ml_prediction_result: dict | None
    price_comparison_result: dict | None
    adjusted_prediction_result: dict | None

    # Tools tracking
    tools_called: Annotated[list, reduce_tools_called]

    # LLM output
    thinking: str
    report: dict | None         # Structured JSON report
    message: str                # Formatted markdown for display

    # Control flow
    tools_needed: list          # Which tools the supervisor decides to run
    iteration_count: int        # Loop guard
    error: Annotated[str | None, reduce_error]
    next_agent: str             # Next worker selected by the supervisor

    # Advanced metadata
    target_date: str | None
    parsed_route: str | None
    comparison_intent: bool


# ── Langfuse Tracing Helper ──────────────────────────────────────────────────
class TraceContext:
    """Manages Langfuse trace lifecycle for a copilot run."""

    def __init__(self, user_query: str):
        self.trace = None
        self.spans = {}
        
        if _langfuse:
            try:
                # Always prefer the standard v2+ trace() method
                if hasattr(_langfuse, "trace"):
                    self.trace = _langfuse.trace(
                        name="copilot_flow",
                        input={"query": user_query},
                        metadata={"model": LLM_MODEL},
                    )
            except Exception as e:
                logger.warning(f"Failed to create Langfuse trace via trace(): {e}")
                
            # If trace() failed or doesn't exist, try start_observation
            if not self.trace and hasattr(_langfuse, "start_observation"):
                try:
                    self.trace = _langfuse.start_observation(
                        name="copilot_flow",
                        as_type="span",
                        input={"query": user_query},
                        metadata={"model": LLM_MODEL},
                    )
                except Exception as e:
                    logger.warning(f"Failed to create Langfuse trace via start_observation(): {e}")

    def start_span(self, name: str, input_data: dict = None) -> None:
        if self.trace:
            try:
                # StatefulTraceClient or SpanClient both support creating child spans
                if hasattr(self.trace, "span"):
                    span = self.trace.span(name=name, input=input_data or {})
                    self.spans[name] = span
                elif hasattr(self.trace, "start_observation"):
                    span = self.trace.start_observation(
                        name=name,
                        as_type="span",
                        input=input_data or {},
                    )
                    self.spans[name] = span
                elif _langfuse and hasattr(_langfuse, "start_observation"):
                    parent_id = getattr(self.trace, "id", None)
                    trace_id = getattr(self.trace, "trace_id", None)
                    trace_ctx = {"trace_id": trace_id, "parent_span_id": parent_id} if trace_id else None
                    span = _langfuse.start_observation(
                        name=name,
                        as_type="span",
                        input=input_data or {},
                        trace_context=trace_ctx
                    )
                    self.spans[name] = span
            except Exception as e:
                logger.debug(f"Failed to start span {name}: {e}")

    def end_span(self, name: str, output_data: dict = None, level: str = "DEFAULT") -> None:
        span = self.spans.get(name)
        if span:
            try:
                if hasattr(span, "end"):
                    span.end(output=output_data or {}, level=level)
            except Exception as e:
                logger.debug(f"Failed to end span {name}: {e}")

    def log_generation(self, name: str, model: str, input_text: str,
                       output_text: str, usage: dict = None) -> None:
        if self.trace:
            try:
                if hasattr(self.trace, "generation"):
                    self.trace.generation(
                        name=name, model=model,
                        input=input_text, output=output_text,
                        usage=usage or {},
                    )
                elif hasattr(self.trace, "start_observation"):
                    gen = self.trace.start_observation(
                        name=name,
                        as_type="generation",
                        model=model,
                        input=input_text,
                    )
                    if hasattr(gen, "end"):
                        gen.end(
                            output=output_text,
                            usage=usage or {},
                        )
                elif _langfuse and hasattr(_langfuse, "start_observation"):
                    parent_id = getattr(self.trace, "id", None)
                    trace_id = getattr(self.trace, "trace_id", None)
                    trace_ctx = {"trace_id": trace_id, "parent_span_id": parent_id} if trace_id else None
                    gen = _langfuse.start_observation(
                        name=name,
                        as_type="generation",
                        model=model,
                        input=input_text,
                        trace_context=trace_ctx
                    )
                    if hasattr(gen, "end"):
                        gen.end(
                            output=output_text,
                            usage=usage or {},
                        )
            except Exception as e:
                logger.debug(f"Failed to log generation {name}: {e}")

    def finalize(self, output: dict = None) -> None:
        if self.trace:
            try:
                if hasattr(self.trace, "update"):
                    self.trace.update(output=output or {})
                elif hasattr(self.trace, "end"):
                    self.trace.end(output=output or {})
            except Exception as e:
                logger.debug(f"Failed to finalize trace: {e}")
        if _langfuse:
            try:
                _langfuse.flush()
            except Exception:
                pass


import contextvars

# Shared thread-safe trace context proxy using contextvars
_current_trace_var = contextvars.ContextVar("current_trace", default=None)

class TraceContextProxy:
    def __getattr__(self, name):
        obj = _current_trace_var.get()
        if obj is None:
            raise AttributeError(f"No active trace context. Cannot access {name}.")
        return getattr(obj, name)
        
    def __bool__(self):
        return _current_trace_var.get() is not None

_current_trace = TraceContextProxy()


def extract_route(query: str) -> str | None:
    """Extract route from natural language query using Vietnamese city names or IATA codes."""
    if not query:
        return None
    query_lower = query.lower()
    
    aliases = {
        "SGN": ["thành phố hồ chí minh", "thanh pho ho chi minh", "hồ chí minh", "ho chi minh", "sài gòn", "sai gon", "sgn", "hcm", "tphcm"],
        "HAN": ["hà nội", "ha noi", "han", "hn"],
        "DAD": ["đà nẵng", "da nang", "dad", "dn"],
        "CXR": ["nha trang", "cam ranh", "cxr"],
        "PQC": ["phú quốc", "phu quoc", "pqc"],
        "HPH": ["hải phòng", "hai phong", "hph", "cat bi", "cát bi", "hp"]
    }
    
    matches = []
    for iata, terms in aliases.items():
        for term in terms:
            # We want to match whole phrases or boundaries, avoiding partial word matching (like "hn" in "hôm nay")
            pattern = r'(?i)\b' + re.escape(term) + r'\b'
            for m in re.finditer(pattern, query_lower):
                matches.append((iata, m.start(), m.end(), len(term)))
                
    if not matches:
        return None
        
    # Remove overlapping matches, prioritize longer terms
    matches.sort(key=lambda x: x[3], reverse=True)
    final_matches = []
    for m in matches:
        overlap = False
        for accepted in final_matches:
            if not (m[2] <= accepted[1] or m[1] >= accepted[2]):
                overlap = True
                break
        if not overlap:
            final_matches.append(m)
            
    final_matches.sort(key=lambda x: x[1])
    
    unique_iatas = []
    for m in final_matches:
        if not unique_iatas or unique_iatas[-1] != m[0]:
            unique_iatas.append(m[0])
            
    if len(unique_iatas) >= 2:
        loc1_iata, loc1_start, loc1_end, _ = final_matches[0]
        loc2_iata, loc2_start, loc2_end, _ = final_matches[1]
        
        text_before_loc1 = query_lower[:loc1_start]
        text_between = query_lower[loc1_end:loc2_start]
        
        has_from_before_loc1 = any(w in text_before_loc1.split()[-2:] for w in ["từ", "from"]) if text_before_loc1.split() else False
        has_from_between = any(w in text_between.split() for w in ["từ", "from"])
        
        if has_from_between and not has_from_before_loc1:
            return f"{loc2_iata}-{loc1_iata}"
        else:
            return f"{loc1_iata}-{loc2_iata}"
            
    return None


# ── Node Functions ───────────────────────────────────────────────────────────

def parse_query(state: AgentState) -> dict:
    """Parse flight number, route, date, and comparison intent from user query."""
    query = state["user_query"]
    query_upper = query.upper()
    query_lower = query.lower()

    # 1. Parse flight number
    flight_match = re.search(r'(VJ\d{3,4})|(A\d{3})', query, re.IGNORECASE)
    flight_no = flight_match.group(0).upper() if flight_match else None

    # 2. Parse route
    parsed_route = None
    normalized_query = query_upper
    normalized_query = re.sub(r'\b(?:ĐẾN|TO|ĐI|->|=>|AND|VÀ)\b', '-', normalized_query)
    normalized_query = re.sub(r'\s*-\s*', '-', normalized_query)
    route_match = re.search(r'\b([A-Z]{3})-([A-Z]{3})\b', normalized_query)
    
    if route_match:
        parsed_route = route_match.group(0)
    else:
        iata_codes = re.findall(r'\b[A-Z]{3}\b', query_upper)
        if len(iata_codes) == 2:
            parsed_route = f"{iata_codes[0]}-{iata_codes[1]}"

    if not parsed_route:
        parsed_route = extract_route(query)

    # 3. Parse date (dynamically resolve 'hôm nay' / 'ngày mai' in VN local time)
    target_date = None
    try:
        today_dt = vn_now()
    except Exception:
        today_dt = None

    if "hôm nay" in query_lower or "today" in query_lower:
        target_date = today_dt.strftime("%Y-%m-%d") if today_dt else "2026-06-10"
    elif "ngày mai" in query_lower or "tomorrow" in query_lower:
        target_date = (today_dt + timedelta(days=1)).strftime("%Y-%m-%d") if today_dt else "2026-06-11"
    elif "ngày mốt" in query_lower or "ngày kia" in query_lower or "ngay mot" in query_lower or "ngay kia" in query_lower:
        target_date = (today_dt + timedelta(days=2)).strftime("%Y-%m-%d") if today_dt else "2026-06-12"
    elif "cuối tuần sau" in query_lower or "cuoi tuan sau" in query_lower:
        if today_dt:
            days_to_saturday = 5 - today_dt.weekday() + 7
            target_date = (today_dt + timedelta(days=days_to_saturday)).strftime("%Y-%m-%d")
        else:
            target_date = "2026-06-20"
    elif "cuối tuần" in query_lower or "cuoi tuan" in query_lower or "weekend" in query_lower:
        if today_dt:
            if today_dt.weekday() in [5, 6]:
                target_date = today_dt.strftime("%Y-%m-%d")
            else:
                days_to_saturday = 5 - today_dt.weekday()
                target_date = (today_dt + timedelta(days=days_to_saturday)).strftime("%Y-%m-%d")
        else:
            target_date = "2026-06-13"
    elif "tuần sau" in query_lower or "tuan sau" in query_lower or "next week" in query_lower:
        target_date = (today_dt + timedelta(days=7)).strftime("%Y-%m-%d") if today_dt else "2026-06-18"
    else:
        # Match YYYY-MM-DD or YYYY/MM/DD specifically for June 2026
        date_match = re.search(r'\b(2026)[-/](0?6)[-/]([0-2]?\d|30)\b', query)
        if date_match:
            year, month, day = date_match.groups()
            target_date = f"{year}-{int(month):02d}-{int(day):02d}"
        else:
            # Match DD/MM/YYYY or DD-MM-YYYY
            date_match2 = re.search(r'\b([0-2]?\d|30)[-/](0?6)[-/](2026)\b', query)
            if date_match2:
                day, month, year = date_match2.groups()
                target_date = f"{year}-{int(month):02d}-{int(day):02d}"
            else:
                # Match DD/MM or DD-MM
                date_match3 = re.search(r'\b([0-2]?\d|30)[-/](0?6)\b', query)
                if date_match3:
                    day, month = date_match3.groups()
                    target_date = f"2026-{int(month):02d}-{int(day):02d}"

    # 4. Comparison intent
    comparison_keywords = ["so sánh", "đối thủ", "hãng khác", "bamboo", "vietnam airlines", "vietravel", "pacific", "compare", "competitor"]
    comparison_intent = any(kw in query_lower for kw in comparison_keywords)

    # 4b. Multi-turn fallback: fill missing slots from session context seeded
    # into the initial state (e.g. follow-up "còn ngày mốt thì sao?" inherits
    # the route from the previous turn but keeps its own freshly-parsed date)
    if not parsed_route and state.get("parsed_route"):
        parsed_route = state["parsed_route"]
    if not target_date and state.get("target_date"):
        target_date = state["target_date"]

    # 5. Set search term
    search_term = ""
    has_target = False
    if flight_no:
        search_term = flight_no
        has_target = True
    elif parsed_route:
        search_term = parsed_route
        has_target = True
    elif target_date:
        search_term = target_date
        has_target = True

    if not has_target and state.get("search_term"):
        # Inherit the previous turn's target (e.g. flight number) wholesale
        search_term = state["search_term"]
        has_target = True

    # 6. Tools needed
    tools_needed = []
    if has_target:
        tools_needed.append("db")
        
        if any(kw in query_lower for kw in ["dự báo", "dự đoán", "predict", "forecast", "giá"]):
            tools_needed.append("ml")
            
        if any(kw in query_lower for kw in ["tối ưu", "optimize", "doanh thu"]):
            tools_needed.append("optimizer")
            
        if comparison_intent:
            tools_needed.append("competitor")
            tools_needed.append("compare")
            
        if any(kw in query_lower for kw in ["sự kiện", "thời tiết", "bối cảnh", "nhiên liệu"]):
            tools_needed.append("rag")

    return {
        "search_term": search_term,
        "tools_needed": tools_needed,
        "iteration_count": 0,
        "target_date": target_date,
        "parsed_route": parsed_route,
        "comparison_intent": comparison_intent
    }


def query_database(state: AgentState) -> dict:
    """Query SQL Server for flight data — supports aggregate queries for route/date combinations."""
    global _current_trace
    if _current_trace:
        _current_trace.start_span("query_database", {"search_term": state["search_term"]})

    search_term = state["search_term"].strip().upper()
    target_date = state.get("target_date")
    parsed_route = state.get("parsed_route")
    tools_called = list(state.get("tools_called", []))
    queries_executed = []

    if not search_term:
        if _current_trace:
            _current_trace.end_span("query_database", {"found": False, "reason": "No flight/route/date specified"})
        return {"flight_data": None}

    try:
        with _connect() as conn:
            cursor = conn.cursor()

            def db_execute(sql, params=None):
                cleaned_sql = " ".join(sql.strip().split())
                logger.info(f"Executing SQL: {cleaned_sql} | Params: {params}")
                queries_executed.append({"sql": cleaned_sql, "params": list(params) if params else []})
                if params is not None:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)

            # Case 1: Route + Date query
            if parsed_route and target_date:
                # 1. Total flights on this route on this date
                db_execute("""
                    SELECT COUNT(DISTINCT flight_no) FROM flights
                    WHERE route = ? AND flight_date = ?
                """, (parsed_route, target_date))
                total_flights = cursor.fetchone()[0] or 0

                # 2. Avg price & load factor on this route on this date
                # NULLIF excludes 0-VND rows (missing booking data) from the average
                db_execute("""
                    SELECT AVG(NULLIF(mny_GL_Charges_Total, 0)), AVG(LF_by_date) FROM flights
                    WHERE route = ? AND flight_date = ?
                """, (parsed_route, target_date))
                avg_price, avg_lf = cursor.fetchone()
                avg_price = avg_price or 0.0
                avg_lf = avg_lf or 0.0

                # 3. List of flight details
                db_execute("""
                    SELECT
                        id, flight_no, flight_date, str_Dep, str_Arr, route,
                        mny_GL_Charges_Total AS price, LF_by_date AS lf, lng_Capacity AS capacity,
                        fare_family, lead_time_days, booking_velocity_3d, Weekday, IsHoliday
                    FROM flights
                    WHERE route = ? AND flight_date = ?
                    ORDER BY flight_no
                """, (parsed_route, target_date))
                
                rows = cursor.fetchall()
                cols = [d[0] for d in cursor.description]
                flights_list = []
                seen_f = set()
                for r in rows:
                    fd = dict(zip(cols, r))
                    if "flight_date" in fd and hasattr(fd["flight_date"], "isoformat"):
                        fd["flight_date"] = fd["flight_date"].isoformat()
                    f_no = str(fd.get("flight_no") or "").strip()
                    if f_no and f_no not in seen_f:
                        seen_f.add(f_no)
                        fd["flight_no"] = f_no
                        flights_list.append(fd)

                data = {
                    "is_aggregate": True,
                    "target_date": target_date,
                    "parsed_route": parsed_route,
                    "total_flights": total_flights,
                    "avg_price": avg_price,
                    "avg_lf": avg_lf,
                    "flights_list": flights_list
                }

                if flights_list:
                    data.update(flights_list[0])
                    data["price"] = avg_price
                    data["lf"] = avg_lf

                tools_called.append({
                    "name": "Query SQL Server (Aggregate DB)",
                    "args": f"Route: '{parsed_route}', Date: '{target_date}'",
                    "result": f"Tìm thấy {total_flights} chuyến bay chặng {parsed_route} ngày {target_date}. Giá TB: {avg_price:,.0f} VND, LF trung bình: {avg_lf*100:.1f}%"
                })

            # Case 2: Only Date query (e.g. all flights today)
            elif target_date and not parsed_route and search_term == target_date:
                # 1. Total flights scheduled today
                db_execute("""
                    SELECT COUNT(DISTINCT flight_no) FROM flights
                    WHERE flight_date = ?
                """, (target_date,))
                total_flights = cursor.fetchone()[0] or 0

                # 2. Avg price & load factor today
                # NULLIF excludes 0-VND rows (missing booking data) from the average
                db_execute("""
                    SELECT AVG(NULLIF(mny_GL_Charges_Total, 0)), AVG(LF_by_date) FROM flights
                    WHERE flight_date = ?
                """, (target_date,))
                avg_price, avg_lf = cursor.fetchone()
                avg_price = avg_price or 0.0
                avg_lf = avg_lf or 0.0

                # 3. Route breakdown
                db_execute("""
                    SELECT route, COUNT(DISTINCT flight_no) AS flight_cnt, AVG(NULLIF(mny_GL_Charges_Total, 0)) AS avg_price, AVG(LF_by_date) AS avg_lf
                    FROM flights
                    WHERE flight_date = ?
                    GROUP BY route
                    ORDER BY flight_cnt DESC
                """, (target_date,))
                routes = []
                for r in cursor.fetchall():
                    routes.append({
                        "route": r[0],
                        "flight_cnt": r[1],
                        "avg_price": r[2] or 0.0,
                        "avg_lf": r[3] or 0.0
                    })

                # 4. Sample list of flights
                db_execute("""
                    SELECT TOP 20
                        id, flight_no, flight_date, str_Dep, str_Arr, route,
                        mny_GL_Charges_Total AS price, LF_by_date AS lf, lng_Capacity AS capacity,
                        fare_family, lead_time_days, booking_velocity_3d, Weekday, IsHoliday
                    FROM flights
                    WHERE flight_date = ?
                    ORDER BY LF_by_date DESC
                """, (target_date,))
                rows = cursor.fetchall()
                cols = [d[0] for d in cursor.description]
                flights_list = []
                seen_f = set()
                for r in rows:
                    fd = dict(zip(cols, r))
                    if "flight_date" in fd and hasattr(fd["flight_date"], "isoformat"):
                        fd["flight_date"] = fd["flight_date"].isoformat()
                    f_no = str(fd.get("flight_no") or "").strip()
                    if f_no and f_no not in seen_f:
                        seen_f.add(f_no)
                        fd["flight_no"] = f_no
                        flights_list.append(fd)

                data = {
                    "is_aggregate": True,
                    "target_date": target_date,
                    "total_flights": total_flights,
                    "avg_price": avg_price,
                    "avg_lf": avg_lf,
                    "routes": routes,
                    "flights_list": flights_list
                }

                if flights_list:
                    data.update(flights_list[0])
                    data["price"] = avg_price
                    data["lf"] = avg_lf

                tools_called.append({
                    "name": "Query SQL Server (Aggregate DB)",
                    "args": f"Date: '{target_date}'",
                    "result": f"Tổng cộng hôm nay có {total_flights} chuyến bay hoạt động. Giá TB: {avg_price:,.0f} VND, LF trung bình: {avg_lf*100:.1f}% trên {len(routes)} chặng bay."
                })

            # Case 3: Single flight number or fallback single route lookup (original behavior)
            else:
                db_execute("""
                    SELECT TOP 1
                        id, flight_no, flight_date, str_Dep, str_Arr, route,
                        mny_GL_Charges_Total AS price, LF_by_date AS lf, lng_Capacity AS capacity,
                        fare_family, lead_time_days, booking_velocity_3d, Weekday, IsHoliday
                    FROM flights
                    WHERE UPPER(flight_no) = ? OR UPPER(route) = ?
                    ORDER BY flight_date DESC
                """, (search_term, search_term))

                row = cursor.fetchone()
                if not row:
                    db_execute("""
                        SELECT TOP 1
                            id, flight_no, flight_date, str_Dep, str_Arr, route,
                            mny_GL_Charges_Total AS price, LF_by_date AS lf, lng_Capacity AS capacity,
                            fare_family, lead_time_days, booking_velocity_3d, Weekday, IsHoliday
                        FROM flights
                        WHERE UPPER(flight_no) LIKE ?
                        ORDER BY flight_date DESC
                    """, (f"%{search_term}%",))
                    row = cursor.fetchone()

                cols = [d[0] for d in cursor.description] if cursor.description else []
                
                if row:
                    data = dict(zip(cols, row))
                    if "flight_date" in data and hasattr(data["flight_date"], "isoformat"):
                        data["flight_date"] = data["flight_date"].isoformat()
                    
                    tools_called.append({
                        "name": "Query SQL Server (Direct DB)",
                        "args": f"Search term: '{search_term}'",
                        "result": f"Tìm thấy chuyến bay {data['flight_no']} ({data['route']}) ngày {data['flight_date']}. Giá: {data['price']:,.0f} VND, LF: {data['lf']*100:.1f}%"
                    })
                else:
                    data = None
                    tools_called.append({
                        "name": "Query SQL Server (Direct DB)",
                        "args": f"Search term: '{search_term}'",
                        "result": f"Không tìm thấy dữ liệu cho '{search_term}'."
                    })

            cursor.close()

        if _current_trace:
            _current_trace.end_span("query_database", {
                "found": data is not None,
                "queries_executed": queries_executed
            })
        return {"flight_data": data, "tools_called": tools_called}

    except Exception as ex:
        logger.error(f"DB query failed: {ex}")
        if _current_trace:
            _current_trace.end_span("query_database", {
                "found": False,
                "error": str(ex),
                "queries_executed": queries_executed
            })
        
        tools_called.append({
            "name": "Query SQL Server (Direct DB)",
            "args": f"Search term: '{search_term}'",
            "result": f"Lỗi truy vấn CSDL: {str(ex)}"
        })
        return {
            "flight_data": None,
            "error": f"Lỗi truy vấn cơ sở dữ liệu: {str(ex)}",
            "tools_called": tools_called
        }


def run_ml_prediction(state: AgentState) -> dict:
    """Run trained Machine Learning model to predict ticket fares. Supports aggregate/batch prediction."""
    global _current_trace
    if _current_trace:
        _current_trace.start_span("run_ml_prediction")

    flight = state["flight_data"]
    tools_called = list(state.get("tools_called", []))

    if not flight:
        if _current_trace:
            _current_trace.end_span("run_ml_prediction", {"found": False})
        return {"tools_called": tools_called}

    try:
        import joblib
        from backend.src.api.main import app
        from backend.config import OUTPUTS_DIR
        from backend.src.models.trainer import load_kaggle_models, get_best_model_name
        from backend.src.api.services.prediction_service import _predict_classes_for_flight, _get_model
        from backend.src.api.competitor_service import CompetitorService

        # Get models/encoders from app state or load them dynamically (fallback)
        class DummyAppState:
            def __init__(self):
                self.models = {}
                self.label_encoders = {}
                self.target_transformer = None
                self.feature_names = []
                self.best_model_name = "XGBoost"

        app_state = getattr(app, "state", None)
        if not app_state or not getattr(app_state, "models", None):
            logger.info("FastAPI app state not available. Loading models dynamically...")
            app_state = DummyAppState()
            app_state.models = load_kaggle_models()
            
            enc_path = os.path.join(OUTPUTS_DIR, "label_encoders.pkl")
            if os.path.exists(enc_path):
                app_state.label_encoders = joblib.load(enc_path)
            
            qt_path = os.path.join(OUTPUTS_DIR, "target_transformer.pkl")
            if os.path.exists(qt_path):
                app_state.target_transformer = joblib.load(qt_path)
                
            fn_path = os.path.join(OUTPUTS_DIR, "feature_names.txt")
            if os.path.exists(fn_path):
                with open(fn_path) as f:
                    app_state.feature_names = [l.strip() for l in f if l.strip()]
            
            if app_state.models:
                app_state.best_model_name = get_best_model_name()

        model = _get_model(app_state)
        if not model:
            raise ValueError("No ML models could be loaded for prediction.")

        # Batch prediction if aggregate flight_data
        if flight.get("is_aggregate") == True:
            flights_list = flight.get("flights_list", [])
            flights_to_predict = flights_list[:15] # limit to 15 representative flights
            
            predictions_list = []
            comp_svc = CompetitorService()
            for f in flights_to_predict:
                enriched_f = f.copy()
                if "capacity" in enriched_f and "lng_Capacity" not in enriched_f:
                    enriched_f["lng_Capacity"] = enriched_f["capacity"]
                if "str_Dep" not in enriched_f and "route" in enriched_f:
                    parts = enriched_f["route"].split("-")
                    enriched_f["str_Dep"] = parts[0] if len(parts) > 0 else "SGN"
                    enriched_f["str_Arr"] = parts[1] if len(parts) > 1 else "HAN"
                
                f_route = enriched_f.get("route", "SGN-HAN")
                f_date = enriched_f.get("flight_date", None)
                comp_data = comp_svc.get_prices(
                    route=f_route,
                    base_price=enriched_f.get("price", 1000000.0),
                    flight_date=str(f_date) if f_date else None,
                    fare_class=enriched_f.get("fare_family", "Eco"),
                )
                comp_prices = [c.price for c in comp_data if c.price > 0]
                avg_comp_price = sum(comp_prices) / len(comp_prices) if comp_prices else None
                enriched_f["competitor_price"] = avg_comp_price

                preds = _predict_classes_for_flight(enriched_f, model, app_state)
                predictions_list.append({
                    "flight_no": f["flight_no"],
                    "route": f["route"],
                    "current_price": f["price"],
                    "classes": preds
                })
                
            model_name = getattr(app_state, "best_model_name", "XGBoost")
            tools_called.append({
                "name": f"ML Model Batch Price Prediction ({model_name})",
                "args": f"Predicted Eco/Deluxe/SkyBoss classes for {len(flights_to_predict)} flights.",
                "result": f"Đã hoàn thành dự báo giá vé hàng loạt cho {len(flights_to_predict)} chuyến bay đại diện."
            })
            
            if _current_trace:
                _current_trace.end_span("run_ml_prediction", {"batch_size": len(flights_to_predict)})
                
            return {
                "ml_prediction_result": {
                    "is_aggregate": True,
                    "predictions": predictions_list
                },
                "tools_called": tools_called
            }

        # Single flight prediction (original logic)
        enriched_flight = flight.copy()
        if "capacity" in enriched_flight and "lng_Capacity" not in enriched_flight:
            enriched_flight["lng_Capacity"] = enriched_flight["capacity"]
        if "str_Dep" not in enriched_flight and "route" in enriched_flight:
            parts = enriched_flight["route"].split("-")
            enriched_flight["str_Dep"] = parts[0] if len(parts) > 0 else "SGN"
            enriched_flight["str_Arr"] = parts[1] if len(parts) > 1 else "HAN"

        route = enriched_flight.get("route", "SGN-HAN")
        base_price = enriched_flight.get("price", 1000000.0)
        flight_date = enriched_flight.get("flight_date", None)
        
        comp_svc = CompetitorService()
        comp_data = comp_svc.get_prices(
            route=route,
            base_price=base_price,
            flight_date=str(flight_date) if flight_date else None,
            fare_class=enriched_flight.get("fare_family", "Eco"),
        )
        comp_prices = [c.price for c in comp_data if c.price > 0]
        avg_comp_price = sum(comp_prices) / len(comp_prices) if comp_prices else None
        enriched_flight["competitor_price"] = avg_comp_price

        predictions = _predict_classes_for_flight(enriched_flight, model, app_state)
        
        model_name = getattr(app_state, "best_model_name", "XGBoost")
        tools_called.append({
            "name": f"ML Model Price Prediction ({model_name})",
            "args": f"flight_no={flight['flight_no']}, route={flight['route']}, price={flight['price']}, competitor_price={avg_comp_price}",
            "result": ", ".join([f"{cls}: {val:,.0f} VND" for cls, val in predictions.items()])
        })

        if _current_trace:
            _current_trace.end_span("run_ml_prediction", {"predicted_eco": predictions.get("Eco")})

        return {"ml_prediction_result": predictions, "tools_called": tools_called}

    except Exception as ex:
        logger.error(f"ML price prediction failed: {ex}")
        if _current_trace:
            _current_trace.end_span("run_ml_prediction", {"error": str(ex)})
        return {
            "ml_prediction_result": None,
            "error": f"Lỗi dự đoán giá từ mô hình học máy: {str(ex)}",
            "tools_called": tools_called
        }


def _keyword_market_factors(rag_context: str) -> list[dict]:
    """
    Keyword-based fallback for market factor extraction when the LLM is
    unavailable. Unlike the old elif chain, factors are ADDITIVE — a festival
    and a storm in the same context both contribute and partially offset.
    """
    rl = rag_context.lower()
    factors = []
    if any(t in rl for t in ["lễ hội", "festival", "tết", "concert", "cao điểm", "pháo hoa", "diff", "biển nha trang"]):
        factors.append({"name": "Sự kiện/lễ hội cao điểm (keyword)", "type": "demand",
                        "direction": 1, "magnitude": 0.75, "confidence": 0.8})
    if any(t in rl for t in ["tuần lễ du lịch", "mùa du lịch hè", "tăng mạnh", "tăng vọt"]):
        factors.append({"name": "Mùa du lịch / nhu cầu tăng (keyword)", "type": "demand",
                        "direction": 1, "magnitude": 0.5, "confidence": 0.7})
    if any(t in rl for t in ["mưa lớn kéo dài", "cảnh báo mưa lớn", "bão", "thiên tai", "hoãn lịch trình"]):
        factors.append({"name": "Thời tiết bất lợi (keyword)", "type": "demand",
                        "direction": -1, "magnitude": 0.55, "confidence": 0.8})
    if any(t in rl for t in ["săn sale", "khuyến mãi lớn", "kích cầu", "thấp điểm"]):
        factors.append({"name": "Thấp điểm / khuyến mãi kích cầu (keyword)", "type": "price_sensitivity",
                        "direction": 1, "magnitude": 0.6, "confidence": 0.7})
    if any(t in rl for t in ["nhiên liệu", "jet a1"]) and "tăng" in rl:
        factors.append({"name": "Giá nhiên liệu Jet A1 tăng (keyword)", "type": "cost",
                        "direction": 1, "magnitude": 0.4, "confidence": 0.6})
    return factors


def _clamp01(value, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


async def extract_market_factors(rag_context: str, route: str = "", target_date: str = "") -> list[dict]:
    """
    Extract structured market factors from RAG context via LLM structured output.
    Falls back to keyword heuristics when the LLM call or parsing fails.
    """
    try:
        prompt = load_agent_prompt(
            "market_factor_agent.md",
            rag_context=rag_context,
            route=route or "N/A",
            target_date=target_date or "N/A",
        )
        content, _reasoning, _usage = await call_nim_llm(
            prompt=prompt,
            schema=MARKET_FACTORS_SCHEMA,
            temperature=0.1,
            max_tokens=1024,
        )
        data = json.loads(content)
        raw_factors = data.get("factors", []) if isinstance(data, dict) else []

        factors = []
        for f in raw_factors:
            if not isinstance(f, dict):
                continue
            ftype = f.get("type")
            if ftype not in ("demand", "price_sensitivity", "cost"):
                continue
            try:
                direction = 1 if float(f.get("direction", 0)) > 0 else -1
            except (TypeError, ValueError):
                continue
            factors.append({
                "name": str(f.get("name", "unnamed"))[:120],
                "type": ftype,
                "direction": direction,
                "magnitude": _clamp01(f.get("magnitude")),
                "confidence": _clamp01(f.get("confidence")),
            })
        logger.info(f"[Market Factors] LLM extracted {len(factors)} factors from RAG context.")
        return factors
    except Exception as e:
        logger.warning(f"Market factor extraction via LLM failed ({e}). Using keyword fallback.")
        return _keyword_market_factors(rag_context)


def compose_market_adjustments(factors: list[dict]) -> dict:
    """
    Compose extracted market factors into optimizer adjustments.

    Direction comes from factor semantics; MAGNITUDE is scaled by confidence —
    uncertain signals shrink toward neutral instead of being applied at full
    strength (high volatility => smaller, more conservative price moves):
      - demand factors        -> demand_shift (exp of summed impact) and elasticity
                                 (high demand => less price-sensitive, ε toward 0)
      - price_sensitivity     -> elasticity only (more sensitive => ε more negative)
      - cost factors          -> price floor only (never the demand curve)
    """
    DEMAND_SHIFT_GAIN = 0.30      # exp(0.30 * 0.75) ≈ 1.25 — matches old peak-event step
    ELASTICITY_GAIN = 0.25
    COST_PRESSURE_GAIN = 0.10

    d_score = s_score = c_score = 0.0
    for f in factors:
        impact = f["direction"] * f["magnitude"] * f["confidence"]
        if f["type"] == "demand":
            d_score += impact
        elif f["type"] == "price_sensitivity":
            s_score += impact
        elif f["type"] == "cost":
            c_score += impact

    import math
    demand_shift = math.exp(DEMAND_SHIFT_GAIN * max(-1.5, min(1.5, d_score)))
    demand_shift = max(0.70, min(1.40, demand_shift))

    elasticity_adj = ELASTICITY_GAIN * d_score - ELASTICITY_GAIN * s_score
    elasticity_adj = max(-0.30, min(0.30, elasticity_adj))

    cost_pressure = 1.0 + COST_PRESSURE_GAIN * max(0.0, c_score)
    cost_pressure = min(1.15, cost_pressure)

    return {
        "demand_shift_factor": round(demand_shift, 3),
        "elasticity_adjustment": round(elasticity_adj, 3),
        "cost_pressure_factor": round(cost_pressure, 3),
        "demand_score": round(d_score, 3),
        "sensitivity_score": round(s_score, 3),
        "cost_score": round(c_score, 3),
    }


async def run_optimizer(state: AgentState) -> dict:
    """Run SciPy revenue optimizer with data-driven elasticity."""
    global _current_trace
    if _current_trace:
        _current_trace.start_span("run_optimizer")

    flight = state.get("flight_data")
    tools_called = list(state.get("tools_called", []))

    if not flight or flight.get("is_aggregate") == True:
        tools_called.append({
            "name": "Revenue Optimizer (SciPy + Data-Driven Elasticity)",
            "args": "None",
            "result": "Bỏ qua tối ưu hóa: Tác vụ tổng hợp hoặc không có thông tin chuyến bay cụ thể."
        })
        if _current_trace:
            _current_trace.end_span("run_optimizer", {"found": False})
        return {"tools_called": tools_called}

    route = flight.get("route", "")
    fare_class = flight.get("fare_family", "Eco")
    flight_date = flight.get("flight_date", "")
    month = None
    if flight_date:
        try:
            from datetime import datetime
            month = datetime.fromisoformat(str(flight_date)).month
        except Exception:
            pass

    # Extract structured market factors from RAG context (LLM structured output
    # with keyword fallback), then compose them into continuous, confidence-weighted
    # optimizer adjustments — replaces the old single-winner elif keyword chain.
    rag_context = state.get("rag_context") or ""
    market_factors: list[dict] = []
    if rag_context:
        market_factors = await extract_market_factors(
            rag_context, route=route, target_date=str(flight_date) if flight_date else ""
        )
    adjustments = compose_market_adjustments(market_factors)
    demand_shift = adjustments["demand_shift_factor"]
    elasticity_adj = adjustments["elasticity_adjustment"]
    cost_pressure = adjustments["cost_pressure_factor"]

    opt = optimize_flight(
        base_price=flight["price"],
        base_lf=flight["lf"],
        capacity=flight["capacity"],
        route=route,
        fare_class=fare_class,
        month=month,
        demand_shift_factor=demand_shift,
        elasticity_adjustment=elasticity_adj,
        cost_pressure_factor=cost_pressure
    )
    opt["market_factors"] = market_factors
    elasticity_info = f", ε={opt.get('elasticity_used', -1.2):.2f} ({opt.get('elasticity_source', 'default')})"

    rag_info = ""
    if demand_shift != 1.0 or elasticity_adj != 0.0 or cost_pressure != 1.0:
        factor_names = ", ".join(f["name"] for f in market_factors[:4]) or "n/a"
        rag_info = (
            f", Yếu tố thị trường [{factor_names}]: Nhu cầu x{demand_shift:.2f}, "
            f"ε thay đổi {elasticity_adj:+.2f}, sàn giá x{cost_pressure:.2f}"
        )

    tools_called.append({
        "name": "Revenue Optimizer (SciPy + Data-Driven Elasticity)",
        "args": f"base_price={flight['price']}, base_lf={flight['lf']}, capacity={flight['capacity']}, route={route}{rag_info}",
        "result": f"Giá tối ưu: {opt['optimal_price']:,.0f} VND ({opt['price_change_pct']:+.1f}%), LF dự kiến: {opt['optimal_lf']*100:.1f}%, Doanh thu: {opt['revenue_delta_pct']:+.1f}%{elasticity_info}"
    })

    if _current_trace:
        _current_trace.end_span("run_optimizer", {
            "optimal_price": opt["optimal_price"],
            "elasticity": opt.get("elasticity_used"),
            "demand_shift_factor": demand_shift,
            "elasticity_adjustment": elasticity_adj,
            "cost_pressure_factor": cost_pressure,
            "market_factors": [f["name"] for f in market_factors]
        })

    return {"optimizer_result": opt, "tools_called": tools_called}


def check_competitors(state: AgentState) -> dict:
    """Get competitor pricing data from CompetitorService. Supports aggregate lookups."""
    global _current_trace
    if _current_trace:
        _current_trace.start_span("check_competitors")

    flight = state.get("flight_data")
    tools_called = list(state.get("tools_called", []))
    target_date = state.get("target_date")
    parsed_route = state.get("parsed_route")

    # Determine routes to query
    routes_to_check = []
    if parsed_route:
        routes_to_check.append(parsed_route)
    elif flight and flight.get("is_aggregate") and flight.get("routes"):
        # Query top 3 routes for today
        routes_to_check = [r["route"] for r in flight["routes"][:3]]
    else:
        routes_to_check.append("SGN-HAN")

    comp_svc = CompetitorService()
    all_competitor_data = []

    for r in routes_to_check:
        base_price = 1500000.0
        if flight:
            if flight.get("is_aggregate"):
                route_info = next((item for item in flight.get("routes", []) if item["route"] == r), None)
                if route_info:
                    base_price = route_info["avg_price"]
                else:
                    base_price = flight.get("avg_price", 1500000.0)
            else:
                base_price = flight["price"]
                
        comp_data = comp_svc.get_prices(
            route=r,
            base_price=base_price,
            flight_date=target_date,
            fare_class="Eco",
        )
        
        for p in comp_data:
            all_competitor_data.append({
                "competitor": p.competitor,
                "route": p.route,
                "price": p.price,
                "status": "Lower" if p.price < base_price else "Higher" if p.price > base_price * 1.02 else "Similar",
                "source": p.source,
                "fare_class": p.fare_class,
                "flight_date": p.flight_date,
            })

    # Drop exact duplicates — per-flight lookups return the same route-level
    # competitor record once per VJ flight, flooding the summary and the LLM
    # context with identical entries
    seen_entries = set()
    deduped = []
    for p in all_competitor_data:
        key = (p["competitor"], p["route"], round(p["price"]), p.get("fare_class"), p.get("flight_date"))
        if key not in seen_entries:
            seen_entries.add(key)
            deduped.append(p)
    all_competitor_data = deduped

    summary_parts = []
    for r in routes_to_check:
        route_prices = [p for p in all_competitor_data if p["route"] == r]
        if route_prices:
            price_details = ", ".join([f"{p['competitor']}: {p['price']:,.0f} VND" for p in route_prices])
            summary_parts.append(f"{r} ({price_details})")
        else:
            summary_parts.append(f"{r} (Không có dữ liệu)")
            
    summary_str = "; ".join(summary_parts)

    tools_called.append({
        "name": "Competitor Price Check",
        "args": f"routes={routes_to_check}, date={target_date}",
        "result": f"Thu thập xong giá đối thủ ngày {target_date}: {summary_str}."
    })

    if _current_trace:
        _current_trace.end_span("check_competitors", {"competitors": len(all_competitor_data)})

    return {"competitor_data": all_competitor_data, "tools_called": tools_called}


def run_price_comparison(state: AgentState) -> dict:
    """Compare Vietjet fares against competitor fares and generate a markdown table."""
    global _current_trace
    if _current_trace:
        _current_trace.start_span("run_price_comparison")

    flight = state.get("flight_data")
    competitor_data = state.get("competitor_data")
    tools_called = list(state.get("tools_called", []))

    if not flight or not competitor_data:
        tools_called.append({
            "name": "Price Comparison Agent",
            "args": "None",
            "result": "Bỏ qua so sánh: Thiếu dữ liệu Vietjet hoặc đối thủ cạnh tranh."
        })
        if _current_trace:
            _current_trace.end_span("run_price_comparison", {"success": False})
        return {"tools_called": tools_called}

    # Group competitor prices by route
    comp_by_route = {}
    for c in competitor_data:
        r = c["route"]
        if r not in comp_by_route:
            comp_by_route[r] = []
        comp_by_route[r].append(c)

    comparison_results = []
    
    # 1. Process aggregate routes
    if flight.get("is_aggregate") and flight.get("routes"):
        for r_info in flight["routes"]:
            r = r_info["route"]
            vj_avg = r_info["avg_price"]
            
            comps = comp_by_route.get(r, [])
            if comps:
                for c in comps:
                    diff = vj_avg - c["price"]
                    diff_pct = (diff / c["price"]) * 100 if c["price"] > 0 else 0
                    comparison_results.append({
                        "route": r,
                        "vj_price": vj_avg,
                        "competitor": c["competitor"],
                        "comp_price": c["price"],
                        "diff": diff,
                        "diff_pct": diff_pct,
                        "status": "Rẻ hơn" if diff < 0 else "Đắt hơn" if diff > 0 else "Tương đương"
                    })
    # 2. Process single flight or route
    else:
        r = flight["route"]
        vj_price = flight["price"]
        comps = competitor_data
        for c in comps:
            if c["route"] == r:
                diff = vj_price - c["price"]
                diff_pct = (diff / c["price"]) * 100 if c["price"] > 0 else 0
                comparison_results.append({
                    "route": r,
                    "vj_price": vj_price,
                    "competitor": c["competitor"],
                    "comp_price": c["price"],
                    "diff": diff,
                    "diff_pct": diff_pct,
                    "status": "Rẻ hơn" if diff < 0 else "Đắt hơn" if diff > 0 else "Tương đương"
                })

    # Build Markdown Comparison Table
    table_lines = [
        "| Chặng bay | Giá vé Vietjet (VND) | Hãng đối thủ | Giá đối thủ (VND) | Chênh lệch (VND) | Tỷ lệ (%) | Nhận xét |",
        "| :--- | :---: | :--- | :---: | :---: | :---: | :---: |"
    ]
    for res in comparison_results:
        diff_str = f"{res['diff']:+,.0f}" if res['diff'] != 0 else "0"
        diff_pct_str = f"{res['diff_pct']:+.1f}%" if res['diff_pct'] != 0 else "0%"
        table_lines.append(
            f"| {res['route']} | {res['vj_price']:,.0f} | {res['competitor']} | {res['comp_price']:,.0f} | {diff_str} | {diff_pct_str} | {res['status']} |"
        )
    
    comparison_table = "\n".join(table_lines)
    result_dict = {
        "comparison_table": comparison_table,
        "results": comparison_results
    }

    tools_called.append({
        "name": "Price Comparison Agent",
        "args": f"results_count={len(comparison_results)}",
        "result": f"Đã lập bảng so sánh giá vé Vietjet với các đối thủ Bamboo/Vietnam Airlines."
    })

    if _current_trace:
        _current_trace.end_span("run_price_comparison", {"comparisons": len(comparison_results)})

    return {"price_comparison_result": result_dict, "tools_called": tools_called}


def run_price_adjustment(state: AgentState) -> dict:
    """
    Compare predicted Vietjet fares with competitor pricing and adjust predictions 
    to maximize revenue and remain competitive.
    """
    global _current_trace
    if _current_trace:
        _current_trace.start_span("run_price_adjustment")

    ml_pred = state.get("ml_prediction_result")
    competitor_data = state.get("competitor_data")
    tools_called = list(state.get("tools_called", []))

    if not ml_pred or not competitor_data:
        tools_called.append({
            "name": "Price Adjustment Agent",
            "args": "None",
            "result": "Bỏ qua điều chỉnh: Thiếu dữ liệu dự báo ML hoặc đối thủ cạnh tranh."
        })
        if _current_trace:
            _current_trace.end_span("run_price_adjustment", {"success": False})
        return {"tools_called": tools_called}

    # Group competitor prices by route
    comp_by_route = {}
    for c in competitor_data:
        r = c["route"]
        if r not in comp_by_route:
            comp_by_route[r] = []
        comp_by_route[r].append(c)

    adjusted_data = {}
    adjustments_made = 0

    # Business rules constants
    LCC_DISCOUNT_FACTOR = 0.90   # Target 10% cheaper than competitor average
    MIN_PRICE = 600000.0         # Cost floor
    MAX_PRICE = 5000000.0        # Price ceiling
    DELUXE_PROPORTION = 1.4      # Deluxe premium over Eco
    SKYBOSS_PROPORTION = 2.2     # SkyBoss premium over Eco

    # Case 1: Aggregate prediction
    if ml_pred.get("is_aggregate") == True:
        adjusted_preds = []
        for p in ml_pred.get("predictions", []):
            route = p["route"]
            original_classes = p["classes"]
            
            # Find average competitor price for this route
            comps = comp_by_route.get(route, [])
            comp_prices = [c["price"] for c in comps if c["price"] > 0]
            avg_comp_price = sum(comp_prices) / len(comp_prices) if comp_prices else None
            
            new_classes = original_classes.copy()
            if avg_comp_price:
                target_eco = avg_comp_price * LCC_DISCOUNT_FACTOR
                orig_eco = original_classes.get("Eco", 1000000.0)
                
                # If predicted is too high, discount it to target
                if orig_eco > avg_comp_price * 0.95:
                    new_eco = target_eco
                # If predicted is too low, raise it to avoid underpricing (but keep discount)
                elif orig_eco < avg_comp_price * 0.75:
                    new_eco = avg_comp_price * 0.80
                else:
                    new_eco = orig_eco
                    
                # Bound by cost floor/ceiling
                new_eco = max(MIN_PRICE, min(MAX_PRICE, new_eco))
                new_eco = round(new_eco, -3)
                
                new_classes["Eco"] = new_eco
                new_classes["Deluxe"] = round(new_eco * DELUXE_PROPORTION, -3)
                new_classes["SkyBoss"] = round(new_eco * SKYBOSS_PROPORTION, -3)
                # Prices were recomputed from fixed ratios — the ML ladder
                # calibration flag no longer describes these values
                new_classes.pop("ladder_adjusted", None)
                adjustments_made += 1
                
            adjusted_preds.append({
                "flight_no": p["flight_no"],
                "route": p["route"],
                "current_price": p["current_price"],
                "original_classes": original_classes,
                "classes": new_classes
            })
            
        adjusted_data = {
            "is_aggregate": True,
            "predictions": adjusted_preds
        }
        
        tools_called.append({
            "name": "Price Adjustment Agent",
            "args": f"predictions_count={len(adjusted_preds)}",
            "result": f"Đã đối sánh và điều chỉnh giá dự đoán cho {adjustments_made} chuyến bay dựa trên giá đối thủ."
        })

    # Case 2: Single flight prediction
    else:
        # For single flight, competitor_data belongs to the same route
        comp_prices = [c["price"] for c in competitor_data if c["price"] > 0]
        avg_comp_price = sum(comp_prices) / len(comp_prices) if comp_prices else None
        
        original_classes = ml_pred
        new_classes = original_classes.copy()
        reason = "Giữ nguyên giá dự báo của ML."
        
        if avg_comp_price:
            orig_eco = original_classes.get("Eco", 1000000.0)
            target_eco = avg_comp_price * LCC_DISCOUNT_FACTOR
            
            if orig_eco > avg_comp_price * 0.95:
                new_eco = target_eco
                reason = f"Hạ giá Eco dự kiến từ {orig_eco:,.0f} xuống {new_eco:,.0f} VND để cạnh tranh với đối thủ (giá TB đối thủ: {avg_comp_price:,.0f} VND)."
            elif orig_eco < avg_comp_price * 0.75:
                new_eco = avg_comp_price * 0.80
                reason = f"Tăng giá Eco dự kiến từ {orig_eco:,.0f} lên {new_eco:,.0f} VND để tránh bán quá rẻ so với đối thủ (giá TB đối thủ: {avg_comp_price:,.0f} VND)."
            else:
                new_eco = orig_eco
                reason = f"Giữ nguyên giá Eco dự báo {orig_eco:,.0f} VND vì đã nằm trong khoảng cạnh tranh tối ưu so với đối thủ (giá TB đối thủ: {avg_comp_price:,.0f} VND)."
                
            new_eco = max(MIN_PRICE, min(MAX_PRICE, new_eco))
            new_eco = round(new_eco, -3)
            
            new_classes["Eco"] = new_eco
            new_classes["Deluxe"] = round(new_eco * DELUXE_PROPORTION, -3)
            new_classes["SkyBoss"] = round(new_eco * SKYBOSS_PROPORTION, -3)
            # Prices were recomputed from fixed ratios — the ML ladder
            # calibration flag no longer describes these values
            new_classes.pop("ladder_adjusted", None)

        adjusted_data = new_classes
        adjusted_data["reason"] = reason

        tools_called.append({
            "name": "Price Adjustment Agent",
            "args": f"avg_competitor_price={avg_comp_price}",
            "result": f"Đã điều chỉnh giá dự đoán: Eco={new_classes['Eco']:,.0f} VND. Lý do: {reason}"
        })

    if _current_trace:
        _current_trace.end_span("run_price_adjustment", {"adjustments": adjustments_made or 1})

    return {"adjusted_prediction_result": adjusted_data, "tools_called": tools_called}


def query_rag(state: AgentState) -> dict:
    """Query Qdrant RAG for market intelligence."""
    global _current_trace
    if _current_trace:
        _current_trace.start_span("query_rag")

    flight = state.get("flight_data")
    tools_called = list(state.get("tools_called", []))
    
    route_filter = flight["route"] if (flight and not flight.get("is_aggregate")) else (state.get("search_term") or "")

    rag = QdrantRAGService()
    context = rag.query_market_context(state["user_query"], route_filter=route_filter)

    tools_called.append({
        "name": "Qdrant RAG Market Intelligence",
        "args": f"route={route_filter}, query='{state['user_query']}'",
        "result": context
    })

    if _current_trace:
        _current_trace.end_span("query_rag", {"context_length": len(context)})

    return {"rag_context": context, "tools_called": tools_called}


async def generate_report(state: AgentState) -> dict:
    """Generate structured pricing report via vLLM with JSON schema enforcement."""
    global _current_trace
    
    flight = state.get("flight_data")
    opt = state.get("optimizer_result")
    comp = state.get("competitor_data")
    rag = state.get("rag_context")
    ml_pred = state.get("ml_prediction_result")
    price_comp = state.get("price_comparison_result")
    adjusted_pred = state.get("adjusted_prediction_result")

    response_language = (
        "TIẾNG VIỆT (Vietnamese)" if detect_lang(state.get("user_query", "")) == "vi"
        else "ENGLISH (tiếng Anh)"
    )
    data_context = ""

    if state.get("error") or not flight:
        if rag and not state.get("error"):
            # Market-context question answered straight from RAG — no flight
            # data involved, the pricing-report prompt does not apply
            prompt = load_agent_prompt(
                "market_context_agent.md",
                user_query=state['user_query'],
                rag_context=rag,
                response_language=response_language
            )
        else:
            error_msg = state.get('error') or 'Không tìm thấy dữ liệu chuyến bay phù hợp trong cơ sở dữ liệu.'
            prompt = load_agent_prompt(
                "report_agent_error.md",
                user_query=state['user_query'],
                error_status=error_msg,
                response_language=response_language
            )
    else:
        # Build context sections based on available data (support aggregate)
        if flight.get("is_aggregate") == True:
            sections = [f"""THÔNG TIN TỔNG HỢP CÁC CHUYẾN BAY:
- Ngày bay: {flight.get('target_date', '2026-06-08')}
- Chặng bay yêu cầu: {flight.get('parsed_route', 'Tất cả')}
- Tổng số chuyến bay của Vietjet: {flight['total_flights']} chuyến
- Giá vé trung bình hiện tại của Vietjet: {flight['avg_price']:,.0f} VND
- Tỷ lệ lấp đầy (Load Factor) trung bình: {flight['avg_lf']*100:.1f}%"""]
            
            if flight.get("routes"):
                routes_str = "\n".join([f"  * {r['route']}: {r['flight_cnt']} chuyến, Giá TB: {r['avg_price']:,.0f} VND, LF: {r['avg_lf']*100:.1f}%" for r in flight["routes"]])
                sections.append(f"PHÂN BỔ THEO CHẶNG BAY:\n{routes_str}")
        else:
            sections = [f"""THÔNG TIN CHUYẾN BAY:
- Mã chuyến bay: {flight['flight_no']}
- Chặng bay: {flight['route']}
- Ngày bay: {flight['flight_date']}
- Giá vé hiện tại: {flight['price']:,.0f} VND
- Load Factor hiện tại: {flight['lf']*100:.1f}%
- Sức chứa: {flight['capacity']} ghế
- Hạng vé: {flight.get('fare_family', 'Eco')}"""]

        if ml_pred:
            if isinstance(ml_pred, dict) and ml_pred.get("is_aggregate") == True:
                pred_lines = []
                for pred in ml_pred.get("predictions", [])[:5]:
                    pred_lines.append(f"  * Chuyến {pred['flight_no']} ({pred['route']}): Eco={pred['classes'].get('Eco', 0):,.0f} VND, Deluxe={pred['classes'].get('Deluxe', 0):,.0f} VND, SkyBoss={pred['classes'].get('SkyBoss', 0):,.0f} VND")
                sections.append("DỰ BÁO GIÁ VÉ TỪ MÔ HÌNH MACHINE LEARNING (TOP 5):\n" + "\n".join(pred_lines))
            else:
                sections.append(f"""DỰ BÁO GIÁ VÉ TỪ MÔ HÌNH MACHINE LEARNING (XGBoost/Ensemble):
- Dự báo giá Eco: {ml_pred.get('Eco', 0):,.0f} VND
- Dự báo giá Deluxe: {ml_pred.get('Deluxe', 0):,.0f} VND
- Dự báo giá SkyBoss: {ml_pred.get('SkyBoss', 0):,.0f} VND
- Dự báo giá GDS (Business): {ml_pred.get('GDS', 0):,.0f} VND""")

        if opt:
            base_price = opt.get('base_price') or flight.get('price') or 1000000.0
            price_diff = opt['optimal_price'] - base_price
            diff_str = f"Tăng {price_diff:,.0f} VND" if price_diff > 0 else f"Giảm {abs(price_diff):,.0f} VND" if price_diff < 0 else "Giữ nguyên"
            
            # Format market factor adjustments if applied
            rag_details = ""
            if opt.get("demand_shift_factor", 1.0) != 1.0 or opt.get("elasticity_adjustment", 0.0) != 0.0:
                rag_details = f"\n- Điều chỉnh nhu cầu nền (yếu tố thị trường): x{opt['demand_shift_factor']:.2f}\n- Điều chỉnh độ co giãn cầu: {opt['elasticity_adjustment']:+.2f} (Độ co giãn gốc: {opt.get('original_elasticity', -1.2):.2f} -> Độ co giãn sử dụng: {opt['elasticity_used']:.2f})"
            if opt.get("cost_pressure_factor", 1.0) != 1.0:
                rag_details += f"\n- Áp lực chi phí khai thác: sàn giá tối thiểu nâng x{opt['cost_pressure_factor']:.2f}"
            if opt.get("market_factors"):
                type_labels = {"demand": "nhu cầu", "price_sensitivity": "độ nhạy giá", "cost": "chi phí"}
                factor_lines = "\n".join(
                    f"  * {f['name']} ({type_labels.get(f['type'], f['type'])} {'tăng' if f['direction'] > 0 else 'giảm'}, "
                    f"độ lớn {f['magnitude']:.1f}, tin cậy {f['confidence']:.1f})"
                    for f in opt["market_factors"][:5]
                )
                rag_details += f"\n- Các yếu tố thị trường được nhận diện:\n{factor_lines}"
                
            sections.append(f"""KẾT QUẢ TỐI ƯU HÓA DOANH THU (SciPy) VIETJET:
- Giá tối ưu khuyến nghị: {opt['optimal_price']:,.0f} VND ({diff_str}, {opt['price_change_pct']:+.1f}%){rag_details}
- Load Factor tối ưu dự kiến: {opt['optimal_lf']*100:.1f}%
- Tăng trưởng doanh thu dự kiến: {opt['revenue_delta_pct']:+.1f}%
- Đề xuất: {opt['recommendation']}""")

        if comp:
            sections.append(f"THÔNG TIN GIÁ ĐỐI THỦ:\n{json.dumps(comp[:10], ensure_ascii=False, indent=2)}")

        if price_comp and price_comp.get("results"):
            comp_lines = []
            for res in price_comp["results"][:5]:
                comp_lines.append(f"  * Chặng {res['route']}: VJ={res['vj_price']:,.0f} VND vs {res['competitor']}={res['comp_price']:,.0f} VND (VJ {res['status']})")
            sections.append("BẢNG SO SÁNH GIÁ ĐỐI THỦ:\n" + "\n".join(comp_lines))

        if adjusted_pred:
            if adjusted_pred.get("is_aggregate"):
                adj_lines = []
                for p in adjusted_pred.get("predictions", [])[:5]:
                    adj_lines.append(f"  * Chuyến {p['flight_no']} ({p['route']}): Eco={p['classes'].get('Eco', 0):,.0f} VND (Gốc ML: {p['original_classes'].get('Eco', 0):,.0f} VND)")
                sections.append("DỰ BÁO GIÁ ĐÃ ĐIỀU CHỈNH CẠNH TRANH (TOP 5):\n" + "\n".join(adj_lines))
            else:
                sections.append(f"""DỰ BÁO GIÁ ĐÃ ĐIỀU CHỈNH CẠNH TRANH:
- Giá Eco điều chỉnh: {adjusted_pred.get('Eco', 0):,.0f} VND (Gốc ML: {ml_pred.get('Eco', 0):,.0f} VND)
- Giá Deluxe điều chỉnh: {adjusted_pred.get('Deluxe', 0):,.0f} VND (Gốc ML: {ml_pred.get('Deluxe', 0):,.0f} VND)
- Giá SkyBoss điều chỉnh: {adjusted_pred.get('SkyBoss', 0):,.0f} VND (Gốc ML: {ml_pred.get('SkyBoss', 0):,.0f} VND)
- Lý do điều chỉnh: {adjusted_pred.get('reason', 'Định giá lại để tối ưu hóa tính cạnh tranh với đối thủ.')}""")

        if rag:
            sections.append(f"BỐI CẢNH THỊ TRƯỜNG (RAG từ Qdrant):\n{rag}")

        data_context = "\n\n".join(sections)

        prompt = load_agent_prompt(
            "report_agent_success.md",
            user_query=state['user_query'],
            data_context=data_context,
            response_language=response_language
        )

    thinking = "Đang phân tích dữ liệu và lập luận..."
    report = None
    message = ""

    try:
        start_time = time.time()
        content, reasoning, usage = await call_nim_llm(
            prompt=prompt,
            schema=PRICING_REPORT_SCHEMA if flight else None,
            temperature=0.3,
            max_tokens=3072
        )
        latency_ms = int((time.time() - start_time) * 1000)

        if not (content or "").strip():
            # Reasoning models can burn the whole token budget thinking and
            # return empty content — never surface an empty answer
            raise ValueError("LLM returned empty content (token budget likely consumed by reasoning)")

        thinking = reasoning if reasoning else "Agent đã hoàn thành phân tích dữ liệu."

        if flight:
            try:
                report = json.loads(content)
                report = _validate_summary(report, data_context, flight, ml_pred, adjusted_pred, state)
                message = _format_report_markdown(report, flight, ml_pred, price_comp, adjusted_pred, state)
            except json.JSONDecodeError:
                logger.warning("JSON parse failed, using raw LLM output")
                message = content
                report = {
                    "executive_summary": content,
                    "recommended_price": opt["optimal_price"] if opt else (flight.get("avg_price") if flight.get("is_aggregate") else flight.get("price", 0)),
                    "confidence_level": "medium",
                    "risk_factors": []
                }
        else:
            message = content
            report = None

        if _current_trace:
            model_name = await get_active_model_name()
            _current_trace.log_generation(
                name="pricing_report",
                model=model_name,
                input_text=prompt[:500],
                output_text=content[:500],
                usage={
                    "input": usage.get("prompt_tokens", 0),
                    "output": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0),
                    "latency_ms": latency_ms,
                }
            )

    except Exception as ex:
        logger.error(f"LLM call failed: {ex}")
        if flight:
            message = _fallback_report(flight, opt, comp, ml_pred=ml_pred, price_comparison=price_comp, adjusted_prediction=adjusted_pred, state=state)
            thinking = "Không thể kết nối vLLM. Sử dụng báo cáo dự phòng."
            report = {
                "executive_summary": "Báo cáo dự phòng - vLLM offline",
                "recommended_price": opt["optimal_price"] if opt else (flight.get("avg_price") if flight.get("is_aggregate") else flight.get("price", 0)),
                "confidence_level": "low",
                "risk_factors": ["vLLM service unavailable"]
            }
        else:
            detail = state.get('error') or str(ex) or 'Lỗi hệ thống hoặc vLLM offline.'
            message = f"Xin lỗi, tôi gặp lỗi khi xử lý câu hỏi của bạn. Chi tiết: {detail}"
            thinking = "vLLM offline hoặc gặp sự cố khi xử lý câu hỏi chung."
            report = None

    if _current_trace:
        _current_trace.end_span("generate_report", {"has_structured_output": report is not None})

    return {"thinking": thinking, "report": report, "message": message}


# ── Multi-Agent Supervisor Implementation ──────────────────────────────────────

SUPERVISOR_SCHEMA = {
    "type": "object",
    "properties": {
        "next_agent": {
            "type": "string",
            "enum": ["DatabaseAgent", "CompetitorAgent", "MLPredictionAgent", "OptimizerAgent", "RAGAgent", "PriceComparisonAgent", "PriceAdjustmentAgent", "generate_report"],
            "description": "Nhiệm vụ tiếp theo cần thực hiện."
        },
        "reasoning": {
            "type": "string",
            "description": "Lý do lựa chọn tác vụ tiếp theo dựa trên tiến trình hiện tại."
        }
    },
    "required": ["next_agent", "reasoning"]
}


def _supervisor_fallback_heuristic(state: AgentState, tools_called: list) -> str:
    """Rule-based routing fallback if the supervisor LLM call fails."""
    user_query = state["user_query"].lower()
    search_term = state.get("search_term", "")
    
    if search_term and not any("Query SQL Server" in t for t in tools_called):
        return "DatabaseAgent"
        
    if any(kw in user_query for kw in ["đối thủ", "competitor", "cạnh tranh", "hãng khác", "bamboo", "vietnam airlines"]) and not any("Competitor Price Check" in t for t in tools_called):
        return "CompetitorAgent"

    if state.get("comparison_intent") and any("Competitor Price Check" in t for t in tools_called) and not any("Price Comparison Agent" in t for t in tools_called):
        return "PriceComparisonAgent"
        
    if any(kw in user_query for kw in ["sự kiện", "event", "thời tiết", "weather", "bối cảnh"]) and "Qdrant RAG Market Intelligence" not in tools_called:
        return "RAGAgent"
        
    if state.get("flight_data") and not state.get("flight_data", {}).get("is_aggregate") and any(kw in user_query for kw in ["tối ưu", "optimize", "giá"]) and not any("Revenue Optimizer" in t for t in tools_called):
        return "OptimizerAgent"
        
    if state.get("flight_data") and not any("ML Model" in t for t in tools_called):
        return "MLPredictionAgent"

    if state.get("ml_prediction_result") and state.get("competitor_data") and not any("Price Adjustment Agent" in t for t in tools_called):
        return "PriceAdjustmentAgent"
        
    return "generate_report"


# Cache for the resolved vLLM model name — avoids an extra HTTP round-trip
# to /models before every single LLM call (supervisor loops + report)
_MODEL_NAME_TTL_S = 60.0
_model_name_cache: dict = {"name": None, "ts": 0.0}


async def get_active_model_name() -> str:
    """Fetch the active model name loaded in vLLM dynamically, fallback to LLM_MODEL."""
    now = time.time()
    if _model_name_cache["name"] and (now - _model_name_cache["ts"]) < _MODEL_NAME_TTL_S:
        return _model_name_cache["name"]
    try:
        headers = {}
        if VLLM_API_KEY:
            headers["Authorization"] = f"Bearer {VLLM_API_KEY}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{VLLM_URL}/models", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if "data" in data and len(data["data"]) > 0:
                    model_id = data["data"][0]["id"]
                    logger.info(f"Dynamically resolved active vLLM model: '{model_id}'")
                    _model_name_cache["name"] = model_id
                    _model_name_cache["ts"] = now
                    return model_id
    except Exception as e:
        logger.warning(f"Failed to dynamically query vLLM models list: {e}. Using fallback {LLM_MODEL}")
    # Cache the fallback too, so a down vLLM doesn't add a timeout before every call
    _model_name_cache["name"] = LLM_MODEL
    _model_name_cache["ts"] = now
    return LLM_MODEL


async def call_nim_llm(prompt: str, schema: dict | None = None, temperature: float = 0.3, max_tokens: int = 2048) -> tuple[str, str, dict]:
    """
    Call LLM via ChatNVIDIA if possible, fallback to direct httpx POST to vLLM.
    Returns (content, reasoning_content, usage_dict).
    """
    import httpx
    model_name = await get_active_model_name()
    api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("VLLM_API_KEY")
    
    # Try using langchain-nvidia-ai-endpoints ChatNVIDIA
    try:
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        
        kwargs = {
            "model": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if api_key:
            kwargs["nvidia_api_key"] = api_key
        if VLLM_URL:
            # Always honor the configured endpoint (self-hosted vLLM/NIM).
            # Without this, ChatNVIDIA defaults to the NVIDIA cloud API even
            # when a local vLLM is intended (e.g. VLLM_URL=http://localhost:8001/v1).
            kwargs["base_url"] = VLLM_URL.rstrip('/')
            
        chat_client = ChatNVIDIA(**kwargs)
        
        if schema:
            chat_client = chat_client.bind(response_format={"type": "json_schema", "json_schema": {"name": "output_schema", "strict": False, "schema": schema}})
            
        response = await chat_client.ainvoke(prompt)
        
        content = response.content
        reasoning = ""
        if hasattr(response, "additional_kwargs"):
            reasoning = response.additional_kwargs.get("reasoning_content") or ""
            
        # extract thinking if <think> in content
        if not reasoning and "<think>" in content:
            parts = content.split("</think>")
            reasoning = parts[0].replace("<think>", "").strip()
            content = parts[1].strip() if len(parts) > 1 else content
            
        usage = {}
        if hasattr(response, "response_metadata") and "token_usage" in response.response_metadata:
            usage = response.response_metadata["token_usage"]
            
        return content, reasoning, usage
        
    except Exception as e:
        logger.warning(f"Failed to call ChatNVIDIA: {e}. Falling back to direct httpx call to vLLM.")
        
    # Fallback to direct HTTP request
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "output_schema",
                "strict": False,
                "schema": schema
            }
        }
        
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{VLLM_URL}/chat/completions",
            json=payload,
            headers=headers
        )
        
    if response.status_code == 200:
        res_data = response.json()
        choice = res_data["choices"][0]["message"]
        content = choice.get("content") or ""
        reasoning = choice.get("reasoning_content") or ""
        usage = res_data.get("usage", {})
        
        if not reasoning and "<think>" in content:
            parts = content.split("</think>")
            reasoning = parts[0].replace("<think>", "").strip()
            content = parts[1].strip() if len(parts) > 1 else content
            
        return content, reasoning, usage
    else:
        raise Exception(f"vLLM API failed with status {response.status_code}: {response.text}")


async def run_supervisor_node(state: AgentState) -> dict:
    """Supervisor node: LLM decides which worker agent to invoke next."""
    global _current_trace
    
    iteration_count = state.get("iteration_count", 0) + 1
    if iteration_count > 6:
        return {"next_agent": "generate_report", "iteration_count": iteration_count}

    user_query = state["user_query"]
    search_term = state.get("search_term", "")
    flight_data = state.get("flight_data")
    competitor_data = state.get("competitor_data")
    optimizer_result = state.get("optimizer_result")
    ml_prediction_result = state.get("ml_prediction_result")
    price_comparison_result = state.get("price_comparison_result")
    rag_context = state.get("rag_context")
    error = state.get("error")
    tools_called = [t["name"] for t in state.get("tools_called", [])]
    adjusted_prediction_result = state.get("adjusted_prediction_result")

    # Intent detection
    user_query_lower = user_query.lower()
    is_comparison = state.get("comparison_intent") or any(kw in user_query_lower for kw in ["đối thủ", "so sánh", "bamboo", "vietnam airlines", "cạnh tranh", "compare", "competitor"])
    is_adjustment = any(kw in user_query_lower for kw in ["điều chỉnh", "cập nhật", "khuyến nghị giá", "adjust", "recommendation"])
    is_optimization = any(kw in user_query_lower for kw in ["tối ưu", "optimize", "doanh thu", "scipy"])

    # Rule-based routing guardrails
    next_agent_override = None
    reasoning_override = ""

    # Rule 0: Market-context question (festival/event/weather/news) with no
    # pricing intent → answer from RAG directly; the full pricing pipeline
    # (DB/ML/competitor) is irrelevant noise for these
    is_context_question = any(kw in user_query_lower for kw in [
        "lễ hội", "le hoi", "festival", "sự kiện", "su kien", "event",
        "thời tiết", "thoi tiet", "weather", "tin tức", "tin tuc", "bối cảnh", "boi canh"
    ])
    has_pricing_intent = any(kw in user_query_lower for kw in [
        "giá", "gia ve", " vé", "fare", "price", "dự báo", "du bao", "forecast", "predict",
        "doanh thu", "revenue", "tối ưu", "toi uu", "optimize", "so sánh", "so sanh", "compare",
        "đối thủ", "doi thu", "competitor", "load factor", "lấp đầy", "lap day"
    ])
    if is_context_question and not has_pricing_intent:
        if not rag_context and "Qdrant RAG Market Intelligence" not in tools_called:
            next_agent_override = "RAGAgent"
            reasoning_override = "Câu hỏi về bối cảnh thị trường (sự kiện/thời tiết) — truy vấn RAG để trả lời trực tiếp."
        else:
            next_agent_override = "generate_report"
            reasoning_override = "Đã có bối cảnh thị trường từ RAG, trả lời trực tiếp câu hỏi."

    # Rule 1: Always query database if a target is parsed but database query has not run
    elif search_term and not any("Query SQL Server" in t for t in tools_called):
        next_agent_override = "DatabaseAgent"
        reasoning_override = "Cần truy vấn dữ liệu chuyến bay trước từ cơ sở dữ liệu."

    # Rule 2: Handle Comparison Intent Workflow
    elif is_comparison:
        if not competitor_data and "Competitor Price Check" not in tools_called:
            next_agent_override = "CompetitorAgent"
            reasoning_override = "Yêu cầu so sánh giá đối thủ cần lấy dữ liệu giá của Bamboo/Vietnam Airlines."
        elif competitor_data and "Price Comparison Agent" not in tools_called:
            next_agent_override = "PriceComparisonAgent"
            reasoning_override = "Đã có dữ liệu đối thủ, cần tiến hành lập bảng so sánh giá vé."

    # Rule 3: Handle Price Adjustment Workflow
    elif is_adjustment:
        if not ml_prediction_result and not any("ML Model" in t for t in tools_called):
            next_agent_override = "MLPredictionAgent"
            reasoning_override = "Cần chạy dự báo giá từ mô hình Machine Learning làm cơ sở điều chỉnh."
        elif not competitor_data and "Competitor Price Check" not in tools_called:
            next_agent_override = "CompetitorAgent"
            reasoning_override = "Cần lấy thông tin giá của đối thủ để đối sánh cạnh tranh."
        elif not adjusted_prediction_result and "Price Adjustment Agent" not in tools_called:
            next_agent_override = "PriceAdjustmentAgent"
            reasoning_override = "Đã thu thập đủ dự báo ML và đối thủ, tiến hành điều chỉnh giá để tăng sức cạnh tranh."

    # Rule 4: Handle Optimization Workflow
    elif is_optimization:
        if flight_data and not flight_data.get("is_aggregate") and "Revenue Optimizer" not in tools_called:
            next_agent_override = "OptimizerAgent"
            reasoning_override = "Cần thực hiện tối ưu hóa doanh thu bằng SciPy cho chuyến bay cụ thể."

    if next_agent_override:
        logger.info(f"[Routing Override] Bypassing LLM routing. Next: {next_agent_override} | Reason: {reasoning_override}")
        return {
            "next_agent": next_agent_override,
            "iteration_count": iteration_count,
            "thinking": f"Supervisor (Deterministic Override): Chọn {next_agent_override} vì {reasoning_override}"
        }

    # Context about which agents have already run
    progress_details = []
    if flight_data:
        if flight_data.get("is_aggregate"):
            progress_details.append(f"- Đã lấy dữ liệu tổng hợp chuyến bay: {flight_data['total_flights']} chuyến ngày {flight_data.get('target_date')}")
        else:
            progress_details.append(f"- Chuyến bay tìm thấy trong CSDL: {flight_data['flight_no']} ({flight_data['route']})")
    elif any("Query SQL Server" in t for t in tools_called):
        progress_details.append("- Đã tra cứu CSDL cục bộ nhưng KHÔNG tìm thấy chuyến bay.")
        
    if competitor_data:
        progress_details.append(f"- Đã lấy thông tin giá đối thủ: {len(competitor_data)} entries.")
    if ml_prediction_result:
        progress_details.append("- Đã dự báo giá bằng mô hình Machine Learning.")
    if price_comparison_result:
        progress_details.append("- Đã thực hiện so sánh giá vé với đối thủ.")
    if optimizer_result:
        progress_details.append("- Đã chạy tối ưu hóa doanh thu (SciPy).")
    if rag_context:
        progress_details.append("- Đã truy vấn RAG ngữ cảnh thị trường.")
    if error:
        progress_details.append(f"- Lỗi/cảnh báo hệ thống: {error}")

    progress_str = "\n".join(progress_details) if progress_details else "- Chưa có công cụ nào được chạy."

    tools_called_str = ', '.join(tools_called) if tools_called else 'Chưa có'
    registered_agents = load_agent_registry()
    prompt = load_agent_prompt(
        "supervisor_agent.md",
        user_query=user_query,
        search_term=search_term,
        progress_str=progress_str,
        tools_called=tools_called_str,
        registered_agents=registered_agents
    )

    next_agent = "generate_report"
    reasoning = "Mặc định tạo báo cáo."
    
    try:
        content, reasoning_content, usage = await call_nim_llm(
            prompt=prompt,
            schema=SUPERVISOR_SCHEMA,
            temperature=0.1,
            max_tokens=512
        )
        
        # If content is empty but reasoning has text, try to extract JSON from it
        if not content and reasoning_content:
            logger.info(f"Supervisor empty content. Checking reasoning: {reasoning_content}")
            import re
            json_match = re.search(r"(\{.*\})", reasoning_content, re.DOTALL)
            if json_match:
                content = json_match.group(1)
                logger.info(f"Extracted JSON from reasoning: {content}")

        try:
            import re
            clean_content = content or ""
            # Trích xuất chuỗi JSON nếu nó được bọc trong markdown code blocks hoặc văn bản
            json_match = re.search(r"(\{.*\})", clean_content, re.DOTALL)
            if json_match:
                clean_content = json_match.group(1)
            
            decision = json.loads(clean_content)
            next_agent = decision.get("next_agent", "generate_report")
            reasoning = decision.get("reasoning", "")
        except (json.JSONDecodeError, TypeError):
            # Chỉ tìm từ khóa trong content sạch của mô hình (KHÔNG tìm trong reasoning trace để tránh nhận diện sai các thảo luận)
            text_to_search = content or ""
            for choice in ["DatabaseAgent", "CompetitorAgent", "MLPredictionAgent", "OptimizerAgent", "RAGAgent", "PriceComparisonAgent", "PriceAdjustmentAgent", "generate_report"]:
                if choice.lower() in text_to_search.lower():
                    next_agent = choice
                    break
    except Exception as ex:
        logger.error(f"Supervisor LLM call failed: {ex}")
        next_agent = _supervisor_fallback_heuristic(state, tools_called)

    logger.info(f"[Supervisor Decision] Next: {next_agent} | Reasoning: {reasoning} (Step {iteration_count})")
    
    return {
        "next_agent": next_agent,
        "iteration_count": iteration_count,
        "thinking": f"Supervisor: Chọn {next_agent} vì {reasoning}"
    }


def route_next(state: AgentState) -> str:
    """Route from supervisor to the selected agent."""
    next_agent = state.get("next_agent", "generate_report")
    mapping = {
        "DatabaseAgent": "query_database",
        "CompetitorAgent": "check_competitors",
        "MLPredictionAgent": "run_ml_prediction",
        "OptimizerAgent": "run_optimizer",
        "RAGAgent": "query_rag",
        "PriceComparisonAgent": "price_comparison",
        "PriceAdjustmentAgent": "price_adjustment",
        "generate_report": "generate_report"
    }
    return mapping.get(next_agent, "generate_report")


def route_after_db(state: AgentState) -> list[str]:
    """Route from query_database to worker agents in parallel, or fallback to supervisor."""
    if state.get("flight_data") and not state.get("error"):
        logger.info("[Workflow Router] Branching to parallel agents: MLPredictionAgent, CompetitorAgent, RAGAgent")
        return ["run_ml_prediction", "check_competitors", "query_rag"]
    logger.info("[Workflow Router] No flight data or error found. Routing back to supervisor.")
    return ["supervisor"]


def route_after_tools(state: AgentState) -> str:
    """Legacy helper."""
    return "generate_report"


# ── Helper Functions ──────────────────────────────────────────────────────────

# UI strings for the code-built report markdown, keyed by response language.
_L10N = {
    "vi": {
        "route_report_title": "### Báo cáo Tổng quan Chặng bay Vietjet {route} ngày {date}",
        "total_flights": "\n- **Tổng số chuyến bay:** {n} chuyến",
        "avg_price_route": "- **Giá vé trung bình thực tế Vietjet:** {x:,.0f} VND",
        "avg_lf": "- **Tỷ lệ lấp đầy trung bình:** {x:.1f}%",
        "network_report_title": "### Báo cáo Tổng quan Hoạt động Vietjet ngày {date}",
        "total_flights_today": "\n- **Tổng số chuyến bay hôm nay:** {n} chuyến",
        "avg_price_network": "- **Giá vé trung bình thực tế toàn mạng:** {x:,.0f} VND",
        "route_breakdown": "\n#### Phân bổ theo chặng bay hôm nay:",
        "route_line": "- **{route}:** {n} chuyến (Giá TB: {x:,.0f} VND, LF: {lf:.1f}%)",
        "more_routes": "*và {n} chặng bay khác...*",
        "competitor_table": "\n#### Bảng so sánh giá vé đối thủ (Bamboo/Vietnam Airlines)",
        "adj_table_title": "\n#### Đề xuất giá vé theo từng chuyến bay (đã điều chỉnh cạnh tranh)",
        "adj_table_header": "| Chuyến bay | Giá hiện tại (VND) | Eco đề xuất (VND) | Chênh lệch Eco vs giá đề xuất | Deluxe (VND) | SkyBoss (VND) |",
        "ml_table_title": "\n#### Dự báo giá vé theo từng chuyến bay (mô hình Machine Learning)",
        "ml_table_header": "| Chuyến bay | Giá hiện tại (VND) | Eco dự báo (VND) | Chênh lệch Eco vs giá dự báo | Deluxe (VND) | SkyBoss (VND) |",
        "more_flights": "*và {n} chuyến bay Vietjet khác...*",
        "note_delta": "\n*Cột chênh lệch so sánh giá thực tế hiện tại với giá mô hình đưa ra — không phải biến động giá thị trường.*",
        "note_anomaly": "*N/A / ⚠ ở cột giá hiện tại: chưa có dữ liệu booking hoặc giá thấp bất thường (< {floor:,.0f} VND) — đã loại khỏi giá trung bình và cột chênh lệch.*",
        "note_inversion": "*⚠ ở cuối dòng: hạng vé cao có giá dự báo thấp hơn hạng dưới (SkyBoss < Deluxe hoặc Deluxe < Eco) — cần kiểm tra lại dữ liệu đầu vào hoặc mô hình.*",
        "note_ladder": "*† Giá gốc mô hình dự báo thấp hơn hạng dưới, đã được nâng lên bậc tối thiểu (+5% so với hạng dưới) — cần kiểm tra lại mô hình dự báo hạng cao.*",
        "auto_summary_prefix": "(Tóm tắt AI đã bị loại vì chứa số liệu không khớp dữ liệu — dưới đây là tóm tắt tự động từ dữ liệu.)",
        "auto_summary_agg": "Theo dữ liệu: chênh lệch giữa giá hiện tại và giá Eco mô hình đưa ra từ {minpct:+.1f}% đến {maxpct:+.1f}% trên {m}/{n} chuyến có dữ liệu hợp lệ; giá vé trung bình thực tế {avg:,.0f} VND, tỷ lệ lấp đầy trung bình {lf:.1f}%.",
        "auto_summary_issues": "Lưu ý: {k} chuyến có cảnh báo dữ liệu (thiếu giá hoặc thang hạng vé bất thường).",
        "auto_summary_single": "Theo dữ liệu: giá hiện tại {price:,.0f} VND; giá Eco mô hình đưa ra {eco:,.0f} VND ({delta}).",
        "auto_summary_single_nopred": "Theo dữ liệu: giá hiện tại {price:,.0f} VND.",
        "system_facts_label": "**Đối chiếu hệ thống:**",
        "summary_agg": "\n**Tóm tắt phân tích:** {s}",
        "flight_report_title": "### Báo cáo Phân tích Chuyến bay Vietjet {no}",
        "adj_class_title": "\n#### Đề xuất giá vé theo hạng (đã điều chỉnh cạnh tranh)",
        "adj_class_header": "| Hạng vé | Giá đề xuất (VND) | Gốc dự báo ML (VND) | So với giá hiện tại ({cls}) |",
        "ml_class_title": "\n#### Dự báo giá vé theo hạng (mô hình Machine Learning)",
        "ml_class_header": "| Hạng vé | Giá dự báo (VND) | So với giá hiện tại ({cls}) |",
        "note_inversion_single": "\n*⚠ Hạng vé cao có giá thấp hơn hạng dưới — cần kiểm tra lại dữ liệu đầu vào hoặc mô hình.*",
        "adjust_reason": "\n- **Lý do điều chỉnh:** {s}",
        "summary": "\n**Tóm tắt:** {s}",
        "sec_assessment": "\n#### 1. Đánh giá hiện trạng\n{s}",
        "sec_competitor": "\n#### 2. Phân tích cạnh tranh\n{s}",
        "sec_math": "\n#### 3. Cơ sở toán học\n{s}",
        "sec_recommendation": "\n#### 4. Khuyến nghị",
        "rec_price": "- **Giá đề xuất:** **{x:,.0f} VND**",
        "rec_change": "- **Thay đổi:** {s}",
        "increase": "Tăng {x:,.0f} VND",
        "decrease": "Giảm {x:,.0f} VND",
        "unchanged": "Giữ nguyên",
        "confidence": "- **Độ tin cậy:** {s}",
        "confidence_map": {"high": "Cao", "medium": "Trung bình", "low": "Thấp"},
        "risk_title": "\n#### Yếu tố rủi ro",
        "action_title": "\n#### Hành động đề xuất",
        "delta_up": "▲ Tăng",
        "delta_down": "▼ Giảm",
        "delta_anomalous": "— (giá hiện tại bất thường)",
        "fallback_summary": "Không thể kết nối với máy chủ AI (vLLM) để nhận phân tích chi tiết. Dưới đây là dữ liệu tổng hợp trực tiếp từ các tác tử chuyên biệt (chế độ dự phòng).",
        "scipy_block": "\n\n#### Đề xuất tối ưu (SciPy)\n- **Giá tối ưu khuyến nghị:** **{p:,.0f} VND** ({pct:+.1f}%)\n- **Doanh thu dự kiến thay đổi:** {rev:+.1f}%\n- **Khuyến nghị:** {rec}",
        "keep_current": "Giữ nguyên giá hiện tại.",
    },
    "en": {
        "route_report_title": "### Vietjet Route Overview Report {route} — {date}",
        "total_flights": "\n- **Total flights:** {n}",
        "avg_price_route": "- **Average actual Vietjet fare:** {x:,.0f} VND",
        "avg_lf": "- **Average load factor:** {x:.1f}%",
        "network_report_title": "### Vietjet Network Overview Report — {date}",
        "total_flights_today": "\n- **Total flights today:** {n}",
        "avg_price_network": "- **Network-wide average actual fare:** {x:,.0f} VND",
        "route_breakdown": "\n#### Breakdown by route today:",
        "route_line": "- **{route}:** {n} flights (avg fare: {x:,.0f} VND, LF: {lf:.1f}%)",
        "more_routes": "*and {n} more routes...*",
        "competitor_table": "\n#### Competitor fare comparison (Bamboo/Vietnam Airlines)",
        "adj_table_title": "\n#### Recommended fares per flight (competition-adjusted)",
        "adj_table_header": "| Flight | Current price (VND) | Recommended Eco (VND) | Eco gap vs recommendation | Deluxe (VND) | SkyBoss (VND) |",
        "ml_table_title": "\n#### Forecast fares per flight (Machine Learning model)",
        "ml_table_header": "| Flight | Current price (VND) | Forecast Eco (VND) | Eco gap vs forecast | Deluxe (VND) | SkyBoss (VND) |",
        "more_flights": "*and {n} more Vietjet flights...*",
        "note_delta": "\n*The gap column compares the current actual price with the model's price — it is not market price movement.*",
        "note_anomaly": "*N/A / ⚠ in the current-price column: missing booking data or abnormally low price (< {floor:,.0f} VND) — excluded from averages and the gap column.*",
        "note_inversion": "*⚠ at end of row: a higher fare class is priced below a lower one (SkyBoss < Deluxe or Deluxe < Eco) — check the input data or the model.*",
        "note_ladder": "*† The model's raw forecast was below the lower class and was raised to the minimum ladder step (+5% over the class below) — review the premium-class model.*",
        "auto_summary_prefix": "(The AI summary was discarded because it contained figures not found in the data — below is an automatic data-derived summary.)",
        "auto_summary_agg": "Per the data: the gap between current prices and the model's Eco price ranges from {minpct:+.1f}% to {maxpct:+.1f}% across {m}/{n} flights with valid data; average actual fare {avg:,.0f} VND, average load factor {lf:.1f}%.",
        "auto_summary_issues": "Note: {k} flights carry data warnings (missing price or abnormal fare-class ladder).",
        "auto_summary_single": "Per the data: current price {price:,.0f} VND; the model's Eco price is {eco:,.0f} VND ({delta}).",
        "auto_summary_single_nopred": "Per the data: current price {price:,.0f} VND.",
        "system_facts_label": "**System cross-check:**",
        "summary_agg": "\n**Analysis summary:** {s}",
        "flight_report_title": "### Vietjet Flight Analysis Report {no}",
        "adj_class_title": "\n#### Recommended fares by class (competition-adjusted)",
        "adj_class_header": "| Fare class | Recommended (VND) | Original ML forecast (VND) | vs current price ({cls}) |",
        "ml_class_title": "\n#### Forecast fares by class (Machine Learning model)",
        "ml_class_header": "| Fare class | Forecast (VND) | vs current price ({cls}) |",
        "note_inversion_single": "\n*⚠ A higher fare class is priced below a lower one — check the input data or the model.*",
        "adjust_reason": "\n- **Adjustment reason:** {s}",
        "summary": "\n**Summary:** {s}",
        "sec_assessment": "\n#### 1. Current assessment\n{s}",
        "sec_competitor": "\n#### 2. Competitive analysis\n{s}",
        "sec_math": "\n#### 3. Mathematical basis\n{s}",
        "sec_recommendation": "\n#### 4. Recommendation",
        "rec_price": "- **Recommended price:** **{x:,.0f} VND**",
        "rec_change": "- **Change:** {s}",
        "increase": "Increase {x:,.0f} VND",
        "decrease": "Decrease {x:,.0f} VND",
        "unchanged": "Keep unchanged",
        "confidence": "- **Confidence:** {s}",
        "confidence_map": {"high": "High", "medium": "Medium", "low": "Low"},
        "risk_title": "\n#### Risk factors",
        "action_title": "\n#### Recommended actions",
        "delta_up": "▲ Up",
        "delta_down": "▼ Down",
        "delta_anomalous": "— (anomalous current price)",
        "fallback_summary": "Unable to reach the AI server (vLLM) for detailed analysis. Below is data aggregated directly from the specialist agents (fallback mode).",
        "scipy_block": "\n\n#### Optimization recommendation (SciPy)\n- **Recommended optimal price:** **{p:,.0f} VND** ({pct:+.1f}%)\n- **Expected revenue change:** {rev:+.1f}%\n- **Recommendation:** {rec}",
        "keep_current": "Keep the current price.",
    },
}


# Fares below this floor are treated as data anomalies (missing/partial booking
# data), not real prices: excluded from deltas and flagged in tables.
PRICE_FLOOR_VND = float(os.getenv("PRICE_FLOOR_VND", "100000"))


def _fmt_price_cell(price) -> str:
    """Format a price cell, flagging missing (0) and below-floor anomalies."""
    try:
        price = float(price or 0)
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        return "N/A"
    if price < PRICE_FLOOR_VND:
        return f"{price:,.0f} ⚠"
    return f"{price:,.0f}"


def _class_order_warning(classes: dict) -> bool:
    """True when a higher fare class is predicted cheaper than a lower one."""
    eco = classes.get("Eco") or 0
    deluxe = classes.get("Deluxe") or 0
    skyboss = classes.get("SkyBoss") or 0
    return bool((eco and deluxe and deluxe < eco) or (deluxe and skyboss and skyboss < deluxe))


def _fmt_delta(new_price: float, base_price: float, lang: str = "vi") -> str:
    """Format an absolute + percentage price delta cell for markdown tables."""
    L = _L10N.get(lang, _L10N["vi"])
    try:
        new_price = float(new_price or 0)
        base_price = float(base_price or 0)
    except (TypeError, ValueError):
        return "—"
    if base_price <= 0 or new_price <= 0:
        return "—"
    if base_price < PRICE_FLOOR_VND:
        # A % vs an anomalous base (e.g. 54,000 VND) would read +300% and mislead
        return L["delta_anomalous"]
    diff = new_price - base_price
    pct = diff / base_price * 100.0
    if abs(pct) < 0.05:
        return L["unchanged"]
    arrow = L["delta_up"] if diff > 0 else L["delta_down"]
    return f"{arrow} {abs(diff):,.0f} VND ({pct:+.1f}%)"


# ── Executive-summary validation ─────────────────────────────────────────────
# Small LLMs ignore the "only quote numbers from the data" prompt rule often
# enough that the summary can contradict the table above it. Every money-sized
# figure in the summary must trace back to the data given to the LLM; if any
# doesn't, the whole summary is replaced with a deterministic one built from
# the same data as the table.

_NUM_TOKEN_RE = re.compile(r"\d[\d.,]*\d|\d")


def _extract_numbers(text: str) -> set:
    """Parse numeric tokens ('1,190,000', '1.190.000', '28.6') into floats."""
    nums = set()
    for tok in _NUM_TOKEN_RE.findall(text or ""):
        t = tok
        if t.count(".") > 1:          # vi thousands: 1.190.000
            t = t.replace(".", "")
        if t.count(",") > 1:          # en thousands: 1,190,000
            t = t.replace(",", "")
        if "," in t and "." in t:     # 1,190,000.5 → en style
            t = t.replace(",", "")
        elif "," in t:
            head, tail = t.rsplit(",", 1)
            t = head + tail if len(tail) == 3 else head + "." + tail
        elif "." in t:
            head, tail = t.rsplit(".", 1)
            t = head + tail if len(tail) == 3 else t
        try:
            nums.add(float(t))
        except ValueError:
            pass
    return nums


def _summary_facts(flight: dict, ml_pred: dict | None, adjusted_pred: dict | None, state: dict | None) -> str:
    """Deterministic facts sentence built from the same data as the table."""
    lang = detect_lang(state.get("user_query", "")) if state else "vi"
    L = _L10N.get(lang, _L10N["vi"])
    parts = []

    preds = None
    for src in (adjusted_pred, ml_pred):
        if isinstance(src, dict) and src.get("predictions"):
            preds = src["predictions"]
            break

    if flight and flight.get("is_aggregate") and preds:
        pcts = []
        flagged = 0
        for p in preds:
            cur = float(p.get("current_price") or 0)
            classes = p.get("classes") or {}
            eco = float(classes.get("Eco") or 0)
            issue = False
            if cur >= PRICE_FLOOR_VND and eco > 0:
                pcts.append((eco - cur) / cur * 100.0)
            else:
                issue = True
            if _class_order_warning(classes) or classes.get("ladder_adjusted"):
                issue = True
            flagged += 1 if issue else 0
        if pcts:
            parts.append(L["auto_summary_agg"].format(
                minpct=min(pcts), maxpct=max(pcts), m=len(pcts), n=len(preds),
                avg=flight.get("avg_price") or 0, lf=(flight.get("avg_lf") or 0) * 100))
        if flagged:
            parts.append(L["auto_summary_issues"].format(k=flagged))
    elif flight and not flight.get("is_aggregate"):
        cur = float(flight.get("price") or 0)
        eco = None
        for src in (adjusted_pred, ml_pred):
            if isinstance(src, dict) and isinstance(src.get("Eco"), (int, float)):
                eco = float(src["Eco"])
                break
        if cur > 0 and eco:
            parts.append(L["auto_summary_single"].format(price=cur, eco=eco, delta=_fmt_delta(eco, cur, lang)))
        elif cur > 0:
            parts.append(L["auto_summary_single_nopred"].format(price=cur))

    return " ".join(parts).strip()


def _validate_summary(report: dict, data_context: str, flight: dict, ml_pred: dict | None, adjusted_pred: dict | None, state: dict | None) -> dict:
    """Discard the LLM summary when it quotes money figures absent from the data."""
    summary = (report or {}).get("executive_summary") or ""
    if not summary or not flight:
        return report

    allowed = _extract_numbers(data_context)
    # The data context truncates prediction lists to 5 — allow every figure
    # from the full lists the table is built from
    for src in (ml_pred, adjusted_pred):
        if not isinstance(src, dict):
            continue
        for p in src.get("predictions", []) or []:
            allowed.add(float(p.get("current_price") or 0))
            for v in (p.get("classes") or {}).values():
                if isinstance(v, (int, float)):
                    allowed.add(float(v))
        for cls in ("Eco", "Deluxe", "SkyBoss", "GDS"):
            v = src.get(cls)
            if isinstance(v, (int, float)):
                allowed.add(float(v))

    # Only money-sized figures are checked; small numbers (percentages,
    # counts, dates) are too ambiguous to trace reliably
    suspects = [
        n for n in _extract_numbers(summary)
        if n >= 10000 and not any(abs(n - a) <= max(1000.0, 0.01 * a) for a in allowed)
    ]
    lang = detect_lang(state.get("user_query", "")) if state else "vi"
    L = _L10N.get(lang, _L10N["vi"])
    facts = _summary_facts(flight, ml_pred, adjusted_pred, state)
    if suspects:
        logger.warning(f"Discarding LLM summary, figures not found in data: {sorted(suspects)[:5]}")
        report["executive_summary"] = (L["auto_summary_prefix"] + " " + facts).strip()
    elif facts and flight.get("is_aggregate"):
        # Valid figures can still be misread (e.g. quoting the current average
        # as the forecast) — ride the code-computed facts along as a cross-check
        report["executive_summary"] = f"{summary.rstrip()}\n\n{L['system_facts_label']} {facts}"
    return report


def _format_report_markdown(report: dict, flight: dict, ml_pred: dict | None = None, price_comparison: dict | None = None, adjusted_prediction: dict | None = None, state: dict | None = None) -> str:
    """Convert structured JSON report to display-ready markdown dynamically based on query intent."""
    query_lower = state.get("user_query", "").lower() if state else ""
    lang = detect_lang(state.get("user_query", "")) if state else "vi"
    L = _L10N.get(lang, _L10N["vi"])

    # Intent detection
    has_comp_intent = any(kw in query_lower for kw in ["đối thủ", "so sánh", "hãng khác", "bamboo", "vietnam airlines", "compare", "competitor"]) or (state and state.get("comparison_intent"))
    has_opt_intent = any(kw in query_lower for kw in ["tối ưu", "optimize", "doanh thu", "scipy"])
    has_ml_intent = any(kw in query_lower for kw in ["dự báo", "dự đoán", "predict", "forecast"])
    
    # If no specific intent is detected, show everything as fallback
    show_all = not (has_comp_intent or has_opt_intent or has_ml_intent)

    if flight.get("is_aggregate") == True:
        target_date = flight.get("target_date", "2026-06-08")
        parsed_route = flight.get("parsed_route")
        
        if parsed_route:
            parts = [L["route_report_title"].format(route=parsed_route, date=target_date)]
            parts.append(L["total_flights"].format(n=flight['total_flights']))
            parts.append(L["avg_price_route"].format(x=flight['avg_price']))
            parts.append(L["avg_lf"].format(x=flight['avg_lf'] * 100))
        else:
            parts = [L["network_report_title"].format(date=target_date)]
            parts.append(L["total_flights_today"].format(n=flight['total_flights']))
            parts.append(L["avg_price_network"].format(x=flight['avg_price']))
            parts.append(L["avg_lf"].format(x=flight['avg_lf'] * 100))

            if flight.get("routes"):
                parts.append(L["route_breakdown"])
                for r in flight["routes"][:5]:
                    parts.append(L["route_line"].format(route=r['route'], n=r['flight_cnt'], x=r['avg_price'], lf=r['avg_lf'] * 100))
                if len(flight["routes"]) > 5:
                    parts.append(L["more_routes"].format(n=len(flight['routes']) - 5))

        # Competitor pricing section
        if (show_all or has_comp_intent) and price_comparison and price_comparison.get("comparison_table"):
            parts.append(L["competitor_table"])
            parts.append(price_comparison["comparison_table"])

        # ML and price adjustments sections — comparison tables so the reader
        # sees exactly which flight, which fare class, and how much
        if show_all or has_ml_intent:
            agg_preds = None
            if adjusted_prediction and adjusted_prediction.get("predictions"):
                parts.append(L["adj_table_title"])
                parts.append(L["adj_table_header"])
                agg_preds = adjusted_prediction["predictions"]
            elif ml_pred and ml_pred.get("predictions"):
                parts.append(L["ml_table_title"])
                parts.append(L["ml_table_header"])
                agg_preds = ml_pred["predictions"]

            if agg_preds:
                parts.append("| :--- | ---: | ---: | :--- | ---: | ---: |")
                has_anomaly = False
                has_class_inversion = False
                has_ladder = False
                for p in agg_preds[:10]:
                    cur = p.get("current_price") or 0
                    classes = p["classes"]
                    eco = classes.get("Eco", 0)
                    if cur <= 0 or (0 < cur < PRICE_FLOOR_VND):
                        has_anomaly = True
                    inversion = _class_order_warning(classes)
                    has_class_inversion = has_class_inversion or inversion
                    ladder = classes.get("ladder_adjusted") or []
                    has_ladder = has_ladder or bool(ladder)
                    parts.append(
                        f"| **VJ{str(p['flight_no']).replace('VJ', '')}** | {_fmt_price_cell(cur)} | {eco:,.0f} | {_fmt_delta(eco, cur, lang)} "
                        f"| {classes.get('Deluxe', 0):,.0f}{'†' if 'Deluxe' in ladder else ''} "
                        f"| {classes.get('SkyBoss', 0):,.0f}{'†' if 'SkyBoss' in ladder else ''}{' ⚠' if inversion else ''} |"
                    )
                if len(agg_preds) > 10:
                    parts.append(L["more_flights"].format(n=len(agg_preds) - 10))
                parts.append(L["note_delta"])
                if has_anomaly:
                    parts.append(L["note_anomaly"].format(floor=PRICE_FLOOR_VND))
                if has_class_inversion:
                    parts.append(L["note_inversion"])
                if has_ladder:
                    parts.append(L["note_ladder"])

        if report and report.get("executive_summary"):
            parts.append(L["summary_agg"].format(s=report['executive_summary']))

        return "\n".join(parts)

    # Original single flight markdown formatter
    parts = [L["flight_report_title"].format(no=flight['flight_no'])]

    # Show prediction / adjustments if general query or prediction/competitor intent
    if show_all or has_ml_intent or has_comp_intent:
        current_price = flight.get("price") or 0
        current_class = flight.get("fare_family", "Eco")
        # Delta vs current price is only meaningful for the same fare class
        def _delta_for(cls: str, proposed: float) -> str:
            return _fmt_delta(proposed, current_price, lang) if cls == current_class else "—"

        if adjusted_prediction:
            parts.append(L["adj_class_title"])
            parts.append(L["adj_class_header"].format(cls=current_class))
            parts.append("| :--- | ---: | ---: | :--- |")
            for cls in ("Eco", "Deluxe", "SkyBoss"):
                proposed = adjusted_prediction.get(cls, 0)
                parts.append(
                    f"| **{cls}** | {proposed:,.0f} | {(ml_pred or {}).get(cls, 0):,.0f} | {_delta_for(cls, proposed)} |"
                )
            if _class_order_warning(adjusted_prediction):
                parts.append(L["note_inversion_single"])
            if adjusted_prediction.get('reason'):
                parts.append(L["adjust_reason"].format(s=adjusted_prediction.get('reason')))
        elif ml_pred:
            parts.append(L["ml_class_title"])
            parts.append(L["ml_class_header"].format(cls=current_class))
            parts.append("| :--- | ---: | :--- |")
            ladder = ml_pred.get("ladder_adjusted") or []
            for cls in ("Eco", "Deluxe", "SkyBoss", "GDS"):
                if cls in ml_pred:
                    label = "GDS (Business)" if cls == "GDS" else cls
                    parts.append(f"| **{label}** | {ml_pred.get(cls, 0):,.0f}{'†' if cls in ladder else ''} | {_delta_for(cls, ml_pred.get(cls, 0))} |")
            if _class_order_warning(ml_pred):
                parts.append(L["note_inversion_single"])
            if ladder:
                parts.append(L["note_ladder"])

    # Executive Summary (always show if available)
    if report.get("executive_summary"):
        parts.append(L["summary"].format(s=report['executive_summary']))

    # Detailed sections (only show if not empty and query matches intent or show_all)
    if (show_all or has_opt_intent) and report.get("current_assessment"):
        parts.append(L["sec_assessment"].format(s=report['current_assessment']))

    if (show_all or has_comp_intent) and report.get("competitor_analysis"):
        parts.append(L["sec_competitor"].format(s=report['competitor_analysis']))

    if (show_all or has_opt_intent) and report.get("mathematical_basis"):
        parts.append(L["sec_math"].format(s=report['mathematical_basis']))

    # Recommended Price & Recommendations
    if report.get("recommended_price"):
        confidence_text = L["confidence_map"].get(report.get("confidence_level", "medium"), L["confidence_map"]["medium"])
        parts.append(L["sec_recommendation"])
        parts.append(L["rec_price"].format(x=report['recommended_price']))
        if flight.get("price"):
            price_diff = report["recommended_price"] - flight["price"]
            diff_str = L["increase"].format(x=price_diff) if price_diff > 0 else L["decrease"].format(x=abs(price_diff)) if price_diff < 0 else L["unchanged"]
            if report.get("price_change_pct"):
                parts.append(L["rec_change"].format(s=f"{diff_str} ({report['price_change_pct']:+.1f}%)"))
            else:
                parts.append(L["rec_change"].format(s=diff_str))
        elif report.get("price_change_pct"):
            parts.append(L["rec_change"].format(s=f"{report['price_change_pct']:+.1f}%"))
        parts.append(L["confidence"].format(s=confidence_text))

    if (show_all or has_opt_intent) and report.get("risk_factors"):
        # Filter empty items
        risks = [r for r in report["risk_factors"] if r.strip()]
        if risks:
            parts.append(L["risk_title"])
            for r in risks:
                parts.append(f"- {r}")

    if (show_all or has_opt_intent) and report.get("action_items"):
        actions = [a for a in report["action_items"] if a.strip()]
        if actions:
            parts.append(L["action_title"])
            for a in actions:
                parts.append(f"- {a}")

    return "\n".join(parts)


def _fallback_report(flight: dict, opt: dict | None, comp: list | None, ml_pred: dict | None = None, price_comparison: dict | None = None, adjusted_prediction: dict | None = None, state: dict | None = None) -> str:
    """Fallback report when vLLM is offline."""
    lang = detect_lang(state.get("user_query", "")) if state else "vi"
    L = _L10N.get(lang, _L10N["vi"])
    dummy_report = {"executive_summary": L["fallback_summary"]}

    body = _format_report_markdown(dummy_report, flight, ml_pred, price_comparison, adjusted_prediction, state)

    if flight.get("is_aggregate") != True and opt:
        opt_price = opt['optimal_price'] if opt else flight['price']
        opt_pct = opt['price_change_pct'] if opt else 0
        opt_rev = opt['revenue_delta_pct'] if opt else 0
        body += L["scipy_block"].format(
            p=opt_price, pct=opt_pct, rev=opt_rev,
            rec=opt.get('recommendation', L["keep_current"])
        )

    return body


# ── Build the LangGraph ──────────────────────────────────────────────────────

def build_copilot_graph() -> StateGraph:
    """Construct the LangGraph state machine for the Revenue Copilot."""
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("parse_query", parse_query)
    graph.add_node("supervisor", run_supervisor_node)
    graph.add_node("query_database", query_database)
    graph.add_node("run_ml_prediction", run_ml_prediction)
    graph.add_node("run_optimizer", run_optimizer)
    graph.add_node("check_competitors", check_competitors)
    graph.add_node("price_comparison", run_price_comparison)
    graph.add_node("price_adjustment", run_price_adjustment)
    graph.add_node("query_rag", query_rag)
    graph.add_node("generate_report", generate_report)

    # Entry edge
    graph.add_edge(START, "parse_query")
    graph.add_edge("parse_query", "supervisor")

    # Supervisor decides who runs next
    graph.add_conditional_edges(
        "supervisor",
        route_next,
        {
            "query_database": "query_database",
            "check_competitors": "check_competitors",
            "run_ml_prediction": "run_ml_prediction",
            "run_optimizer": "run_optimizer",
            "query_rag": "query_rag",
            "price_comparison": "price_comparison",
            "price_adjustment": "price_adjustment",
            "generate_report": "generate_report"
        }
    )

    # Workers route back to the supervisor
    graph.add_conditional_edges(
        "query_database",
        route_after_db,
        {
            "run_ml_prediction": "run_ml_prediction",
            "check_competitors": "check_competitors",
            "query_rag": "query_rag",
            "supervisor": "supervisor"
        }
    )
    graph.add_edge("check_competitors", "supervisor")
    graph.add_edge("run_ml_prediction", "supervisor")
    graph.add_edge("run_optimizer", "supervisor")
    graph.add_edge("query_rag", "supervisor")
    graph.add_edge("price_comparison", "supervisor")
    graph.add_edge("price_adjustment", "supervisor")

    # Report ends the flow
    graph.add_edge("generate_report", END)

    return graph


# Compile once at module level
_copilot_graph = build_copilot_graph().compile()


# ── Public API ───────────────────────────────────────────────────────────────

# Multi-turn session context: remembers the last resolved target per chat session
# so follow-ups like "còn ngày mốt thì sao?" inherit route/flight from history.
_SESSION_CTX_TTL_S = 30 * 60
_MAX_SESSION_CTX = 500
_session_context: dict = {}


def _get_session_context(session_id) -> dict | None:
    if session_id is None:
        return None
    ctx = _session_context.get(session_id)
    if not ctx:
        return None
    if time.time() - ctx.get("ts", 0) > _SESSION_CTX_TTL_S:
        _session_context.pop(session_id, None)
        return None
    return ctx


def _update_session_context(session_id, result: dict) -> None:
    """Persist the resolved target of this turn for follow-up resolution."""
    if session_id is None:
        return
    flight = result.get("flight_data") or {}
    is_aggregate = bool(flight.get("is_aggregate"))
    parsed_route = result.get("parsed_route") or (flight.get("route") if not is_aggregate else None)
    flight_no = (flight.get("flight_no") or "") if not is_aggregate else ""
    target_date = result.get("target_date")
    search_term = result.get("search_term") or ""
    if not (parsed_route or flight_no or target_date or search_term):
        return
    if len(_session_context) >= _MAX_SESSION_CTX:
        oldest = min(_session_context, key=lambda k: _session_context[k].get("ts", 0))
        _session_context.pop(oldest, None)
    _session_context[session_id] = {
        "search_term": flight_no or search_term,
        "parsed_route": parsed_route,
        "target_date": target_date,
        "ts": time.time(),
    }


NODE_STATUS_LABELS = {
    "parse_query": "Đã phân tích câu hỏi (chặng bay / ngày / số hiệu).",
    "supervisor": "Supervisor đang điều phối tác tử...",
    "query_database": "Đã truy vấn dữ liệu chuyến bay từ SQL Server.",
    "run_ml_prediction": "Đã chạy dự báo giá vé bằng mô hình ML.",
    "run_optimizer": "Đã tối ưu hóa doanh thu (SciPy + yếu tố thị trường).",
    "check_competitors": "Đã thu thập giá vé đối thủ.",
    "query_rag": "Đã tra cứu bối cảnh thị trường (RAG).",
    "price_comparison": "Đã lập bảng so sánh giá với đối thủ.",
    "price_adjustment": "Đã điều chỉnh giá dự báo theo cạnh tranh.",
    "generate_report": "Đã tổng hợp báo cáo cuối cùng.",
}


def _blocked_response(reason: str, severity: str, user_query: str) -> dict:
    return {
        "thinking": "Guardrails: Input blocked.",
        "message": f"Cảnh báo: {reason}",
        "tools_called": [{"name": "Guardrails (Input)", "args": user_query[:100], "result": reason}],
        "report": None,
        "action": {"type": "none"},
        "guardrail": {"blocked": True, "reason": reason, "severity": severity},
    }


async def run_copilot_graph_stream(user_query: str, session_id=None):
    """
    Async generator executing the copilot pipeline with progress events:
      {"type": "status", "node": ..., "label": ...}  — pipeline progress
      {"type": "result", "data": {...}}              — final response (always last)

    Pipeline order (cheap before expensive):
      fast guardrails (regex/PII, no LLM) → multi-turn context seed → semantic
      cache → LLM input self-check (cache miss only) → LangGraph → merged
      output review → cache store.
    """
    # ── Layer 1a: Fast deterministic input guardrails (no LLM) ──
    guardrails = get_guardrails()
    input_check = await guardrails.check_input_fast(user_query)
    if input_check.blocked:
        yield {"type": "result", "data": _blocked_response(input_check.reason, input_check.severity, user_query)}
        return

    effective_query = input_check.modified_input or user_query

    # ── Multi-turn: resolve follow-up references from session context ──
    seed_state: dict = {}
    cache_query = effective_query
    session_ctx = _get_session_context(session_id)
    if session_ctx:
        raw_pre = parse_query({"user_query": effective_query})
        seeded_pre = parse_query({
            "user_query": effective_query,
            "search_term": session_ctx.get("search_term") or "",
            "parsed_route": session_ctx.get("parsed_route"),
            "target_date": session_ctx.get("target_date"),
        })
        slots = ("search_term", "parsed_route", "target_date")
        if any(seeded_pre.get(s) != raw_pre.get(s) for s in slots):
            seed_state = {s: session_ctx.get(s) for s in slots if session_ctx.get(s)}
            # Tag the cache key with the resolved context so a follow-up in one
            # session can never hit a cache entry resolved differently elsewhere
            ctx_parts = [str(seeded_pre.get(s)) for s in ("parsed_route", "target_date") if seeded_pre.get(s)]
            if not ctx_parts and seeded_pre.get("search_term"):
                ctx_parts = [str(seeded_pre["search_term"])]
            cache_query = f"{effective_query} [ngữ cảnh: {' '.join(ctx_parts)}]"
            logger.info(f"[Multi-turn] Session {session_id} seeded context: {seed_state}")

    # ── Layer 2: Semantic Cache Check ───────────────────────────
    cache = get_cache()
    parsed_route = seed_state.get("parsed_route") or cache._parse_route(cache_query)
    # cache.get performs a synchronous HTTP call to the NIM embedding service —
    # run it in a worker thread so the FastAPI event loop is not blocked
    cached = await asyncio.to_thread(cache.get, cache_query, parsed_route)
    if cached:
        logger.info(f"Cache hit for query: '{cache_query[:50]}...' (route: {parsed_route})")
        yield {"type": "result", "data": cached}
        return

    # ── Layer 1b: Semantic input guardrail (LLM) — cache miss only ──
    # Cache hits skip this by design: a cached query already passed it once.
    yield {"type": "status", "node": "guardrails", "label": "Đang kiểm tra an toàn nội dung (LLM self-check)..."}
    semantic_check = await guardrails.check_input_semantic(effective_query)
    if semantic_check.blocked:
        yield {"type": "result", "data": _blocked_response(semantic_check.reason, semantic_check.severity, user_query)}
        return

    # ── Layer 3: Execute LangGraph Pipeline ─────────────────────
    _current_trace_var.set(TraceContext(effective_query))

    initial_state = {
        "user_query": effective_query,
        "search_term": "",
        "flight_data": None,
        "optimizer_result": None,
        "competitor_data": None,
        "rag_context": None,
        "ml_prediction_result": None,
        "price_comparison_result": None,
        "adjusted_prediction_result": None,
        "tools_called": [],
        "thinking": "",
        "report": None,
        "message": "",
        "tools_needed": [],
        "iteration_count": 0,
        "error": None,
        "next_agent": "",
        "target_date": None,
        "parsed_route": None,
        "comparison_intent": False
    }
    initial_state.update(seed_state)

    try:
        # Stream node-level progress while accumulating the final state.
        # "updates" gives completed node names, "values" gives state snapshots.
        result = None
        async for mode, chunk in _copilot_graph.astream(initial_state, stream_mode=["updates", "values"]):
            if mode == "updates" and isinstance(chunk, dict):
                for node_name in chunk:
                    label = NODE_STATUS_LABELS.get(node_name)
                    if label:
                        yield {"type": "status", "node": node_name, "label": label}
            elif mode == "values":
                result = chunk

        if result is None:
            result = await _copilot_graph.ainvoke(initial_state)

        flight = result.get("flight_data") or {}
        opt = result.get("optimizer_result") or {}
        report = result.get("report") or {}

        recommended_price = float(report.get("recommended_price", 0)) if report else 0
        if recommended_price <= 0:
            adj_pred = result.get("adjusted_prediction_result")
            if adj_pred and not adj_pred.get("is_aggregate"):
                recommended_price = float(adj_pred.get("Eco", 0))
            elif opt:
                recommended_price = float(opt.get("optimal_price", flight.get("price", 0)))
            else:
                recommended_price = float(flight.get("price", 0))

        # If we don't have a valid flight, action type should be none
        if not flight or not flight.get("id") or flight.get("is_aggregate") == True:
            action = {"type": "none"}
        else:
            action = {
                "type": "apply_price",
                "flight_id": int(flight.get("id")),
                "flight_no": flight.get("flight_no", ""),
                "recommended_price": recommended_price,
                "recommended_lf": float(opt.get("optimal_lf", flight.get("lf", 0))) if opt else float(flight.get("lf", 0)),
            }

        response = {
            "thinking": result.get("thinking", ""),
            "message": result.get("message", ""),
            "tools_called": result.get("tools_called", []),
            "report": result.get("report"),
            "action": action
        }

        # ── Layer 4: Output Guardrails — single merged review pass ──
        # (check + PII filter in one Colang flow run instead of two)
        output_check, filtered_message = await guardrails.review_output(response)
        if output_check.blocked:
            response["message"] += f"\n\n**Guardrail Warning:** {output_check.reason}"
            response["guardrail"] = {"blocked": False, "warning": output_check.reason}
        else:
            response["message"] = filtered_message

        # Store in cache (embedding call runs off the event loop)
        route = flight.get("route", "")
        await asyncio.to_thread(cache.put, cache_query, response, route)

        # Remember this turn's resolved target for multi-turn follow-ups
        _update_session_context(session_id, result)

        if _current_trace_var.get() is not None:
            _current_trace_var.get().finalize(output={"flight_no": flight.get("flight_no"), "recommended_price": recommended_price})
        yield {"type": "result", "data": response}

    except Exception as e:
        logger.error(f"Copilot graph failed: {e}", exc_info=True)
        if _current_trace_var.get() is not None:
            _current_trace_var.get().finalize(output={"error": str(e)})
        raise
    finally:
        _current_trace_var.set(None)


async def run_copilot_graph(user_query: str, session_id=None) -> dict:
    """
    Backward-compatible entrypoint: consumes the streaming pipeline and returns
    only the final response dict (same format as before).
    """
    final = None
    async for event in run_copilot_graph_stream(user_query, session_id=session_id):
        if event.get("type") == "result":
            final = event.get("data")
    if final is None:
        raise RuntimeError("Copilot pipeline produced no result")
    return final
