"""
backend/src/api/guardrails.py
==============================
4-Layer Guardrails Pipeline for the Revenue Copilot.

Layers:
  1. Input validation — prompt injection detection, scope checking
  2. Tool-call gating — validates tool arguments before execution
  3. Output validation — price range checks, business rules
  4. Content filtering — PII detection, harmful content blocking

All checks are lightweight (no LLM calls) for minimal latency impact.
"""
import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ── Business Rule Constants ──────────────────────────────────────────────────
PRICE_ABSOLUTE_MIN = 50_000          # 50K VND
PRICE_ABSOLUTE_MAX = 50_000_000      # 50M VND
PRICE_CHANGE_MAX_PCT = 80.0          # Max 80% price change per action
LF_MIN = 0.0
LF_MAX = 1.0
MAX_QUERY_LENGTH = 2000


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    blocked: bool = False
    reason: str = ""
    severity: str = "info"  # info, warning, critical
    modified_input: Optional[str] = None  # if input was sanitized

    @staticmethod
    def ok() -> "GuardrailResult":
        return GuardrailResult(passed=True)

    @staticmethod
    def block(reason: str, severity: str = "critical") -> "GuardrailResult":
        return GuardrailResult(passed=False, blocked=True, reason=reason, severity=severity)

    @staticmethod
    def warn(reason: str) -> "GuardrailResult":
        return GuardrailResult(passed=True, blocked=False, reason=reason, severity="warning")


