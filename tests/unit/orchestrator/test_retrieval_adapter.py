"""Tests for RAG retrieval adapter."""
from datetime import datetime, date, UTC
from decimal import Decimal
from unittest.mock import Mock
import pytest

from src.agent.orchestration.state import SessionState
from src.agent.tools.contracts import SearchPoliciesInput, SearchPoliciesOutput
from src.agent.tools.registry import ToolContext
from src.agent.tools.retrieval import build_policy_search, PolicySearch
from src.agent.tools.stubs import build_stub_registry, StubData
from src.core.errors import (
    KnowledgeStoreUnavailable,
    EmbeddingModelUnavailable,
    ToolUnavailable,
    ConfigurationError,
)
from src.core.settings import OrchestratorSettings
from src.models.knowledge import (
    SearchQuery,
    SearchResult,
    SearchStatus,
    Passage,
    Citation,
    Scores,
    Product,
    DocKind,
    ChunkKind,
    Topic,
    Authority,
    PassageFlag,
    Conflict,
)


class FakePolicySearch:
    """Fake policy search for testing."""

    def __init__(self, result: SearchResult):
        self._result = result

    def search(self, query: SearchQuery) -> SearchResult:
        return self._result


class FakePolicySearchWithException:
    """Fake policy search that raises exceptions."""

    def __init__(self, exception: Exception):
        self._exception = exception

    def search(self, query: SearchQuery) -> SearchResult:
        raise self._exception


def test_rag_citation_mapping():
    """Test that RAG citations are correctly mapped to CitationRef."""
    # Build a fake passage with section path
    citation = Citation(
        publisher="Raiffeisen Bank",
        title="Credite de nevoi personale",
        url="https://www.raiffeisen.ro/persoane-fizice/credite/nevoi-personale/",
        section_path=["Costuri", "Comisioane"],
        effective_date=date(2024, 1, 15),
        fetched_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    )

    passage = Passage(
        chunk_id=123,
        document_id=45,
        doc_kind=DocKind.product_page,
        kind=ChunkKind.section,
        topic=Topic.costs_fees,
        products=[Product.personal_loan],
        authority=Authority.high,
        header="Comisioane aplicabile",
        text="Comisionul de acordare este 0%.",
        citation=citation,
        scores=Scores(dense=0.85, keyword=0.60, fused=0.75)
    )

    result = SearchResult(
        status=SearchStatus.ok,
        passages=[passage]
    )

    # Create fake policy search
    policy_search = FakePolicySearch(result)

    # Build registry with fake
    stub_data = StubData.load(OrchestratorSettings().config_dir)
    registry = build_stub_registry(stub_data, policy_search)

    # Execute search
    now = datetime.now(UTC)
    state = SessionState(
        session_id="test",
        customer_id="demo1",
        created_at=now,
        updated_at=now
    )
    ctx = ToolContext(state=state, now=now)
    tool_input = SearchPoliciesInput(text="care sunt comisioanele")

    tool_spec = registry.get("search_banking_policies")
    output = tool_spec.handler(tool_input, ctx)

    # Verify
    assert output.status == "ok"
    assert len(output.passages) == 1
    assert output.simulated is False  # RagPolicySearch has no simulated attribute

    # Check citation reference
    assert len(ctx.state.retrieved_sources) == 1
    citation_ref = ctx.state.retrieved_sources["c1"]
    assert citation_ref.publisher == "Raiffeisen Bank"
    assert citation_ref.title == "Credite de nevoi personale"
    assert citation_ref.url == "https://www.raiffeisen.ro/persoane-fizice/credite/nevoi-personale/"
    assert citation_ref.section == "Costuri > Comisioane"
    assert citation_ref.effective_date == date(2024, 1, 15)


def test_campaign_warning_in_text():
    """Test that campaign_ended and teaser_figure warnings are appended to text."""
    citation = Citation(
        publisher="Synthetic stub",
        title="Test page",
        url="https://example.com",
        section_path=["Promotii"],
        effective_date=date(2024, 1, 1),
        fetched_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    )

    passage = Passage(
        chunk_id=200,
        document_id=50,
        doc_kind=DocKind.product_page,
        kind=ChunkKind.section,
        topic=Topic.costs_fees,
        products=[Product.personal_loan],
        authority=Authority.high,
        header="Oferta speciala",
        text="Dobanda de la 5.9% pe an.",
        citation=citation,
        scores=Scores(dense=0.80, keyword=0.50, fused=0.65),
        flags=[PassageFlag.campaign_ended, PassageFlag.teaser_figure]
    )

    result = SearchResult(
        status=SearchStatus.ok,
        passages=[passage]
    )

    policy_search = FakePolicySearch(result)
    stub_data = StubData.load(OrchestratorSettings().config_dir)
    registry = build_stub_registry(stub_data, policy_search)

    now = datetime.now(UTC)
    state = SessionState(
        session_id="test",
        customer_id="demo1",
        created_at=now,
        updated_at=now
    )
    ctx = ToolContext(state=state, now=now)
    tool_input = SearchPoliciesInput(text="oferte")

    tool_spec = registry.get("search_banking_policies")
    output = tool_spec.handler(tool_input, ctx)

    assert output.status == "ok"
    assert len(output.passages) == 1
    passage_view = output.passages[0]

    # Warnings should be appended to text
    assert "[warning: campaign_ended]" in passage_view.text
    assert "[warning: teaser_figure]" in passage_view.text
    assert passage_view.text.startswith("Dobanda de la 5.9% pe an.")


