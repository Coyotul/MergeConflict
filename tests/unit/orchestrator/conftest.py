"""Shared fixtures for orchestrator unit tests."""
from pathlib import Path

import pytest

from src.agent.orchestration.orchestrator import Orchestrator
from src.agent.tools.retrieval import StubPolicySearch
from src.agent.tools.stubs import StubData, build_stub_registry
from src.integrations.llm.chat import FakeChatModel
from src.services.conversations.store import InMemorySessionStore

# Anchor on this file, not the working directory.
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config" / "orchestrator"
CATALOG_CODES = ["personal_loan", "refinancing_unsecured", "mortgage_casa_ta"]


@pytest.fixture
def stub_data() -> StubData:
    return StubData.load(CONFIG_DIR)


@pytest.fixture
def orchestrator_factory(stub_data):
    """Return make(responses, **orchestrator_kwargs) -> (orch, store, model)."""

    def make(responses, **kwargs):
        store = InMemorySessionStore()
        model = FakeChatModel(responses)
        registry = build_stub_registry(stub_data, StubPolicySearch(CONFIG_DIR))
        orch = Orchestrator(store, model, registry, list(CATALOG_CODES), **kwargs)
        return orch, store, model

    return make
