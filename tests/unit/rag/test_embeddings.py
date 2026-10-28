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


def _vectors_file(tmp_path, texts, vectors, model_name="BAAI/bge-m3"):
    import numpy as np
    path = tmp_path / "vectors.npz"
    np.savez(path, ids=np.array([f"q-{i}" for i in range(len(texts))]), texts=np.array(texts),
             vectors=np.array(vectors, dtype=np.float32), model_name=np.array(model_name))
    return path


def test_precomputed_embedder_serves_vectors_by_exact_question_text(tmp_path):
    from src.integrations.llm.embeddings import PrecomputedQueryEmbedder
    e = PrecomputedQueryEmbedder(_vectors_file(tmp_path, ["Ce este IRCC?", "Ce este DAE?"], [[0.5, 0.25], [1.0, 0.0]]))
    assert e.model_name == "BAAI/bge-m3" and e.dimension == 2
    assert e.embed_query("Ce este DAE?") == [1.0, 0.0] and e.embed_query("Ce este IRCC?") == [0.5, 0.25]
    with pytest.raises(EmbeddingModelUnavailable, match="no precomputed vector"):
        e.embed_query("Ce este DAE")
    with pytest.raises(EmbeddingModelUnavailable):
        e.embed_documents(["text"])


def test_precomputed_embedder_missing_file_is_typed_error(tmp_path):
    from src.integrations.llm.embeddings import PrecomputedQueryEmbedder
    with pytest.raises(EmbeddingModelUnavailable, match="query vectors"):
        PrecomputedQueryEmbedder(tmp_path / "absent.npz")