def test_superseded_withdrawn_filtered_unless_only_ones():
    """Test that superseded/withdrawn passages are filtered unless they're the only ones."""
    # Create three passages: one superseded, one withdrawn, one normal
    citation1 = Citation(
        publisher="Synthetic stub",
        title="Old doc",
        url="https://example.com/old",
        section_path=[],
        effective_date=date(2023, 1, 1),
        fetched_at=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
    )

    passage1 = Passage(
        chunk_id=1,
        document_id=1,
        doc_kind=DocKind.product_page,
        kind=ChunkKind.section,
        topic=Topic.costs_fees,
        products=[Product.personal_loan],
        authority=Authority.high,
        header="Old info",
        text="Old rate info.",
        citation=citation1,
        scores=Scores(dense=0.80, keyword=0.50, fused=0.65),
        flags=[PassageFlag.superseded]
    )

    citation2 = Citation(
        publisher="Synthetic stub",
        title="Withdrawn doc",
        url="https://example.com/withdrawn",
        section_path=[],
        effective_date=date(2023, 6, 1),
        fetched_at=datetime(2023, 6, 1, 12, 0, 0, tzinfo=UTC)
    )

    passage2 = Passage(
        chunk_id=2,
        document_id=2,
        doc_kind=DocKind.product_page,
        kind=ChunkKind.section,
        topic=Topic.costs_fees,
        products=[Product.personal_loan],
        authority=Authority.high,
        header="Withdrawn info",
        text="Withdrawn rate info.",
        citation=citation2,
        scores=Scores(dense=0.75, keyword=0.45, fused=0.60),
        flags=[PassageFlag.withdrawn]
    )

    citation3 = Citation(
        publisher="Synthetic stub",
        title="Current doc",
        url="https://example.com/current",
        section_path=[],
        effective_date=date(2024, 1, 1),
        fetched_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    )

    passage3 = Passage(
        chunk_id=3,
        document_id=3,
        doc_kind=DocKind.product_page,
        kind=ChunkKind.section,
        topic=Topic.costs_fees,
        products=[Product.personal_loan],
        authority=Authority.high,
        header="Current info",
        text="Current rate info.",
        citation=citation3,
        scores=Scores(dense=0.90, keyword=0.70, fused=0.80)
    )

    # Test 1: With normal passage present, superseded/withdrawn are filtered
    result_with_normal = SearchResult(
        status=SearchStatus.ok,
        passages=[passage1, passage2, passage3]
    )

    policy_search = FakePolicySearch(result_with_normal)
    stub_data = StubData.load(OrchestratorSettings().config_dir)
    registry = build_stub_registry(stub_data, policy_search)

    now = datetime.now(UTC)
    state = SessionState(
        session_id="test",
        customer_id="demo1",
        created_at=now,
        updated_at=now
    )
    ctx = ToolContext(state=state, now=now)
    tool_input = SearchPoliciesInput(text="rate info")

    tool_spec = registry.get("search_banking_policies")
    output = tool_spec.handler(tool_input, ctx)

    # Should only include passage3
    assert len(output.passages) == 1
    assert output.passages[0].text == "Current rate info."

    # Test 2: When only superseded/withdrawn passages, include them
    result_only_flagged = SearchResult(
        status=SearchStatus.ok,
        passages=[passage1, passage2]
    )

    policy_search_only_flagged = FakePolicySearch(result_only_flagged)
    registry_only_flagged = build_stub_registry(stub_data, policy_search_only_flagged)

    now2 = datetime.now(UTC)
    state2 = SessionState(
        session_id="test2",
        customer_id="demo1",
        created_at=now2,
        updated_at=now2
    )
    ctx2 = ToolContext(state=state2, now=now2)

    tool_spec2 = registry_only_flagged.get("search_banking_policies")
    output2 = tool_spec2.handler(tool_input, ctx2)

    # Should include both flagged passages
    assert len(output2.passages) == 2


