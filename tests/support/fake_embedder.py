"""Fake embedder for testing without downloading real models."""

import re
import unicodedata
from binascii import crc32


class HashingEmbedder:
    """Deterministic fake embedder using token hashing."""

    model_name: str = "hashing-test"
    dimension: int

    def __init__(self, dimension: int = 1024):
        self.dimension = dimension

    def _normalize_text(self, text: str) -> str:
        """Strip accents and lowercase."""
        # Normalize to NFD (decomposed form) and remove combining characters
        nfd = unicodedata.normalize("NFD", text)
        stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
        return stripped.lower()

    def _tokenize(self, text: str) -> list[str]:
        """Extract word tokens."""
        normalized = self._normalize_text(text)
        # Extract \w+ tokens (alphanumeric and underscore)
        tokens = re.findall(r"\w+", normalized)
        return tokens

    def _embed_text(self, text: str) -> list[float]:
        """Create a hashed embedding vector."""
        tokens = self._tokenize(text)
        vector = [0.0] * self.dimension

        # Each token adds 1.0 at crc32(token) % dimension
        for token in tokens:
            token_bytes = token.encode("utf-8")
            index = crc32(token_bytes) % self.dimension
            vector[index] += 1.0

        # L2 normalize
        magnitude = sum(x * x for x in vector) ** 0.5
        if magnitude > 0:
            vector = [x / magnitude for x in vector]
        else:
            # All-zero vector becomes [1.0, 0, ...]
            vector[0] = 1.0

        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        return [self._embed_text(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        return self._embed_text(text)
