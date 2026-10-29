"""Composition of a ready-to-use RetrievalService (the entry point for the orchestrator tool)."""
import psycopg

from src.core.settings import RagSettings, load_rag_settings
from src.integrations.llm.embeddings import BgeM3Embedder, Embedder
from src.services.retrieval.service import RetrievalService

# A refused local connection can hang instead of failing fast; bound it.
CONNECT_TIMEOUT_S = 10


def build_retrieval_service(settings: RagSettings | None = None, embedder: Embedder | None = None) -> RetrievalService:
    """A retrieval service over the configured database.

    settings default to load_rag_settings() (.env and RAG_* variables). The embedder defaults to
    the local BGE-M3 adapter, which loads the model lazily on the first search.
    """
    settings = settings or load_rag_settings()
    embedder = embedder or BgeM3Embedder(settings.embedding_model, settings.embedding_device)
    return RetrievalService(
        lambda: psycopg.connect(settings.database_url, connect_timeout=CONNECT_TIMEOUT_S), embedder, settings
    )
