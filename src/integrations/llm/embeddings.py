"""Embedding adapters for RAG retrieval."""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np

from src.core.errors import EmbeddingModelUnavailable

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


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

    def _load_model(self) -> "SentenceTransformer":
        """Lazily load the model on first use (torch is imported only here)."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

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


class PrecomputedQueryEmbedder:
    """Serves query vectors computed earlier (scripts/rag/embed_eval_queries.py), so no model is loaded.

    Lookup is by exact query text; unknown text, a missing file and document embedding
    raise EmbeddingModelUnavailable.
    """

    def __init__(self, path: Path):
        try:
            with np.load(path) as data:
                texts = [str(t) for t in data["texts"]]
                vectors = data["vectors"].astype(np.float32)
                self.model_name = str(data["model_name"])
        except (OSError, KeyError, ValueError) as exc:
            raise EmbeddingModelUnavailable(f"query vectors unavailable at {path}: {exc}") from exc
        self.dimension = int(vectors.shape[1])
        self._vectors = {text: vector for text, vector in zip(texts, vectors)}

    def embed_query(self, text: str) -> list[float]:
        vector = self._vectors.get(text)
        if vector is None:
            raise EmbeddingModelUnavailable(f"no precomputed vector for query {text[:60]!r}")
        return vector.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingModelUnavailable("precomputed query vectors cannot embed documents")