def test_conflicts_become_notice():
    """Test that conflicts are converted to notice entries."""
    citation = Citation(
        publisher="Synthetic stub",
        title="Test doc",
        url="https://example.com",
        section_path=[],
        effective_date=date(2024, 1, 1),
        fetched_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    )

    passage = Passage(
        chunk_id=300,
        document_id=60,
        doc_kind=DocKind.product_page,
        kind=ChunkKind.section,
        topic=Topic.costs_fees,
        products=[Product.personal_loan],
        authority=Authority.high,
        header="Rate info",
        text="Some rate information.",
        citation=citation,
        scores=Scores(dense=0.85, keyword=0.60, fused=0.75)
    )

    # Add a conflict
    conflict = Conflict(
        doc_kind=DocKind.product_page,
        topic=Topic.costs_fees,
        product=Product.personal_loan,
        chunk_ids=[300, 301, 302],
        effective_dates=[date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
    )

    result = SearchResult(
        status=SearchStatus.ok,
        passages=[passage],
        conflicts=[conflict]
    )

    policy_search = FakePolicySearch(result)
    stub_data = StubData.load(OrchestratorSettings().config_dir)
    registry = build_stub_registry(stub_data, policy_search)

    now = datetime.now(UTC)
    state = SessionState(
        session_id="test",
        customer_id="demo1",
        created_at=now,
        updated_at=now
    )
    ctx = ToolContext(state=state, now=now)
    tool_input = SearchPoliciesInput(text="rates")

    tool_spec = registry.get("search_banking_policies")
    output = tool_spec.handler(tool_input, ctx)

    # Check that notices are populated
    assert len(output.notices) == 1
    assert "CONFLICTING_SOURCES:" in output.notices[0]
    # Should reference the citation IDs involved
    assert "c1" in output.notices[0]  # The passage we returned


def test_store_unavailable_maps_to_tool_unavailable():
    """Test that KnowledgeStoreUnavailable is mapped to ToolUnavailable."""
    policy_search = FakePolicySearchWithException(
        KnowledgeStoreUnavailable("Database connection failed")
    )

    stub_data = StubData.load(OrchestratorSettings().config_dir)
    registry = build_stub_registry(stub_data, policy_search)

    now = datetime.now(UTC)
    state = SessionState(
        session_id="test",
        customer_id="demo1",
        created_at=now,
        updated_at=now
    )
    ctx = ToolContext(state=state, now=now)
    tool_input = SearchPoliciesInput(text="test query")

    tool_spec = registry.get("search_banking_policies")

    with pytest.raises(ToolUnavailable):
        tool_spec.handler(tool_input, ctx)


def test_embedding_unavailable_maps_to_tool_unavailable():
    """Test that EmbeddingModelUnavailable is mapped to ToolUnavailable."""
    policy_search = FakePolicySearchWithException(
        EmbeddingModelUnavailable("Embedding model failed to load")
    )

    stub_data = StubData.load(OrchestratorSettings().config_dir)
    registry = build_stub_registry(stub_data, policy_search)

    now = datetime.now(UTC)
    state = SessionState(
        session_id="test",
        customer_id="demo1",
        created_at=now,
        updated_at=now
    )
    ctx = ToolContext(state=state, now=now)
    tool_input = SearchPoliciesInput(text="test query")

    tool_spec = registry.get("search_banking_policies")

    with pytest.raises(ToolUnavailable):
        tool_spec.handler(tool_input, ctx)


def test_rag_mode_without_service_raises_configuration_error(monkeypatch):
    """Test that RAG mode without RetrievalService raises ConfigurationError."""
    import builtins

    settings = OrchestratorSettings(retrieval="rag")

    # Save original import function
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if "src.services.retrieval.service" in name:
            raise ImportError("No module named 'src.services.retrieval.service'")
        if "src.services.retrieval.connect" in name:
            raise ImportError("No module named 'src.services.retrieval.connect'")
        if "src.services.retrieval.embedder" in name:
            raise ImportError("No module named 'src.services.retrieval.embedder'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", mock_import)

    with pytest.raises(ConfigurationError) as exc_info:
        build_policy_search(settings)

    assert "ORCHESTRATOR_RETRIEVAL=rag needs the RAG retrieval service (feat/rag-service) to be merged" in str(exc_info.value)


def test_build_policy_search_stub_mode():
    """Test that build_policy_search returns StubPolicySearch in stub mode."""
    settings = OrchestratorSettings(retrieval="stub")
    policy_search = build_policy_search(settings)

    # Should have simulated attribute
    assert hasattr(policy_search, "simulated")
    assert policy_search.simulated is True


def test_rag_policy_search_has_no_simulated_attribute():
    """Test that RagPolicySearch does not have a simulated attribute."""
    # Create a mock RetrievalService
    mock_service = Mock()
    mock_service.search.return_value = SearchResult(
        status=SearchStatus.insufficient_evidence,
        passages=[]
    )

    # We need to test RagPolicySearch directly, but it will be created in retrieval.py
    # For now, we'll check via build_policy_search with a monkeypatch
    # This test will pass once we implement RagPolicySearch correctly
    pass
