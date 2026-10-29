"""Factory functions for building orchestrator components."""
from dataclasses import replace
from pathlib import Path
from datetime import datetime
from typing import Callable

import psycopg

from src.agent.orchestration.demo_model import DemoChatModel
from src.agent.orchestration.orchestrator import Orchestrator, utcnow
from src.agent.orchestration.trace import FileTracer, NullTracer, Tracer
from src.agent.tools.credit_check import make_eligibility_handler, make_profile_handler
from src.agent.tools.registry import ToolRegistry
from src.agent.tools.retrieval import PolicySearch, build_policy_search
from src.agent.tools.stubs import StubData, build_stub_registry
from src.core.errors import ConfigurationError
from src.core.settings import OrchestratorSettings
from src.integrations.credit_sources import SqliteCreditSources, load_bindings
from src.integrations.llm.chat import ChatModel, FeatherlessChatModel
from src.services.conversations.store import (
    InMemorySessionStore,
    FileSessionStore,
    SessionStore,
)
from src.services.conversations.postgres_store import PostgresSessionStore
from src.services.document_processing.service import DocumentProcessingService
from src.storage.secure_documents.store import SecureDocumentStore


def build_chat_model(settings: OrchestratorSettings) -> ChatModel:
    """Build a chat model based on settings.

    Args:
        settings: Orchestrator settings

    Returns:
        ChatModel implementation

    "fake" selects the scripted DemoChatModel (mock mode, no API key needed).

    Raises:
        ConfigurationError: If the Featherless configuration is invalid
    """
    if settings.model == "fake":
        return DemoChatModel()
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


def build_tracer(settings: OrchestratorSettings) -> Tracer:
    """Build a tracer based on settings.

    Args:
        settings: Orchestrator settings

    Returns:
        Tracer implementation
    """
    if settings.trace == "off":
        return NullTracer()
    elif settings.trace == "file":
        return FileTracer(settings.traces_dir)
    else:
        raise ConfigurationError(f"Unknown trace type: {settings.trace}")


def build_registry(
    settings: OrchestratorSettings, stub_data: StubData, policy_search: PolicySearch,
    document_service: DocumentProcessingService | None = None,
) -> ToolRegistry:
    """Stub registry with get_customer_profile and run_eligibility_check backed by SQLite credit sources.

    The ToolSpec fields (flows, preconditions, model visibility) stay those of the stub registry;
    only the handlers change.
    """
    registry = build_stub_registry(stub_data, policy_search, document_service=document_service)
    sources = SqliteCreditSources(settings.credit_sources_db, load_bindings(settings.customer_bindings_path))
    overrides = {
        "get_customer_profile": make_profile_handler(sources),
        "run_eligibility_check": make_eligibility_handler(sources, stub_data),
    }
    for name, handler in overrides.items():
        registry.register(replace(registry.get(name), handler=handler))
    return registry


def build_orchestrator(
    settings: OrchestratorSettings,
    *,
    model: ChatModel | None = None,
    store: SessionStore | None = None,
    tracer: Tracer | None = None,
    documents: SecureDocumentStore | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> Orchestrator:
    """Build an orchestrator with all dependencies.

    Args:
        settings: Orchestrator settings
        model: Optional pre-built chat model (for testing)
        store: Optional pre-built session store (for testing)
        tracer: Optional pre-built tracer (for testing)
        documents: Optional shared upload store; always uses real OCR/extraction
        clock: Server-owned clock; explicitly injectable for reproducible simulations

    Returns:
        Configured Orchestrator instance
    """
    if model is None:
        model = build_chat_model(settings)
    if store is None:
        store = build_session_store(settings)
    if tracer is None:
        tracer = build_tracer(settings)

    # Load stub data for catalog and registry
    stub_data = StubData.load(settings.config_dir)
    catalog_codes = [product.value for product in stub_data.products.keys()]

    # Build policy search
    policy_search = build_policy_search(settings)

    # Build tool registry
    if documents is None:
        documents = SecureDocumentStore(settings.uploads_dir, max_file_size_bytes=settings.max_upload_bytes)
    registry = build_registry(settings, stub_data, policy_search, DocumentProcessingService(documents))

    return Orchestrator(
        store=store,
        model=model,
        registry=registry,
        catalog_codes=catalog_codes,
        max_steps=settings.max_steps,
        history_window=settings.history_window,
        tracer=tracer,
        model_info={"model": settings.model, "temperature": settings.temperature, "json_mode": settings.json_mode},
        clock=clock,
    )
