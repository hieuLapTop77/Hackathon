# VJ Revenue Optimizer — Trình Tối Ưu Hóa Doanh Thu Hàng Không (Kiến Trúc Tác Tử Thông Minh)

Dự án áp dụng **Machine Learning** kết hợp **Fullstack Web Application** nhằm dự đoán giá vé máy bay và tối ưu hóa doanh thu của các chuyến bay thương mại. Hệ thống đã được nâng cấp toàn diện sang kiến trúc **Tác tử Thông minh (Agentic AI Copilot)** sử dụng **LangGraph**, tích hợp **Vector DB (Qdrant)**, **3-Layer Semantic Caching**, **4-Layer Safety Guardrails** và giám sát thời gian thực với **Langfuse Observability**.

---

## Kiến Trúc Hệ Thống Nâng Cấp (Architecture Overview)

Hệ thống bao gồm 3 thành phần cốt lõi:
1. **ML Training Pipeline (`kaggle/`)**: Quá trình ETL, xử lý sạch dữ liệu quy nạp (Inductive Imputation), xây dựng đặc trưng nâng cao (30 features), huấn luyện song song 6 mô hình ML và tối ưu hóa trọng số mô hình kết hợp (Weighted Ensemble).
2. **Backend API (`backend/`)**: FastAPI server chịu trách nhiệm tải dữ liệu chuyến bay từ SQL Server, thực hiện suy luận (inference) thời gian thực thông qua các mô hình ML, chạy bộ tối ưu doanh thu chuyến bay (Revenue Optimizer) sử dụng Scipy, và vận hành **LangGraph Copilot Agent**.
3. **Frontend Dashboard (`frontend/`)**: Giao diện React người dùng hiện đại xây dựng trên Vite, thiết kế theo tone màu đỏ chủ đạo cao cấp của **Vietjet Air**, hỗ trợ xem danh sách chuyến bay, What-if simulation trực quan, và tích hợp khung chat trao đổi trực tiếp với Copilot Agent để tối ưu hóa giá vé.

```mermaid
flowchart TD
    User([Người dùng / Nhà quản trị]) <-->|Chat / Thao tác UI| FE[Frontend Dashboard: React + Vite]
    FE <-->|REST API / JWT Auth| BE[Backend API: FastAPI]
    
    subgraph Engine Tác Tử (LangGraph Copilot Agent)
        BE <-->|1. Check Cache / Save State| Cache[(3-Layer Semantic Cache: Qdrant + RAM)]
        BE -->|2. Input Guardrails| Guard[4-Layer Safety Guardrails]
        Guard -->|3. Run State Machine| Graph[LangGraph State Machine]
        
        subgraph Các Node Tác Vụ
            Graph --> NodeParse[parse_query]
            Graph --> NodeSup[supervisor]
            Graph --> NodeDB[query_database]
            Graph --> NodeML[run_ml_prediction]
            Graph --> NodeOpt[run_optimizer]
            Graph --> NodeComp[check_competitors]
            Graph --> NodeRAG[query_rag]
            Graph --> NodeReport[generate_report]
        end
        
        NodeDB <-->|Direct Async Connection| DB[(SQL Server Database)]
        NodeML -->|Model inference| Models[Outputs: XGBoost / LightGBM / RF]
        NodeOpt -->|SciPy Bounded Optimization| SciPy[Constant-Elasticity Model]
        NodeRAG <-->|Hybrid Search + Re-rank| Qdrant[(Qdrant Vector DB: Market Intelligence)]
        
        NodeSup <-->|Inference / Chat Completion| LLM[Self-Hosted vLLM: NVIDIA Nemotron NIM]
        NodeReport -->|Structured Output Schema| LLM
    end
    
    BE -->|Traces & Generations metrics| LF[Langfuse Observability Platform]
```

---

## Các Công Nghệ & Giải Pháp Cốt Lõi Mới

