"""
rag/pinecone_store.py — Pinecone vector store initialisation and query interface.

Uses:
  - pinecone-client  for index management
  - langchain-pinecone for LangChain-compatible retriever
  - HuggingFace all-MiniLM-L6-v2 (384-dim, runs locally, free)

Embeddings are loaded LAZILY on first query — not at startup — so the server
starts instantly without blocking on the ~40s model download/load.
"""

import logging
import time
from typing import Optional

from pinecone import Pinecone, ServerlessSpec
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore

from config import settings

logger = logging.getLogger(__name__)


class PineconeStore:
    """
    Manages the Pinecone index and exposes a simple query interface.

    Startup: only connects to the Pinecone index (fast, ~1s).
    First query: loads HuggingFace embeddings model (~10s, cached after that).
    """

    def __init__(self):
        self.index_name = settings.PINECONE_INDEX_NAME
        self.dimension = settings.PINECONE_DIMENSION
        self.index = None
        self.vector_store: Optional[PineconeVectorStore] = None
        self._embeddings: Optional[HuggingFaceEmbeddings] = None

        self._connect_index()

    # ── Internal setup ────────────────────────────────────────────────────────

    def _get_embeddings(self) -> HuggingFaceEmbeddings:
        """Load embedding model once, reuse after that."""
        if self._embeddings is None:
            logger.info("[PineconeStore] Loading HuggingFace embeddings model …")
            self._embeddings = HuggingFaceEmbeddings(
                model_name=settings.EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
            logger.info("[PineconeStore] Embedding model loaded.")
        return self._embeddings

    def _connect_index(self):
        """Connect to Pinecone index only — no embedding model loaded here."""
        if not settings.PINECONE_API_KEY:
            logger.warning("[PineconeStore] PINECONE_API_KEY not set — RAG unavailable.")
            return

        try:
            pc = Pinecone(api_key=settings.PINECONE_API_KEY)

            existing = [idx.name for idx in pc.list_indexes()]
            if self.index_name not in existing:
                logger.info(f"[PineconeStore] Creating index '{self.index_name}' (dim={self.dimension}) …")
                pc.create_index(
                    name=self.index_name,
                    dimension=self.dimension,
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1"),
                )
                for _ in range(20):
                    index_info = pc.describe_index(self.index_name)
                    status = index_info.status
                    is_ready = status.get("ready", False) if isinstance(status, dict) else getattr(status, "ready", False)
                    if is_ready:
                        break
                    time.sleep(2)
                logger.info(f"[PineconeStore] Index '{self.index_name}' ready.")
            else:
                logger.info(f"[PineconeStore] Connected to existing index '{self.index_name}'.")

            self.index = pc.Index(self.index_name)
            logger.info("[PineconeStore] Index connected. Embeddings load on first query.")

        except Exception as e:
            logger.error(f"[PineconeStore] Index connection failed: {e}", exc_info=True)
            self.index = None

    def _get_vector_store(self) -> Optional[PineconeVectorStore]:
        """Lazy-initialise the LangChain vector store on first use."""
        if self.vector_store is None and self.index is not None:
            self.vector_store = PineconeVectorStore(
                index=self.index,
                embedding=self._get_embeddings(),
                text_key="text",
            )
            logger.info("[PineconeStore] LangChain vector store initialised.")
        return self.vector_store

    # ── Public API ────────────────────────────────────────────────────────────

    def query(self, query_text: str, top_k: int = 3) -> list[str]:
        """Retrieve the top-k most relevant document chunks for a query."""
        vs = self._get_vector_store()
        if vs is None:
            logger.warning("[PineconeStore] query() called but vector store is unavailable.")
            return []

        try:
            docs = vs.similarity_search(query_text, k=top_k)
            results = [doc.page_content for doc in docs]
            logger.info(f"[PineconeStore] query='{query_text[:60]}…' returned {len(results)} chunks.")
            return results
        except Exception as e:
            logger.error(f"[PineconeStore] query() failed: {e}", exc_info=True)
            return []

    def query_with_scores(self, query_text: str, top_k: int = 3) -> list[tuple[str, float]]:
        """Returns (text, score) tuples for relevance debugging."""
        vs = self._get_vector_store()
        if vs is None:
            return []
        try:
            results = vs.similarity_search_with_score(query_text, k=top_k)
            return [(doc.page_content, score) for doc, score in results]
        except Exception as e:
            logger.error(f"[PineconeStore] query_with_scores() failed: {e}")
            return []

    def is_ready(self) -> bool:
        return self.index is not None
