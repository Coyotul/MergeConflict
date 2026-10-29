"""Tests for scripts/rag/ingest.py's start-up order (no model is ever loaded)."""
import sys

import pytest

from scripts.rag import ingest
from src.core.errors import KnowledgeStoreUnavailable


class ModelSpy:
    """Stands in for BgeM3Embedder and records whether anything tried to load the model."""
    created = 0

    def __init__(self, *args, **kwargs):
        ModelSpy.created += 1

    def embed_documents(self, texts):
        raise AssertionError("the model must not be loaded")


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    ModelSpy.created = 0
    monkeypatch.setattr(ingest, "BgeM3Embedder", ModelSpy)


def test_missing_manifest_is_a_one_line_error_with_exit_2(monkeypatch, tmp_path, capsys):
    missing = tmp_path / "missing.jsonl"
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--manifest", str(missing)])
    assert ingest.main() == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "manifest not found" in err and str(missing) in err
    assert ModelSpy.created == 0


def test_database_is_checked_before_the_model_is_loaded(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("", encoding="utf-8")
    monkeypatch.setenv("RAG_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:1/none")
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--manifest", str(manifest)])
    with pytest.raises(KnowledgeStoreUnavailable):
        ingest.main()
    assert ModelSpy.created == 0