### 1. LangGraph State Machine (Supervisor-Worker Pattern)
Thay vì luồng xử lý tuyến tính cứng nhắc (hard-coded linear flow), hệ thống sử dụng **LangGraph** để xây dựng một máy trạng thái (state machine) linh hoạt:
*   **Supervisor Node:** Đóng vai trò bộ não điều phối, gọi mô hình ngôn ngữ lớn (LLM) để quyết định Worker Node nào sẽ được thực thi tiếp theo dựa trên câu hỏi của người dùng và trạng thái hiện tại.
*   **Worker Nodes độc lập:** Phục vụ các tác vụ chuyên biệt: `parse_query` (trích xuất thông tin hành trình/ngày bay), `query_database` (truy vấn DB), `run_ml_prediction` (suy luận giá vé ML), `run_optimizer` (tối ưu hóa doanh thu), `check_competitors` (quét giá đối thủ), `query_rag` (tìm kiếm bối cảnh thị trường), và `generate_report` (xuất báo cáo định dạng JSON có cấu trúc nghiêm ngặt).

### 2. 3-Layer Semantic Caching (Bộ Nhớ Đệm Ngữ Nghĩa 3 Lớp)
Giúp giảm từ 70-90% chi phí gọi mô hình ngôn ngữ lớn (LLM) và mang lại tốc độ phản hồi cực nhanh dưới 5ms:
*   **Layer 1 (Exact Hash Match):** Dùng thuật toán SHA-256 mã hóa câu hỏi để so khớp nhanh trong bộ nhớ RAM tạm thời với thời gian sống TTL (mặc định 2 giờ).
*   **Layer 2 (Semantic Similarity Match):** Sử dụng mô hình `SentenceTransformer` tạo vector embedding cho câu hỏi và truy vấn độ tương đồng cosine trong **Qdrant Vector DB** với ngưỡng tin cậy cao `threshold >= 0.92`. Nếu trùng khớp ý định, hệ thống trả về kết quả cũ ngay lập tức.
*   **Layer 3 (Cache Miss):** Khi cả hai tầng cache đều bỏ lỡ, hệ thống mới thực thi luồng tác tử đầy đủ qua LLM, sau đó tự động lưu kết quả mới kèm embedding vào cả hai tầng cache.
*   **Targeted Invalidation:** Khi người quản trị thực hiện áp dụng giá mới cho một chuyến bay (`/api/flights/{id}/apply`), hệ thống sẽ tự động quét và xóa bỏ (invalidate) các bản ghi cache liên quan đến tuyến bay đó nhằm đảm bảo dữ liệu tư vấn luôn cập nhật.

### 3. 4-Layer Safety Guardrails (Hàng Rào Bảo Vệ 4 Lớp)
Đảm bảo tác tử hoạt động an toàn, chống rò rỉ dữ liệu và ngăn chặn các hành vi phá hoại:
*   **Layer 1 (Input Guardrail):** Kiểm tra độ dài, phát hiện các mẫu prompt injection thông dụng, lọc các câu hỏi ngoài phạm vi (out-of-scope) và tự động ẩn (redact) thông tin cá nhân (PII - điện thoại, passport, email).
*   **Layer 2 (Tool-Call Gating):** Kiểm tra tham số đầu vào của các công cụ trước khi chạy thực tế (ví dụ: phát hiện SQL injection trong từ khóa tìm kiếm, kiểm tra giá đề xuất thay đổi có nằm trong khoảng kinh doanh an toàn `50,000` - `50,000,000` VND hay không).
*   **Layer 3 (Output Guardrail):** Xác minh kết quả trả về của Agent trước khi hiển thị cho người dùng, điều chỉnh mức độ tin cậy và tự động gắn cờ cảnh báo rủi ro nếu mức giá khuyến nghị vi phạm quy tắc thương mại.
*   **Layer 4 (Content Filtering):** Tự động ẩn các thông tin nhạy cảm vô tình bị lọt vào thông điệp phản hồi của LLM.

