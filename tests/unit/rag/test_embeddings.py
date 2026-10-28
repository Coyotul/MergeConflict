import pytest
from src.core.errors import EmbeddingModelUnavailable
from tests.support.fake_embedder import HashingEmbedder
from src.integrations.llm.embeddings import BgeM3Embedder


def test_hashing_embedder_is_deterministic_and_lexical():
    e = HashingEmbedder()
    a, b, c = e.embed_query("dobânda fixă"), e.embed_query("dobanda fixa"), e.embed_query("card de debit")
    cos = lambda x, y: sum(i * j for i, j in zip(x, y))
    assert len(a) == 1024 and cos(a, b) == pytest.approx(1.0) and cos(a, c) < 0.5


def test_bge_unavailable_raises_typed_error(monkeypatch):
    monkeypatch.delenv("RAG_ALLOW_MODEL_DOWNLOAD", raising=False)
    with pytest.raises(EmbeddingModelUnavailable):
        BgeM3Embedder(model_name="definitely/not-a-model").embed_query("x")