class GuardrailsPipeline:
    """
    Multi-layer guardrails for protecting the Revenue Copilot.
    
    Usage:
        guardrails = GuardrailsPipeline()
        
        # Before agent execution
        input_check = guardrails.check_input(user_query)
        if input_check.blocked:
            return {"error": input_check.reason}
        
        # After agent execution
        output_check = guardrails.check_output(response)
        if output_check.blocked:
            return {"error": output_check.reason}
    """

    # ── Injection patterns ────────────────────────────────────────
    INJECTION_PATTERNS = [
        # System prompt extraction attempts
        r"(?i)(ignore|forget|disregard)\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)",
        r"(?i)reveal\s+(your|the|system)\s+(prompt|instructions?|rules?)",
        r"(?i)what\s+(are|is)\s+your\s+(system\s+)?(prompt|instructions?|rules?)",
        r"(?i)(show|print|output|display|repeat)\s+(your\s+)?(system\s+)?(prompt|instructions?)",
        r"(?i)you\s+are\s+now\s+(a|an|in)\s+",
        # Role hijacking
        r"(?i)pretend\s+(to\s+be|you\s+are)\s+",
        r"(?i)act\s+as\s+(a|an|if)\s+",
        r"(?i)(jailbreak|dan\s+mode|developer\s+mode)",
        # Code injection
        r"(?i)(exec|eval|import\s+os|subprocess|system\().*",
        r"(?i)```\s*(python|bash|shell|sql)\s*\n.*(exec|eval|import|rm\s+-|drop\s+table)",
    ]

    # ── Out-of-scope patterns ─────────────────────────────────────
    OUT_OF_SCOPE_PATTERNS = [
        r"(?i)(viết|write|generate|create)\s+(code|script|program)",
        r"(?i)(hack|crack|bypass|exploit)\s+",
        r"(?i)((personal|customer|passenger|private)\s+(information|info|data|list))|((thông tin|dữ liệu|danh sách)\s+(cá nhân|riêng tư|khách hàng|hành khách))",
        r"(?i)(bomb|weapon|vũ khí|thuốc nổ|ma túy|drug)",
    ]

    # ── Airline domain keywords (for scope validation) ────────────
    DOMAIN_KEYWORDS = [
        "chuyến bay", "flight", "giá", "price", "vé", "ticket",
        "tuyến", "route", "hàng không", "airline", "sân bay", "airport",
        "load factor", "lf", "doanh thu", "revenue", "tối ưu", "optimize",
        "đặt chỗ", "booking", "ghế", "seat", "hành khách", "passenger",
        "vj", "vietjet", "sgn", "han", "dad", "cxr", "pqc", "hph",
        "bamboo", "vietnam airlines", "đối thủ", "competitor",
        "phân tích", "analysis", "báo cáo", "report",
        "fare", "eco", "deluxe", "skyboss", "business",
        "capacity", "elasticity", "demand", "cầu",
    ]

    # ── PII patterns ──────────────────────────────────────────────
    PII_PATTERNS = [
        (r"\b\d{9,12}\b", "phone_number"),  # Vietnamese phone numbers
        (r"\b[A-Z]\d{7}\b", "passport"),  # Passport number
        (r"\b\d{12}\b", "citizen_id"),  # CCCD
        (r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b", "email"),
        (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "credit_card"),
    ]

    def __init__(self):
        self._compiled_injection = [re.compile(p) for p in self.INJECTION_PATTERNS]
        self._compiled_oos = [re.compile(p) for p in self.OUT_OF_SCOPE_PATTERNS]
        self._compiled_pii = [(re.compile(p), name) for p, name in self.PII_PATTERNS]

    # ── Layer 1: Input Validation ─────────────────────────────────

    def check_input(self, query: str) -> GuardrailResult:
        """
        Validate user input before processing.
        Checks: length, injection, scope, PII.
        """
        if not query or not query.strip():
            return GuardrailResult.block("Query trống. Vui lòng nhập câu hỏi.", "warning")

        query = query.strip()

        # Length check
        if len(query) > MAX_QUERY_LENGTH:
            return GuardrailResult.block(
                f"Câu hỏi quá dài ({len(query)} ký tự, tối đa {MAX_QUERY_LENGTH}). Vui lòng rút gọn.",
                "warning"
            )

        # Injection detection
        for pattern in self._compiled_injection:
            if pattern.search(query):
                logger.warning(f"Prompt injection detected: '{query[:100]}...'")
                return GuardrailResult.block(
                    "Phát hiện yêu cầu không hợp lệ. Hệ thống chỉ hỗ trợ phân tích doanh thu hàng không.",
                    "critical"
                )

        # Out-of-scope detection
        for pattern in self._compiled_oos:
            if pattern.search(query):
                logger.info(f"Out-of-scope query detected: '{query[:100]}...'")
                return GuardrailResult.block(
                    "Câu hỏi nằm ngoài phạm vi hệ thống tối ưu doanh thu hàng không. "
                    "Vui lòng hỏi về giá vé, chuyến bay, tuyến bay, hoặc phân tích doanh thu.",
                    "warning"
                )

        # Scope relevance check (soft — warn but don't block)
        query_lower = query.lower()
        has_domain_keyword = any(kw in query_lower for kw in self.DOMAIN_KEYWORDS)
        if not has_domain_keyword and len(query) > 20:
            return GuardrailResult.warn(
                "Câu hỏi có thể nằm ngoài phạm vi hệ thống. Kết quả có thể không chính xác."
            )

        # PII detection — sanitize, don't block
        sanitized_query = query
        pii_found = []
        for pattern, pii_type in self._compiled_pii:
            matches = pattern.findall(sanitized_query)
            if matches:
                pii_found.append(pii_type)
                sanitized_query = pattern.sub(f"[{pii_type.upper()}_REDACTED]", sanitized_query)

        if pii_found:
            logger.warning(f"PII detected in query: {pii_found}")
            return GuardrailResult(
                passed=True, blocked=False,
                reason=f"Đã tự động ẩn thông tin cá nhân ({', '.join(pii_found)}) trong câu hỏi.",
                severity="warning",
                modified_input=sanitized_query,
            )

        return GuardrailResult.ok()

    # ── Layer 2: Tool-Call Gating ─────────────────────────────────

    def check_tool_call(self, tool_name: str, args: dict) -> GuardrailResult:
        """
        Validate tool call arguments before execution.
        Prevents obviously invalid or dangerous operations.
        """
        if tool_name == "update_flight_pricing" or tool_name == "apply_price":
            price = args.get("new_price") or args.get("applied_price") or args.get("recommended_price", 0)
            price = float(price) if price else 0

            if price < PRICE_ABSOLUTE_MIN:
                return GuardrailResult.block(
                    f"Giá đề xuất {price:,.0f} VND quá thấp (tối thiểu {PRICE_ABSOLUTE_MIN:,.0f} VND).",
                    "critical"
                )
            if price > PRICE_ABSOLUTE_MAX:
                return GuardrailResult.block(
                    f"Giá đề xuất {price:,.0f} VND vượt quá giới hạn ({PRICE_ABSOLUTE_MAX:,.0f} VND).",
                    "critical"
                )

            # LF validation
            lf = args.get("new_lf") or args.get("recommended_lf")
            if lf is not None:
                lf = float(lf)
                if lf < LF_MIN or lf > LF_MAX:
                    return GuardrailResult.block(
                        f"Load Factor {lf} nằm ngoài khoảng cho phép (0.0 - 1.0).",
                        "critical"
                    )

        if tool_name == "query_database":
            search_term = args.get("search_term", "")
            # SQL injection check (basic)
            sql_patterns = [r";\s*(DROP|DELETE|UPDATE|INSERT|ALTER)", r"--", r"UNION\s+SELECT"]
            for pattern in sql_patterns:
                if re.search(pattern, search_term, re.IGNORECASE):
                    return GuardrailResult.block(
                        "Phát hiện pattern SQL injection trong search term.",
                        "critical"
                    )

        return GuardrailResult.ok()

    # ── Layer 3: Output Validation ────────────────────────────────

    def check_output(self, response: dict) -> GuardrailResult:
        """
        Validate agent output before returning to user.
        Checks recommended price and other business constraints.
        """
        if not response:
            return GuardrailResult.ok()

        # Check action/recommendation
        action = response.get("action", {})
        recommended_price = action.get("recommended_price", 0)

        if recommended_price > 0:
            if recommended_price < PRICE_ABSOLUTE_MIN:
                return GuardrailResult.block(
                    f"Hệ thống phát hiện giá đề xuất ({recommended_price:,.0f} VND) quá thấp. "
                    f"Không áp dụng để bảo vệ doanh thu.",
                    "critical"
                )
            if recommended_price > PRICE_ABSOLUTE_MAX:
                return GuardrailResult.block(
                    f"Hệ thống phát hiện giá đề xuất ({recommended_price:,.0f} VND) vượt mức cho phép. "
                    f"Cần xem xét lại.",
                    "critical"
                )

        # Check structured report
        report = response.get("report", {})
        if report and isinstance(report, dict):
            report_price = report.get("recommended_price", 0)
            if report_price > 0:
                if report_price < PRICE_ABSOLUTE_MIN or report_price > PRICE_ABSOLUTE_MAX:
                    report["risk_factors"] = report.get("risk_factors", []) + [
                        f"Giá đề xuất {report_price:,.0f} VND nằm ngoài khoảng hợp lý. Cần review thủ công."
                    ]
                    report["confidence_level"] = "low"

        return GuardrailResult.ok()

    # ── Layer 4: Content Filtering ────────────────────────────────

    def filter_output_content(self, message: str) -> str:
        """
        Filter sensitive content from LLM output.
        Redacts any PII that may have leaked into the response.
        """
        filtered = message
        for pattern, pii_type in self._compiled_pii:
            filtered = pattern.sub(f"[{pii_type.upper()}_REDACTED]", filtered)
        return filtered


# Module-level singleton
_guardrails_instance: GuardrailsPipeline | None = None


def get_guardrails() -> GuardrailsPipeline:
    """Get or create the singleton guardrails instance."""
    global _guardrails_instance
    if _guardrails_instance is None:
        _guardrails_instance = GuardrailsPipeline()
    return _guardrails_instance