### 4. Langfuse Observability & Tracing
Tích hợp sâu nền tảng **Langfuse** giúp giám sát chi tiết từng bước đi của tác tử:
*   **Span & Trace:** Theo dõi thời gian thực hiện của từng Node trong LangGraph.
*   **Generation Logging:** Ghi nhận prompt đầu vào, văn bản đầu ra, model sử dụng, và số lượng token tiêu thụ để tối ưu hóa chi phí.
*   **Debugging:** Dễ dàng phát hiện các lỗi kết nối vLLM, lỗi logic của Supervisor hoặc lỗi dữ liệu đầu vào.

### 5. Tối ưu hóa Database (Direct Async DB Connections)
*   **Loại bỏ MCP Subprocess:** Phiên bản cũ gọi các công cụ database thông qua một tiến trình con (subprocess) chạy script MCP Python, tạo ra độ trễ 200-500ms cho mỗi yêu cầu. Phiên bản mới thực hiện kết nối bất đồng bộ (`asyncio` + direct db connection) trực tiếp vào SQL Server, giúp giảm thiểu độ trễ xuống gần như bằng 0.
*   *Lưu ý:* File máy chủ MCP (`backend/src/db/mcp_sqlserver.py`) vẫn được giữ lại để phục vụ các máy khách ngoài (external clients) kết nối qua giao thức stdio tiêu chuẩn.

---

## Cấu Trúc Dự Án Cập Nhật (Project Structure)

```text
├── kaggle/                       # ML TRAINING PIPELINE (Chạy huấn luyện và lưu mô hình)
│   ├── scripts/
│   │   └── run_pipeline.py       # Pipeline huấn luyện 6 mô hình ML
│   └── src/
│       ├── preprocessor.py       # Điền khuyết quy nạp (Inductive Imputation) & Feature Engineering
│       └── trainer.py            # Tối ưu hóa trọng số kết hợp (Ensemble Weights) bằng Nelder-Mead
│
├── backend/                      # FASTAPI BACKEND SERVER (Phục vụ API & tính toán tối ưu)
│   ├── config.py                 # Cấu hình môi trường (Directories, DB, API Keys)
│   ├── src/
│   │   ├── db/
│   │   │   ├── sqlserver.py      # Kết nối trực tiếp SQL Server
│   │   │   ├── mcp_sqlserver.py  # MCP Server cho external clients (stdio transport)
│   │   │   └── mcp_sqlserver_raw.py
│   │   │
│   │   ├── models/
│   │   │   ├── trainer.py        # Module hỗ trợ load các mô hình ML (.pkl)
│   │   │   └── optimizer.py      # Bộ tối ưu doanh thu (Constant-Elasticity Demand Model)
│   │   │
│   │   └── api/
│   │       ├── main.py           # Khởi tạo FastAPI & mount các endpoints
│   │       ├── agent_graph.py    # LangGraph State Machine (supervisor, nodes, Langfuse integration)
│   │       ├── agent_workflow.py # Copilot Agent phiên bản tuần tự (Fallback)
│   │       ├── semantic_cache.py # Bộ nhớ đệm 3 lớp (RAM + Qdrant similarity)
│   │       ├── guardrails.py     # Hàng rào bảo vệ an toàn 4 lớp
│   │       ├── rag_service.py    # Qdrant RAG Service (Hybrid Search + Cross-Encoder Re-ranking)
│   │       ├── competitor_service.py # Quét và đối sánh giá đối thủ
│   │       ├── schemas.py        # Cấu trúc dữ liệu API Pydantic
│   │       ├── auth.py           # Xác thực JWT Token & Rate Limit
│   │       │
│   │       └── routers/          # Thư mục chứa các router endpoints cô lập
│   │           ├── agent.py      # Endpoints chat tác tử (/agent/chat, /agent/status, /agent/sessions)
│   │           ├── rag.py        # Endpoint refresh dữ liệu thị trường (/rag/refresh)
│   │           ├── flights.py    # API quản lý chuyến bay và áp dụng giá vé
│   │           ├── predictions.py# API suy luận giá vé máy bay
│   │           ├── optimization.py# API tối ưu giá vé bằng SciPy
│   │           ├── dashboard.py  # API thống kê tổng quan
│   │           ├── health.py     # API kiểm tra trạng thái hệ thống
│   │           └── db_ops.py     # API seed dữ liệu ban đầu
│   │
│   └── requirements.txt          # Thư viện cho Backend (FastAPI, LangGraph, Qdrant, Langfuse...)
│
├── frontend/                     # REACT/VITE FRONTEND (Giao diện bảng điều khiển & Chat Agent)
├── outputs/                      # KẾT QUẢ HUẤN LUYỆN (Models lưu dưới dạng .pkl & biểu đồ)
├── docker-compose.gpu.yml        # Điều phối Container trên GPU Server (H200)
├── Dockerfile                    # Dockerfile đa tầng (Multi-stage) cho Backend & Frontend
└── nginx.conf                    # Cấu hình Nginx phục vụ Reverse Proxy cho API và Frontend
```

