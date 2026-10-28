"""Factory functions for building orchestrator components."""
from pathlib import Path

import psycopg

from src.agent.orchestration.orchestrator import Orchestrator
from src.agent.tools.registry import ToolRegistry
from src.agent.tools.retrieval import PolicySearch, build_policy_search
from src.agent.tools.stubs import StubData, build_stub_registry
from src.core.errors import ConfigurationError
from src.core.settings import OrchestratorSettings
from src.integrations.llm.chat import ChatModel, FeatherlessChatModel
from src.services.conversations.store import (
    InMemorySessionStore,
    FileSessionStore,
    SessionStore,
)
from src.services.conversations.postgres_store import PostgresSessionStore


def build_chat_model(settings: OrchestratorSettings) -> ChatModel:
    """Build a chat model based on settings.

    Args:
        settings: Orchestrator settings

    Returns:
        ChatModel implementation

    Raises:
        ConfigurationError: If model is "fake" (not yet available) or configuration is invalid
    """
    if settings.model == "fake":
        raise ConfigurationError("demo model not available")
    return FeatherlessChatModel(settings)


def build_session_store(settings: OrchestratorSettings) -> SessionStore:
    """Build a session store based on settings.

    Args:
        settings: Orchestrator settings

    Returns:
        SessionStore implementation
    """
    if settings.session_store == "memory":
        return InMemorySessionStore()
    elif settings.session_store == "file":
        return FileSessionStore(settings.sessions_dir)
    elif settings.session_store == "postgres":
        return PostgresSessionStore(lambda: psycopg.connect(settings.database_url))
    else:
        raise ConfigurationError(f"Unknown session store type: {settings.session_store}")


def build_orchestrator(
    settings: OrchestratorSettings,
    *,
    model: ChatModel | None = None,
    store: SessionStore | None = None
) -> Orchestrator:
    """Build an orchestrator with all dependencies.

    Args:
        settings: Orchestrator settings
        model: Optional pre-built chat model (for testing)
        store: Optional pre-built session store (for testing)

    Returns:
        Configured Orchestrator instance
    """
    if model is None:
        model = build_chat_model(settings)
    if store is None:
        store = build_session_store(settings)

    # Load stub data for catalog and registry
    stub_data = StubData.load(settings.config_dir)
    catalog_codes = [product.value for product in stub_data.products.keys()]

    # Build policy search
    policy_search = build_policy_search(settings)

    # Build tool registry
    registry = build_stub_registry(stub_data, policy_search)

    return Orchestrator(
        store=store,
        model=model,
        registry=registry,
        catalog_codes=catalog_codes,
        max_steps=settings.max_steps,
        history_window=settings.history_window,
    )
