"""Tests for the retrieval service factory (no database, no model)."""
from src.core.settings import RagSettings
from src.integrations.llm.embeddings import BgeM3Embedder
from src.services.retrieval import factory
from src.services.retrieval.factory import CONNECT_TIMEOUT_S, build_retrieval_service
from src.services.retrieval.service import RetrievalService
from tests.support.fake_embedder import HashingEmbedder


def test_builds_service_with_given_settings_and_embedder(monkeypatch):
    calls = []
    monkeypatch.setattr(factory.psycopg, "connect", lambda url, **kw: calls.append((url, kw)) or "conn")
    settings = RagSettings(database_url="postgresql://u:p@127.0.0.1:5433/demo")
    embedder = HashingEmbedder()
    service = build_retrieval_service(settings, embedder)
    assert isinstance(service, RetrievalService)
    assert service.settings is settings and service.embedder is embedder
    assert service.connect() == "conn"
    assert calls == [("postgresql://u:p@127.0.0.1:5433/demo", {"connect_timeout": CONNECT_TIMEOUT_S})]


def test_defaults_to_loaded_settings_and_a_lazy_bge_m3(monkeypatch):
    settings = RagSettings(embedding_model="demo/model", embedding_device="cuda")
    monkeypatch.setattr(factory, "load_rag_settings", lambda: settings)
    service = build_retrieval_service()
    assert service.settings is settings
    assert isinstance(service.embedder, BgeM3Embedder)
    assert (service.embedder.model_name, service.embedder.device) == ("demo/model", "cuda")
    assert service.embedder._model is None   # nothing loaded until the first search
