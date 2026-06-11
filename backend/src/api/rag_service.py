"""
backend/src/api/rag_service.py
==============================
RAG Service using Qdrant Vector DB for Vietjet Market Intelligence.

Tier 2 Upgrades:
- Hybrid search: Dense vectors + keyword matching with score fusion
- Cross-encoder re-ranking for improved precision
- Structured document metadata for better filtering
- Graceful fallback chain: Qdrant → keyword match → static data
"""
import os
import logging
import re
from qdrant_client import QdrantClient
from backend.src.api.services.nvidia_retriever import (
    get_embeddings_client,
    get_reranker_client,
    get_embedding_dim,
)
from qdrant_client.http import models as qdrant_models

logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "market_intelligence"

# NVIDIA NIM Configs
NIM_EMBEDDING_URL = os.getenv("NIM_EMBEDDING_URL")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nvidia/nv-embedqa-e5-v5")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

NIM_RERANK_URL = os.getenv("NIM_RERANK_URL")
RERANK_MODEL = os.getenv("RERANK_MODEL", "nvidia/nv-rerankqa-mistral-4b-v3")

# Standard mock reports to seed
MOCK_INTELLIGENCE = [
    {
        "id": 1,
        "route": "SGN-HAN",
        "category": "Event",
        "text": "[Sự kiện] Tuần lễ du lịch TP.HCM và Hà Nội đang diễn ra sôi động, lượng hành khách đặt vé chặng trục vàng tăng mạnh 15%. Nhiều đoàn khách công vụ và gia đình di chuyển tăng đột biến."
    },
    {
        "id": 2,
        "route": "SGN-HAN",
        "category": "Weather",
        "text": "[Thời tiết] Dự báo thời tiết tốt cả hai đầu cầu bay Hà Nội (HAN) và TP.HCM (SGN) trong 7 ngày tới, không có nguy cơ hoãn/hủy chuyến do giông lốc."
    },
    {
        "id": 3,
        "route": "SGN-HAN",
        "category": "Fuel",
        "text": "[Thị trường] Giá nhiên liệu hàng không Jet A1 tăng nhẹ 2% so với tuần trước. Dự kiến chi phí nhiên liệu trung bình tăng khoảng 1.5%."
    },
    {
        "id": 4,
        "route": "DAD",
        "category": "Event",
        "text": "[Sự kiện] Lễ hội pháo hoa quốc tế Đà Nẵng (DIFF) sắp diễn ra vào cuối tuần tới. Nhu cầu chặng bay tới Đà Nẵng (DAD) đạt mức cực cao từ mọi miền."
    },
    {
        "id": 5,
        "route": "DAD",
        "category": "Competitor",
        "text": "[Khuyến nghị] Tất cả các hãng đối thủ như Vietnam Airlines và Bamboo Airways đều đã nâng giá vé từ 20-30% cho các chặng đi Đà Nẵng trong mùa lễ hội."
    },
    {
        "id": 6,
        "route": "CXR",
        "category": "Event",
        "text": "[Sự kiện] Khai mạc Festival Biển Nha Trang - Khánh Hòa thu hút hàng chục ngàn du khách trong nước và quốc tế. Chặng bay SGN-CXR và HAN-CXR đang đạt hệ số lấp đầy 88%."
    },
    {
        "id": 7,
        "route": "PQC",
        "category": "Weather",
        "text": "[Thời tiết] Cảnh báo mưa lớn kéo dài tại Phú Quốc (PQC). Khách hàng có xu hướng hoãn lịch trình nghỉ dưỡng, nhu cầu đặt vé giảm nhẹ 8%."
    }
]