---

## Hướng Dẫn Thiết Lập Biến Môi Trường (`.env`)

Sao chép tệp `.env.gpu` thành `.env` ở thư mục gốc và cấu hình đầy đủ các tham số sau:

```ini
# Cấu hình Database
DB_NAME=airline_db
DB_SA_PASSWORD=YourSecurePassword123!

# Cấu hình mô hình ngôn ngữ lớn (vLLM / NVIDIA NIM)
LLM_MODEL=nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4
VLLM_URL=http://vllm:8000/v1
NVIDIA_API_KEY=nvapi-your-key-here
VLLM_API_KEY=your-vllm-key-here # Nếu dùng vLLM độc lập

# Cấu hình Vector DB (Qdrant)
QDRANT_URL=http://qdrant:6333
CACHE_TTL_HOURS=2.0
CACHE_SIMILARITY_THRESHOLD=0.92

# Cấu hình giám sát (Langfuse)
LANGFUSE_PUBLIC_KEY=pk-lf-default
LANGFUSE_SECRET_KEY=sk-lf-default
LANGFUSE_HOST=http://langfuse:3000

# Cấu hình bảo mật API
JWT_SECRET_KEY=your-jwt-secret-key-32-chars-long
DEV_BYPASS_TOKEN=your-dev-bypass-token
TOKEN_GEN_USER=vj_admin
TOKEN_GEN_PASSWORD=your-token-generation-password-here
```

---

## Hướng Dẫn Chạy Nhanh (Quick Start)

### Cách 1: Chạy trực tiếp trên máy cục bộ (Local Development)

#### Bước 1: Huấn luyện các mô hình Machine Learning
```bash
pip install -r kaggle/requirements.txt
python kaggle/scripts/run_pipeline.py
```
*Các mô hình và báo cáo so sánh sẽ tự động được lưu vào thư mục `outputs/`.*

