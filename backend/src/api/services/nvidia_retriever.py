"""
backend/src/api/services/nvidia_retriever.py
=============================================
Centralized NVIDIA NeMo Retriever client.
Provides singleton NVIDIAEmbeddings and NVIDIARerank instances
shared across RAG service, Semantic Cache, and Agent Graph.
"""
import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
NIM_EMBEDDING_URL = os.getenv("NIM_EMBEDDING_URL", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nvidia/embed-qa-4")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

NIM_RERANK_URL = os.getenv("NIM_RERANK_URL", "")
RERANK_MODEL = os.getenv("RERANK_MODEL", "nvidia/reranking-nv-embed-qa-4")


@lru_cache(maxsize=1)
def get_embeddings_client():
    """
    Singleton factory for NVIDIAEmbeddings client.
    When NIM / Cloud is not available, falls back to SentenceTransformer.
    """
    api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("VLLM_API_KEY")
    nim_emb_url = os.getenv("NIM_EMBEDDING_URL", "").strip()

    if nim_emb_url or api_key:
        try:
            from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings

            kwargs = {"model": EMBEDDING_MODEL}
            if api_key:
                kwargs["nvidia_api_key"] = api_key
            if nim_emb_url:
                kwargs["base_url"] = nim_emb_url.rstrip("/")

            client = NVIDIAEmbeddings(**kwargs)

            # Test connection
            test_vec = client.embed_query("test")
            actual_dim = len(test_vec)
            logger.info(
                f"✅ NeMo Retriever Embedding NIM connected: "
                f"model={EMBEDDING_MODEL}, dim={actual_dim}"
            )
            return client
        except Exception as e:
            logger.warning(f"NIM/Cloud Embedding unavailable ({e}). Falling back to local SentenceTransformer.")

    # ── Fallback: Local SentenceTransformer ─────────────────────────
    logger.info("Loading local SentenceTransformer as fallback...")
    try:
        from sentence_transformers import SentenceTransformer

        class LocalEmbeddingWrapper:
            """Wraps SentenceTransformer to match NVIDIAEmbeddings interface."""

            def __init__(self):
                self.model = SentenceTransformer("intfloat/multilingual-e5-large")
                self.dim = 1024

            def embed_query(self, text: str) -> list[float]:
                return self.model.encode(text).tolist()

            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [self.model.encode(t).tolist() for t in texts]

        return LocalEmbeddingWrapper()
    except Exception as e:
        logger.error(f"Failed to load fallback SentenceTransformer: {e}")
        raise ValueError(f"No embedding model is available. Fallback failed: {e}")


@lru_cache(maxsize=1)
def get_reranker_client():
    """
    Singleton factory for NVIDIARerank client.
    When NIM / Cloud is not available, falls back to CrossEncoder.
    """
    api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("VLLM_API_KEY")
    nim_rerank_url = os.getenv("NIM_RERANK_URL", "").strip()

    if nim_rerank_url or api_key:
        try:
            from langchain_nvidia_ai_endpoints import NVIDIARerank

            kwargs = {"model": RERANK_MODEL, "top_n": 5}
            if api_key:
                kwargs["nvidia_api_key"] = api_key
            if nim_rerank_url:
                kwargs["base_url"] = nim_rerank_url.rstrip("/")

            client = NVIDIARerank(**kwargs)
            
            # Test connection
            from langchain_core.documents import Document
            test_doc = Document(page_content="test")
            client.compress_documents([test_doc], "test")

            logger.info(
                f"✅ NeMo Retriever Reranking NIM connected: model={RERANK_MODEL}"
            )
            return client
        except Exception as e:
            logger.warning(f"NIM/Cloud Reranking unavailable ({e}). Falling back to local CrossEncoder.")

    # ── Fallback: Local CrossEncoder ────────────────────────────────
    logger.info("Loading local CrossEncoder as fallback...")
    try:
        from sentence_transformers import CrossEncoder

        class LocalRerankWrapper:
            """Wraps CrossEncoder to match NVIDIARerank interface."""

            def __init__(self):
                self.model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

            def compress_documents(self, documents, query):
                """LangChain DocumentCompressor interface."""
                if not documents:
                    return []
                pairs = [(query, doc.page_content) for doc in documents]
                scores = self.model.predict(pairs)
                for doc, score in zip(documents, scores):
                    doc.metadata["relevance_score"] = float(score)
                scored_docs = sorted(
                    zip(documents, scores), key=lambda x: -x[1]
                )
                return [doc for doc, _ in scored_docs]

        return LocalRerankWrapper()
    except Exception as e:
        logger.warning(f"Local CrossEncoder also unavailable: {e}")
        return None


def get_embedding_dim() -> int:
    """Returns the actual embedding dimension currently in use."""
    client = get_embeddings_client()
    if hasattr(client, "dim"):
        return client.dim  # Local fallback (1024)
    return EMBEDDING_DIM  # NIM config (1024)
