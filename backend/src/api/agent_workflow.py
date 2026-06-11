"""
backend/src/api/agent_workflow.py
==================================
Multi-Agent Revenue Copilot logic (Async version).
Handles tool calling, direct DB queries, SciPy Optimizer, RAG, and vLLM.

Changes from original:
- Converted to fully async to fix asyncio.run() race condition with FastAPI's event loop
- Replaced MCP subprocess-per-request with direct DB calls (MCP server still available for external clients)
- Uses httpx (async) instead of requests (sync) for vLLM calls
"""
import os
import re
import json
import logging
import httpx
import sys

from backend.src.db.sqlserver import _connect
from backend.src.models.optimizer import optimize_flight
from backend.src.api.rag_service import QdrantRAGService

logger = logging.getLogger(__name__)

VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8001/v1")
if VLLM_URL.endswith("/"):
    VLLM_URL = VLLM_URL[:-1]
LLM_MODEL = os.getenv("LLM_MODEL", "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4")


def _query_db_direct(search_term_clean: str) -> dict | None:
    """
    Direct SQL Server database query — replaces MCP subprocess call for internal use.
    This eliminates ~200-500ms subprocess spawn overhead per request.
    MCP server (mcp_sqlserver.py) remains available for external clients via stdio transport.
    """
    try:
        conn = _connect()
        cursor = conn.cursor()
        
        # Find by flight_no or route
        cursor.execute("""
            SELECT TOP 1 
                id, flight_no, flight_date, str_Dep, str_Arr, route,
                mny_GL_Charges_Total AS price, LF_by_date AS lf, lng_Capacity AS capacity,
                fare_family, lead_time_days, booking_velocity_3d, Weekday, IsHoliday
            FROM flights
            WHERE UPPER(flight_no) = ? OR UPPER(route) = ?
            ORDER BY flight_date DESC
        """, (search_term_clean, search_term_clean))
        
        row = cursor.fetchone()
        if not row:
            # Fuzzy search fallback
            cursor.execute("""
                SELECT TOP 1 
                    id, flight_no, flight_date, str_Dep, str_Arr, route,
                    mny_GL_Charges_Total AS price, LF_by_date AS lf, lng_Capacity AS capacity,
                    fare_family, lead_time_days, booking_velocity_3d, Weekday, IsHoliday
                FROM flights
                WHERE UPPER(flight_no) LIKE ?
                ORDER BY flight_date DESC
            """, (f"%{search_term_clean}%",))
            row = cursor.fetchone()

        cols = [d[0] for d in cursor.description] if cursor.description else []
        cursor.close()
        conn.close()

        if row:
            return dict(zip(cols, row))
    except Exception as ex:
        logger.error(f"Direct database query failed: {ex}")
        
    return None


