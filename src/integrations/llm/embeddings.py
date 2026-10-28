"""Embedding adapters for RAG retrieval."""

import os
from typing import Protocol

from sentence_transformers import SentenceTransformer

from src.core.errors import EmbeddingModelUnavailable


class Embedder(Protocol):
    """Protocol for embedding adapters."""

    model_name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        ...


class BgeM3Embedder:
    """Local BGE-M3 embedding adapter using sentence-transformers."""

    model_name: str
    dimension: int = 1024

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: str = "cpu",
        batch_size: int = 16,
    ):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model = None

    def _load_model(self) -> SentenceTransformer:
        """Lazily load the model on first use."""
        if self._model is None:
            try:
                # Only allow download if explicitly enabled
                local_files_only = os.environ.get("RAG_ALLOW_MODEL_DOWNLOAD") != "1"
                self._model = SentenceTransformer(
                    self.model_name,
                    device=self.device,
                    local_files_only=local_files_only,
                )
            except Exception as exc:
                raise EmbeddingModelUnavailable(
                    f"embedding model {self.model_name} unavailable: {exc}"
                )
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        model = self._load_model()
        embeddings = model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        model = self._load_model()
        embedding = model.encode(
            text,
            normalize_embeddings=True,
        )
        return embedding.tolist()