#### Bước 2: Khởi chạy Backend API (Cần cài đặt SQL Server, Qdrant và Langfuse cục bộ)
```bash
cd backend
pip install -r requirements.txt
uvicorn backend.src.api.main:app --reload --port 8000
```
*Tài liệu API trực quan sẽ khả dụng tại: [http://localhost:8000/docs](http://localhost:8000/docs)*

#### Bước 3: Khởi chạy Frontend Dashboard
```bash
cd ../frontend
npm install
npm run dev
```
*Mở trình duyệt và truy cập: [http://localhost:3000](http://localhost:3000)*

---

### Cách 2: Chạy thông qua Docker Compose (Khuyên dùng trên GPU Server)

Dự án hỗ trợ Docker Compose giúp khởi chạy toàn bộ hệ sinh thái (Frontend + Backend + Nginx + vLLM/NIM + Qdrant + Langfuse) trên GPU Server chỉ với một câu lệnh duy nhất:

#### Khởi chạy môi trường phát triển (Development Profile):
```bash
docker compose -f docker-compose.gpu.yml --profile dev up --build -d
```
*   **Frontend**: [http://localhost:3000](http://localhost:3000) (Hỗ trợ Hot Reload)
*   **Backend API**: [http://localhost:8020](http://localhost:8020)
*   **Qdrant Console**: [http://localhost:6333/dashboard](http://localhost:6333/dashboard)
*   **Langfuse Dashboard**: [http://localhost:4000](http://localhost:4000)

#### Khởi chạy môi trường Production:
```bash
docker compose -f docker-compose.gpu.yml --profile prod up -d --build
```
*   Hệ thống sẽ đóng gói build tĩnh Frontend và chạy thông qua **Nginx Reverse Proxy**.
*   **Truy cập Dashboard**: [http://localhost](http://localhost) (Cổng 80 mặc định)

---

## Hiệu Năng Các Mô Hỏi Học Máy (Model Rankings)

Hệ thống đã huấn luyện và đánh giá chéo trên tập kiểm thử độc lập gồm **577,448 dòng dữ liệu** (Temporal Split):

| Xếp Hạng | Mô Hình | MAPE (%) | RMSE (VND) | MAE (VND) | Hệ Số R² | Thời Gian Train |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| 1 | **XGBoost (Best Single)** | **22.71%** | 1,124,685.56 | 374,121.67 | 0.7525 | ~103s |
| 2 | **Weighted Ensemble** | **22.80%** | **1,121,311.29** | **373,674.25** | **0.7540** | *Kết hợp nhanh* |
| 3 | **LightGBM** | 23.33% | 1,127,356.90 | 378,722.17 | 0.7513 | ~52s |
| 4 | **CatBoost** | 25.90% | 1,235,362.87 | 424,042.29 | 0.7014 | ~82s |
| 5 | **Random Forest** | 30.42% | 1,193,730.52 | 414,902.52 | 0.7212 | ~1009s |
| 6 | **Gradient Boosting** | 37.21% | 1,252,819.83 | 461,450.36 | 0.6929 | ~4403s |
| 7 | **MLP Neural Network** | 46.97% | 1,315,123.65 | 529,591.01 | 0.6616 | ~7641s |

> [!TIP]
> *   **Weighted Ensemble** kết hợp đầu ra của các mô hình theo tỉ lệ: **66.54% XGBoost**, **33.45% LightGBM** và **0.01% RandomForest**. Sự kết hợp này mang lại hệ số xác định R² cao nhất (**0.7540**) và hạn chế sai số cực đại (RMSE thấp nhất).
> *   Chi tiết về cách xử lý tiền dữ liệu, điền khuyết quy nạp và phân tích độ ảnh hưởng của biến (SHAP value), xem thêm tại tài liệu: [ML_EXPLANATION.md](file:///d:/LLM/ML_EXPLANATION.md).
> *   Dự án đã được tối ưu hóa cho hệ sinh thái phần cứng & phần mềm của **NVIDIA** (chạy GPU gốc cho XGBoost/LightGBM/CatBoost, tăng tốc Random Forest qua **RAPIDS cuML**, tích hợp **NIM** & **NeMo Agent** để tự động gom dữ liệu). Xem chi tiết tại [Mục 10 của ML_EXPLANATION.md](file:///d:/LLM/ML_EXPLANATION.md#10-kien-truc-tu-dong-hoa-data-pipeline--toi-uu-hoa-tren-he-sinh-thai-nvidia).

---

## Tài Liệu Tham Khảo Liên Quan
*   [SETUP.md](file:///d:/LLM/SETUP.md): Hướng dẫn chi tiết thiết lập môi trường, danh sách các API endpoints và tham số.
*   [ML_EXPLANATION.md](file:///d:/LLM/ML_EXPLANATION.md): Tài liệu chuyên sâu về giải thuật Machine Learning, Feature Engineering, cách chia tập dữ liệu, kết quả thực nghiệm và tích hợp NVIDIA.