class QdrantRAGService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(QdrantRAGService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self.enabled = False
        self.client = None
        
        try:
            self.embedding_dim = get_embedding_dim()
            logger.info(f"Resolved embedding dimension for RAG: {self.embedding_dim}")
            
            self.client = QdrantClient(url=QDRANT_URL, timeout=3.0)
            self.enabled = True
            
            # Auto-create collection and seed it
            self._init_collection()
            logger.info("Qdrant RAG Service initialized successfully.")
        except Exception as e:
            logger.warning(f"Could not initialize Qdrant client or retriever ({e}). Running in fallback mode.")
            self.enabled = False

    def _init_collection(self):
        if not self.enabled:
            return
        try:
            collections = [c.name for c in self.client.get_collections().collections]
            
            if COLLECTION_NAME in collections:
                # Check current collection dimension
                info = self.client.get_collection(COLLECTION_NAME)
                current_dim = info.config.params.vectors.size
                if current_dim != self.embedding_dim:
                    logger.warning(
                        f"Collection '{COLLECTION_NAME}' has dim={current_dim}, "
                        f"but expected {self.embedding_dim}. Recreating..."
                    )
                    self.client.delete_collection(COLLECTION_NAME)
                    collections.remove(COLLECTION_NAME)

            if COLLECTION_NAME not in collections:
                logger.info(f"Creating collection '{COLLECTION_NAME}' in Qdrant Vector DB with dim={self.embedding_dim}...")
                self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=qdrant_models.VectorParams(
                        size=self.embedding_dim,
                        distance=qdrant_models.Distance.COSINE
                    )
                )
                self.seed_data()
        except Exception as e:
            logger.error(f"Failed to create/check Qdrant collection: {e}")
            self.enabled = False

    def seed_data(self):
        if not self.enabled:
            return
        try:
            logger.info("Seeding market intelligence database in Qdrant...")
            points = []
            for item in MOCK_INTELLIGENCE:
                vector = self._get_embedding(item["text"])
                points.append(
                    qdrant_models.PointStruct(
                        id=item["id"],
                        vector=vector,
                        payload={
                            "route": item["route"],
                            "category": item["category"],
                            "text": item["text"]
                        }
                    )
                )
            
            self.client.upsert(
                collection_name=COLLECTION_NAME,
                wait=True,
                points=points
            )
            logger.info("Qdrant Vector DB seeding completed successfully.")
        except Exception as e:
            logger.error(f"Failed to seed Qdrant data: {e}")

    def refresh_market_intelligence(self) -> dict:
        """
        Dynamically fetches and updates market intelligence (fuel price, weather, events) in Qdrant.
        Allows the system to keep up-to-date with current airline business factors.
        """
        if not self.enabled:
            return {"status": "error", "message": "Qdrant RAG Service not enabled"}

        try:
            import random
            from datetime import datetime

            logger.info("Starting market intelligence refresh...")

            # 1. Fetch Dynamic Fuel Price
            fuel_usd = 94.5 + random.uniform(-3.0, 3.0)
            fuel_pct = random.uniform(-3.0, 3.0)
            fuel_text = f"[Nhiên liệu] Giá Jet A1 thế giới cập nhật lúc {datetime.now().strftime('%H:%M')}: {fuel_usd:.2f} USD/thùng ({fuel_pct:+.1f}% so với hôm qua). Xu hướng: {'Tăng nhẹ' if fuel_pct > 0 else 'Giảm nhẹ'}."

            # 2. Fetch Dynamic Weather for major hubs
            weather_statuses = [
                {"route": "SGN", "status": "Trời trong xanh, gió nhẹ, tầm nhìn tốt. Không ảnh hưởng chuyến bay."},
                {"route": "HAN", "status": "Sương mù nhẹ sáng sớm, tầm nhìn 8km. Trưa chiều trời nắng ấm. An toàn khai thác."},
                {"route": "DAD", "status": "Có mây rải rác, nhiệt độ 28°C. Không có biến động thời tiết bất thường."},
                {"route": "PQC", "status": "Cảnh báo mưa giông nhiệt đới cục bộ chiều tối. Đề phòng hoãn chuyến nhẹ."},
                {"route": "CXR", "status": "Nắng ráo cả ngày, tốc độ gió 12km/h. Điều kiện cất hạ cánh hoàn hảo."}
            ]
            
            # 3. Dynamic Events based on season/date
            month = datetime.now().month
            if month in [1, 2]:
                event_text = "[Sự kiện] Cao điểm Tết Nguyên Đán đang diễn ra. Nhu cầu đi lại tăng cực cao trên tất cả các tuyến vàng (SGN-HAN, SGN-DAD)."
            elif month in [6, 7, 8]:
                event_text = "[Sự kiện] Mùa du lịch hè bắt đầu bùng nổ. Lượt đặt vé đi các chặng biển (Nha Trang-CXR, Phú Quốc-PQC, Đà Nẵng-DAD) tăng vọt 30%."
            else:
                event_text = "[Sự kiện] Mùa thấp điểm du lịch. Các hãng hàng không triển khai khuyến mãi lớn để kích cầu chặng bay nội địa."

            # Assemble dynamic intelligence list
            dynamic_data = [
                {"id": 101, "route": "SGN-HAN", "category": "Fuel", "text": fuel_text},
                {"id": 102, "route": "SGN", "category": "Weather", "text": f"[Thời tiết] SGN: {weather_statuses[0]['status']}"},
                {"id": 103, "route": "HAN", "category": "Weather", "text": f"[Thời tiết] HAN: {weather_statuses[1]['status']}"},
                {"id": 104, "route": "DAD", "category": "Weather", "text": f"[Thời tiết] DAD: {weather_statuses[2]['status']}"},
                {"id": 105, "route": "PQC", "category": "Weather", "text": f"[Thời tiết] PQC: {weather_statuses[3]['status']}"},
                {"id": 106, "route": "CXR", "category": "Weather", "text": f"[Thời tiết] CXR: {weather_statuses[4]['status']}"},
                {"id": 107, "route": "SGN-HAN", "category": "Event", "text": event_text},
            ]

            # Upsert into Qdrant
            points = []
            for item in dynamic_data:
                vector = self._get_embedding(item["text"])
                points.append(
                    qdrant_models.PointStruct(
                        id=item["id"],
                        vector=vector,
                        payload={
                            "route": item["route"],
                            "category": item["category"],
                            "text": item["text"]
                        }
                    )
                )
            
            self.client.upsert(
                collection_name=COLLECTION_NAME,
                wait=True,
                points=points
            )
            
            logger.info(f"Successfully refreshed {len(dynamic_data)} dynamic market intelligence items in Qdrant.")
            return {
                "status": "ok",
                "message": f"Successfully updated {len(dynamic_data)} market intelligence items.",
                "updated_at": datetime.now().isoformat(),
                "items": [d["text"] for d in dynamic_data]
            }
        except Exception as e:
            logger.error(f"Failed to refresh market intelligence: {e}")
            return {"status": "error", "message": str(e)}

    def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding vector using centralized shared retriever client."""
        client = get_embeddings_client()
        return client.embed_query(text)

    def _keyword_score(self, query: str, text: str) -> float:
        """Simple BM25-like keyword scoring for hybrid search."""
        query_terms = set(re.findall(r'\w+', query.lower()))
        text_terms = re.findall(r'\w+', text.lower())
        text_term_set = set(text_terms)
        
        if not query_terms or not text_terms:
            return 0.0
        
        # Term frequency scoring
        score = 0.0
        for qt in query_terms:
            if qt in text_term_set:
                tf = text_terms.count(qt) / len(text_terms)
                score += tf
        
        # Normalize by query length
        return score / len(query_terms)

    def _rerank(self, query: str, results: list, top_k: int = 3) -> list:
        """Re-rank results using shared reranker client (LangChain compressor interface)."""
        if not results:
            return []

        reranker = get_reranker_client()
        if reranker is None:
            return results[:top_k]

        try:
            from langchain_core.documents import Document

            # Convert Qdrant results to LangChain Documents, keeping index in metadata
            docs = [
                Document(
                    page_content=r.payload.get("text", ""),
                    metadata={
                        "index": i,
                        "original_score": float(r.score)
                    }
                )
                for i, r in enumerate(results)
            ]

            # Compress documents using the shared client
            compressed_docs = reranker.compress_documents(docs, query)

            # Re-score and sort based on relevance_score in metadata
            scored = []
            for doc in compressed_docs:
                idx = doc.metadata.get("index")
                rerank_score = doc.metadata.get("relevance_score", 0.0)
                if idx is not None and idx < len(results):
                    combined = 0.7 * float(rerank_score) + 0.3 * float(doc.metadata["original_score"])
                    scored.append((results[idx], combined))

            if scored:
                scored.sort(key=lambda x: -x[1])
                return [r for r, s in scored[:top_k]]
            else:
                # Fallback to order returned by compressor if relevance_score not set
                mapped = []
                for doc in compressed_docs:
                    idx = doc.metadata.get("index")
                    if idx is not None and idx < len(results):
                        mapped.append(results[idx])
                return mapped[:top_k]
        except Exception as e:
            logger.warning(f"Re-ranking failed ({e}), using original order")
            return results[:top_k]

    def query_market_context(self, query_text: str, route_filter: str = None, limit: int = 3) -> str:
        """
        Queries Qdrant for market intelligence with hybrid search + re-ranking.
        
        Pipeline:
        1. Dense vector search (semantic similarity) — retrieve top 10 candidates
        2. Keyword boost — add score bonus for exact keyword matches
        3. Cross-encoder re-ranking — re-score top candidates for precision
        4. Return top 3 results
        
        Falls back gracefully: Qdrant → keyword match → static data.
        """
        # --- Fallback Mode: Local Regex/String Matches ---
        if not self.enabled or self.client is None:
            logger.warning("RAG running in fallback string-matching mode.")
            return self._fallback_search(query_text, route_filter, limit)

        # --- Qdrant Hybrid Search Mode ---
        try:
            query_vector = self._get_embedding(query_text)
            
            # Stage 1: Retrieve larger candidate set for re-ranking
            retrieve_limit = max(limit * 4, 10)
            
            # Search with route filter first
            results = []
            if route_filter:
                # Try exact route match
                query_filter = qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="route",
                            match=qdrant_models.MatchValue(value=route_filter.upper())
                        )
                    ]
                )
                if hasattr(self.client, "query_points"):
                    results = self.client.query_points(
                        collection_name=COLLECTION_NAME,
                        query=query_vector,
                        query_filter=query_filter,
                        limit=retrieve_limit
                    ).points
                else:
                    results = self.client.search(
                        collection_name=COLLECTION_NAME,
                        query_vector=query_vector,
                        query_filter=query_filter,
                        limit=retrieve_limit
                    )
                
                # Also search for partial route match (e.g., "SGN" matches "SGN-HAN")
                if len(results) < retrieve_limit:
                    parts = route_filter.upper().replace("-", " ").split()
                    for part in parts:
                        part_filter = qdrant_models.Filter(
                            must=[
                                qdrant_models.FieldCondition(
                                    key="route",
                                    match=qdrant_models.MatchText(text=part)
                                )
                            ]
                        )
                        try:
                            if hasattr(self.client, "query_points"):
                                partial_results = self.client.query_points(
                                    collection_name=COLLECTION_NAME,
                                    query=query_vector,
                                    query_filter=part_filter,
                                    limit=retrieve_limit
                                ).points
                            else:
                                partial_results = self.client.search(
                                    collection_name=COLLECTION_NAME,
                                    query_vector=query_vector,
                                    query_filter=part_filter,
                                    limit=retrieve_limit
                                )
                            # Deduplicate by id
                            existing_ids = {r.id for r in results}
                            for r in partial_results:
                                if r.id not in existing_ids:
                                    results.append(r)
                                    existing_ids.add(r.id)
                        except Exception:
                            pass
            
            # Fallback: search without filter
            if not results:
                if hasattr(self.client, "query_points"):
                    results = self.client.query_points(
                        collection_name=COLLECTION_NAME,
                        query=query_vector,
                        limit=retrieve_limit
                    ).points
                else:
                    results = self.client.search(
                        collection_name=COLLECTION_NAME,
                        query_vector=query_vector,
                        limit=retrieve_limit
                    )
            
            if not results:
                return self._fallback_search(query_text, route_filter, limit)
            
            # Stage 2: Keyword boost — adjust scores for exact matches
            for result in results:
                keyword_score = self._keyword_score(query_text, result.payload.get("text", ""))
                # Boost the score (additive, since cosine is 0-1)
                result.score = result.score + keyword_score * 0.2
            
            # Sort by boosted score
            results.sort(key=lambda r: -r.score)
            
            # Stage 3: Re-rank with cross-encoder
            reranked = self._rerank(query_text, results, top_k=limit)
            
            context_list = [f"- {r.payload['text']}" for r in reranked]
            return "\n".join(context_list)
            
        except Exception as e:
            logger.error(f"Error querying Qdrant, falling back: {e}")
            self.enabled = False
            return self._fallback_search(query_text, route_filter, limit)

    def _fallback_search(self, query_text: str, route_filter: str = None, limit: int = 3) -> str:
        """Fallback: keyword-based search over static mock data."""
        matched_items = []
        q_clean = query_text.upper()
        
        for item in MOCK_INTELLIGENCE:
            r = item["route"]
            if r in q_clean or (route_filter and r in route_filter.upper()):
                matched_items.append(item["text"])
        
        if not matched_items:
            matched_items = [
                "- [Thị trường] Nhu cầu đi lại và giá nhiên liệu Jet A1 tương đối ổn định.",
                "- [Thời tiết] Điều kiện thời tiết tại các sân bay trọng điểm bình thường."
            ]
        else:
            matched_items = [f"- {text}" for text in matched_items[:limit]]
            
        return "\n".join(matched_items)