class RevenueCopilotAgent:
    def __init__(self):
        self.vllm_url = VLLM_URL
        self.model = LLM_MODEL
        self.rag = QdrantRAGService()

    def _query_db_for_flight(self, search_term: str) -> dict | None:
        """Query SQL Server for flight details using direct DB call."""
        search_term_clean = search_term.strip().upper()
        
        logger.info(f"Querying DB directly for '{search_term_clean}'")
        flight_data = _query_db_direct(search_term_clean)
        
        if flight_data:
            return flight_data
            
        logger.warning(f"Flight '{search_term_clean}' not found in database.")
        return None

    def _get_competitor_prices(self, route: str, base_price: float) -> list[dict]:
        """Simulate dynamic competitor prices based on route."""
        Bamboo_factor = 0.98 if "HAN" in route else 1.05
        VNA_factor = 1.15 if "SGN" in route else 1.25
        
        return [
            {"competitor": "Bamboo Airways", "price": round(base_price * Bamboo_factor, -3), "status": "Lower" if Bamboo_factor < 1.0 else "Higher"},
            {"competitor": "Vietnam Airlines", "price": round(base_price * VNA_factor, -3), "status": "Higher"}
        ]

    def _get_market_context(self, route: str, user_query: str) -> str:
        """Retrieve dynamic market context from Qdrant Vector DB (RAG)."""
        logger.info(f"Retrieving RAG context for route '{route}' and query '{user_query}'")
        return self.rag.query_market_context(user_query, route_filter=route)

    async def run_copilot_flow(self, user_query: str) -> dict:
        """
        Run the full copilot logic asynchronously.
        
        Previously this was synchronous and used asyncio.run() which created
        a new event loop conflicting with FastAPI's uvicorn loop. Now fully async.
        """
        tools_called = []
        
        # 1. Parse flight/route from query
        flight_match = re.search(r'(VJ\d{3,4})|(A\d{3})', user_query, re.IGNORECASE)
        
        search_term = None
        if flight_match:
            search_term = flight_match.group(0).upper()
        else:
            # Normalize common separators to hyphen for route parsing
            normalized_query = user_query.upper()
            normalized_query = re.sub(r'\b(?:ĐẾN|TO|ĐI|->|=>|AND|VÀ)\b', '-', normalized_query)
            normalized_query = re.sub(r'\s*-\s*', '-', normalized_query)
            route_match = re.search(r'\b([A-Z]{3})-([A-Z]{3})\b', normalized_query)
            
            if route_match:
                search_term = route_match.group(0)
            else:
                # Fallback: find any two 3-letter uppercase words
                iata_codes = re.findall(r'\b[A-Z]{3}\b', user_query.upper())
                if len(iata_codes) == 2:
                    search_term = f"{iata_codes[0]}-{iata_codes[1]}"

        # If it is not a flight query, handle it directly via LLM without calling database/optimizer
        if not search_term:
            prompt = f"""
Bạn là Vietjet AI Revenue Copilot - trợ lý định giá và tối ưu doanh thu thông minh của Vietjet Air.
Người dùng đã gửi câu hỏi: "{user_query}"

Nhiệm vụ:
Hãy trả lời người dùng một cách lịch sự, chuyên nghiệp bằng tiếng Việt.
- Giải thích rõ bạn là trợ lý tối ưu doanh thu chuyến bay và chặng bay.
- Hướng dẫn họ nhập số hiệu chuyến bay (ví dụ: VJ100) hoặc chặng bay (ví dụ: SGN-HAN) để bạn thực hiện phân tích và tối ưu hóa giá.
"""
            thinking = "Đang xử lý câu hỏi chung của người dùng..."
            message = "Không thể kết nối với dịch vụ vLLM để trả lời câu hỏi chung này."
            try:
                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1024
                }
                headers = {"Content-Type": "application/json"}
                api_key = os.getenv("VLLM_API_KEY") or os.getenv("NVIDIA_API_KEY")
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        f"{self.vllm_url}/chat/completions",
                        json=payload,
                        headers=headers
                    )
                    res_data = response.json()
                    message = res_data["choices"][0]["message"].get("content") or ""
                    thinking = "Đã hoàn thành câu trả lời cho câu hỏi chung."
            except Exception as ex:
                logger.error(f"Failed to connect to vLLM for general query: {ex}")
                message = "Xin lỗi, tôi gặp lỗi khi xử lý câu hỏi của bạn. Chi tiết: Lỗi hệ thống hoặc vLLM offline."

            return {
                "thinking": thinking,
                "message": message,
                "tools_called": [],
                "action": {"type": "none"}
            }

        # Execute DB Tool (direct — no MCP subprocess overhead)
        flight_info = self._query_db_for_flight(search_term)
        
        # Format dates if returned as datetime objects
        if flight_info and "flight_date" in flight_info and hasattr(flight_info["flight_date"], "isoformat"):
            flight_info["flight_date"] = flight_info["flight_date"].isoformat()

        if flight_info:
            tools_called.append({
                "name": "Query SQL Server (Direct DB)",
                "args": f"Search term: '{search_term}'",
                "result": f"Tìm thấy chuyến bay {flight_info['flight_no']} ({flight_info['route']}) ngày {flight_info['flight_date']}. Giá hiện tại: {flight_info['price']:,.0f} VND, Load Factor: {flight_info['lf']*100:.1f}%, Sức chứa: {flight_info['capacity']} ghế."
            })
        else:
            # Fallback mock flight if DB is completely empty
            flight_info = {
                "id": 9999,
                "flight_no": "VJ100",
                "flight_date": "2026-06-04",
                "str_Dep": "SGN",
                "str_Arr": "HAN",
                "route": "SGN-HAN",
                "price": 1450000.0,
                "lf": 0.72,
                "capacity": 230,
                "fare_family": "Eco"
            }
            tools_called.append({
                "name": "Generate Mock Flight Details (Fallback)",
                "args": f"Search term: '{search_term}'",
                "result": f"Tạo dữ liệu mô phỏng chuyến bay VJ100 (SGN-HAN). Giá hiện tại: 1,450,000 VND, LF: 72.0%."
            })

        # Execute Optimizer Tool
        opt_res = optimize_flight(
            base_price=flight_info["price"],
            base_lf=flight_info["lf"],
            capacity=flight_info["capacity"]
        )
        tools_called.append({
            "name": "Revenue Optimizer (SciPy)",
            "args": f"base_price={flight_info['price']}, base_lf={flight_info['lf']}, capacity={flight_info['capacity']}",
            "result": f"Giá đề xuất tối ưu: {opt_res['optimal_price']:,.0f} VND ({opt_res['price_change_pct']:+.1f}%), Load Factor dự kiến: {opt_res['optimal_lf']*100:.1f}%, Doanh thu thay đổi: {opt_res['revenue_delta_pct']:+.1f}%."
        })

        # Execute Competitor Tool
        comp_prices = self._get_competitor_prices(flight_info["route"], flight_info["price"])
        tools_called.append({
            "name": "Competitor Price Check",
            "args": f"route={flight_info['route']}, base_price={flight_info['price']}",
            "result": ", ".join([f"{c['competitor']}: {c['price']:,.0f} VND ({c['status']})" for c in comp_prices])
        })

        # Execute RAG Tool
        market_context = self._get_market_context(flight_info["route"], user_query)
        tools_called.append({
            "name": "Qdrant RAG Market Intelligence",
            "args": f"route={flight_info['route']}, query='{user_query}'",
            "result": market_context
        })

        # 2. Invoke vLLM for reasoning report in Vietnamese
        prompt = f"""
Bạn là một chuyên gia cao cấp về Quản trị doanh thu hàng không (Revenue Management Specialist) của Vietjet Air.
Hãy phân tích dữ liệu chuyến bay dưới đây và viết một báo cáo phân tích chiến lược định giá bằng tiếng Việt để trình bày cho Ban Giám đốc.

THÔNG TIN CHUYẾN BAY:
- Mã chuyến bay: {flight_info['flight_no']}
- Chặng bay: {flight_info['route']}
- Ngày bay: {flight_info['flight_date']}
- Giá vé hiện tại: {flight_info['price']:,.0f} VND
- Load Factor hiện tại: {flight_info['lf']*100:.1f}%
- Sức chứa: {flight_info['capacity']} ghế
- Hạng vé: {flight_info.get('fare_family', 'Eco')}

KẾT QUẢ TỐI ƯU HÓA DOANH THU (SciPy):
- Giá tối ưu khuyến nghị: {opt_res['optimal_price']:,.0f} VND ({opt_res['price_change_pct']:+.1f}% so với hiện tại)
- Load Factor tối ưu dự kiến: {opt_res['optimal_lf']*100:.1f}%
- Tăng trưởng doanh thu dự kiến: {opt_res['revenue_delta_pct']:+.1f}%
- Đề xuất hành động: {opt_res['recommendation']}

THÔNG TIN GIÁ ĐỐI THỦ CẠNH TRANH:
{json.dumps(comp_prices, ensure_ascii=False, indent=2)}

BỐI CẢNH THỊ TRƯỜNG & SỰ KIỆN (RAG từ Qdrant):
{market_context}

Yêu cầu báo cáo:
1. Đánh giá tình hình hiện tại của chuyến bay (về hiệu suất lấp đầy và giá).
2. Phân tích tác động của đối thủ cạnh tranh và bối cảnh thị trường (áp dụng các thông tin lấy được từ Qdrant RAG).
3. Giải thích cơ sở toán học/kinh tế đằng sau mức giá tối ưu được SciPy đề xuất (sử dụng độ co giãn của cầu - elasticity).
4. Đưa ra khuyến nghị cuối cùng có nên áp dụng giá đề xuất tối ưu này không.

Viết báo cáo chuyên nghiệp, mạch lạc, trực quan, có định dạng markdown rõ ràng.
"""
        
        thinking = "Đang phân tích dữ liệu chuyến bay và lập luận..."
        message = "Không thể kết nối với dịch vụ vLLM. Dưới đây là kết quả phân tích nhanh: ..."
        
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 2048
            }
            
            headers = {"Content-Type": "application/json"}
            api_key = os.getenv("VLLM_API_KEY") or os.getenv("NVIDIA_API_KEY")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            logger.info(f"Sending async request to vLLM at {self.vllm_url} for model {self.model}")
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.vllm_url}/chat/completions",
                    json=payload,
                    headers=headers
                )
            
                if response.status_code == 200:
                    res_data = response.json()
                    choice = res_data["choices"][0]["message"]
                    content = choice.get("content") or ""
                    
                    # Check for reasoning_content (DeepSeek-R1 API returns this field)
                    reasoning = choice.get("reasoning_content", "")
                    
                    # If reasoning not in separate field, extract from <think> tags if present
                    if not reasoning and "<think>" in content:
                        parts = content.split("</think>")
                        reasoning = parts[0].replace("<think>", "").strip()
                        content = parts[1].strip()
                    
                    thinking = reasoning if reasoning else "Agent đã hoàn thành suy luận logic chuỗi hành động dựa trên dữ liệu đầu vào."
                    message = content
                else:
                    logger.error(f"vLLM response error: {response.status_code} - {response.text}")
                    message = self._fallback_local_report(flight_info, opt_res, comp_prices)
                    thinking = "Dịch vụ vLLM trả về mã lỗi. Sử dụng công cụ báo cáo dự phòng nội bộ."
        except Exception as ex:
            logger.error(f"Failed to connect to vLLM: {ex}")
            message = self._fallback_local_report(flight_info, opt_res, comp_prices)
            thinking = "Không thể kết nối đến vLLM (hệ thống có thể đang offline hoặc chưa tải xong model). Chuyển sang báo cáo dự phòng."

        return {
            "thinking": thinking,
            "message": message,
            "tools_called": tools_called,
            "action": {
                "type": "apply_price",
                "flight_id": int(flight_info["id"]),
                "flight_no": flight_info["flight_no"],
                "recommended_price": float(opt_res["optimal_price"]),
                "recommended_lf": float(opt_res["optimal_lf"])
            }
        }

    def _fallback_local_report(self, flight_info: dict, opt_res: dict, comp_prices: list) -> str:
        """Fallback report in case vLLM is not running."""
        return f"""### Báo cáo Phân tích Định giá Chuyến bay {flight_info['flight_no']}
**Ngày thực hiện:** 2026-06-03 (Hệ thống tự động chạy chế độ Dự phòng)

#### 1. Đánh giá hiện trạng chuyến bay
*   **Chuyến bay:** {flight_info['flight_no']} | **Chặng bay:** {flight_info['route']} | **Hạng vé:** {flight_info.get('fare_family', 'Eco')}
*   **Load Factor hiện tại:** {flight_info['lf']*100:.1f}% (Số ghế đã bán: {int(flight_info['lf'] * flight_info['capacity'])} / {flight_info['capacity']})
*   **Giá vé hiện tại:** {flight_info['price']:,.0f} VND

#### 2. Phân tích đối thủ & Bối cảnh
*   **Bamboo Airways:** {comp_prices[0]['price']:,.0f} VND ({comp_prices[0]['status']})
*   **Vietnam Airlines:** {comp_prices[1]['price']:,.0f} VND ({comp_prices[1]['status']})
*   *Nhận xét:* Giá vé hiện tại của chúng ta đang có tính cạnh tranh cao.

#### 3. Đề xuất Tối ưu hóa Doanh thu (SciPy Optimizer)
*   **Khuyến nghị:** {opt_res['recommendation']}
*   **Giá tối ưu:** **{opt_res['optimal_price']:,.0f} VND** ({opt_res['price_change_pct']:+.1f}%)
*   **Doanh thu dự kiến tăng:** **{opt_res['revenue_delta_pct']:+.1f}%**
*   **Độ co giãn nhu cầu (Demand Elasticity):** Áp dụng mô hình co giãn tĩnh `-1.2`. Việc tăng/giảm giá sẽ thay đổi hệ số lấp đầy tương ứng để đạt cực đại doanh thu (Revenue Maximization).

#### 4. Khuyến nghị hành động
*   Đề xuất bấm nút **Áp dụng giá tối ưu** ở khung bên dưới để cập nhật trực tiếp mức giá `{opt_res['optimal_price']:,.0f} VND` lên hệ thống Core Booking.
"""
