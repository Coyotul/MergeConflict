"""Tests for stub tools and synthetic configuration."""
from datetime import datetime, UTC
from decimal import Decimal
from pathlib import Path

import pytest

from src.agent.orchestration.progress import can_run_eligibility, can_calculate_offers, fingerprint, offer_input_names
from src.agent.orchestration.state import (
    ApplicationState,
    SessionState,
    FieldValue,
    FieldSource,
    DocumentRecord,
    DocumentStatus,
    EligibilityRecord,
    Flow,
)
from src.agent.tools.contracts import (
    SearchPoliciesInput,
    GetCreditProductsInput,
    GetCustomerProfileInput,
    GetProductRequirementsInput,
    RunEligibilityInput,
    ProcessDocumentInput,
    CalculateOffersInput,
    CreateApplicationInput,
    SubmitApplicationInput,
    GetApplicationStatusInput,
    RequestHumanReviewInput,
)
from src.agent.tools.registry import ToolContext, ToolRegistry
from src.agent.tools.stubs import annuity_installment, StubData, build_stub_registry
from src.agent.tools.retrieval import StubPolicySearch
from src.models.chat import CitationRef
from src.models.credit import EligibilityStatus, ProductRequirements
from src.models.knowledge import Product, SearchQuery, SearchStatus
from tests.unit.orchestrator.factories import make_app


def test_annuity_known_values():
    """Test annuity installment calculation with known values."""
    assert annuity_installment(Decimal("30000"), Decimal("9.5"), 60) == Decimal("630.06")
    assert annuity_installment(Decimal("30000"), Decimal("9.5"), 36) == Decimal("960.99")
    assert annuity_installment(Decimal("10000"), Decimal("12"), 12) == Decimal("888.49")
    assert annuity_installment(Decimal("1200"), Decimal("0"), 12) == Decimal("100.00")


def test_offer_totals():
    """The registry uses engine totals, financed fees and rounded schedule rows."""
    # Minimum 8.55% base, no inferred discounts/insurance, 200 financed fee,
    # 5 RON monthly charges; net cash is 29,800, not the gross 30,000.

    config_dir = Path("config/orchestrator")
    data = StubData.load(config_dir)
    policy_search = StubPolicySearch(config_dir)
    registry = build_stub_registry(data, policy_search)

    # Build app with satisfied eligibility
    now = datetime.now(UTC)
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[],
            documents=[]
        ),
        fields={
            "amount": FieldValue(
                kind="money",
                value=Decimal("30000"),
                source=FieldSource.customer,
                confirmed=True,
                updated_at=now
            ),
            "term_months": FieldValue(
                kind="integer",
                value=60,
                source=FieldSource.customer,
                confirmed=True,
                updated_at=now
            ),
        }
    )

    # Add fake eligibility result
    app.eligibility = EligibilityRecord(
        result=data.eligibility_rules[Product.personal_loan].make_satisfied_result(),
        input_fingerprint=fingerprint(app, []),
        verified_inputs=True
    )

    state = SessionState(
        session_id="test",
        customer_id="cust-001",
        created_at=now,
        updated_at=now,
        active_flow=Flow.credit_application,
        application=app
    )

    ctx = ToolContext(state=state, now=now)
    outcome, output = registry.execute(
        "calculate_loan_offer",
        {"term_options_months": []},
        ctx,
        caller="model"
    )

    assert outcome.ok
    assert len(output.offers) >= 1

    # Find the 60-month offer
    offer_60m = next((o for o in output.offers if o.term_months == 60), None)
    assert offer_60m is not None
    assert offer_60m.monthly_installment.amount == Decimal("621.22")
    assert offer_60m.total_repayment.amount == Decimal("37273.16")
    assert offer_60m.total_cost.amount == Decimal("7473.16")
    assert offer_60m.fees.amount == Decimal("500.00")
    assert any("DAE/APR: 9.58%" in text for text in offer_60m.assumptions)


def test_eligibility_outcomes_per_customer():
    """Test eligibility outcomes for each synthetic customer."""
    config_dir = Path("config/orchestrator")
    data = StubData.load(config_dir)
    policy_search = StubPolicySearch(config_dir)
    registry = build_stub_registry(data, policy_search)

    now = datetime.now(UTC)

    # Helper to build state for customer
    def make_state(customer_id: str) -> SessionState:
        cust = data.customers[customer_id]
        app = make_app(
            product_code=Product.personal_loan,
            requirements=data.requirements[Product.personal_loan],
            fields={
                "full_name": FieldValue(
                    kind="text",
                    value=cust["documents"]["id_card"]["full_name"],
                    source=FieldSource.document,
                    confirmed=True,
                    updated_at=now
                ),
                "age": FieldValue(
                    kind="integer",
                    value=cust["documents"]["id_card"]["age"],
                    source=FieldSource.document,
                    confirmed=True,
                    updated_at=now
                ),
                "employment_type": FieldValue(
                    kind="text",
                    value=cust["stated"]["employment_type"],
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                ),
                "employment_months": FieldValue(
                    kind="integer",
                    value=cust["stated"]["employment_months"],
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                ),
                "monthly_net_income": FieldValue(
                    kind="money",
                    value=Decimal(str(cust["documents"]["payslip"]["monthly_net_income"])),
                    source=FieldSource.document,
                    confirmed=True,
                    updated_at=now
                ),
                "employer_name": FieldValue(
                    kind="text",
                    value=cust["documents"]["payslip"]["employer_name"],
                    source=FieldSource.document,
                    confirmed=True,
                    updated_at=now
                ),
                "existing_monthly_obligations": FieldValue(
                    kind="money",
                    value=Decimal(str(cust["documents"]["bank_statement"]["existing_monthly_obligations"])),
                    source=FieldSource.document,
                    confirmed=True,
                    updated_at=now
                ),
                "amount": FieldValue(
                    kind="money",
                    value=Decimal("30000"),
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                ),
                "term_months": FieldValue(
                    kind="integer",
                    value=60,
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                ),
            }
        )
        return SessionState(
            session_id="test",
            customer_id=customer_id,
            created_at=now,
            updated_at=now,
            active_flow=Flow.credit_application,
            application=app
        )

    # Test cust-001: should be satisfied
    state_001 = make_state("cust-001")
    ctx_001 = ToolContext(state=state_001, now=now)
    outcome_001, output_001 = registry.execute("run_eligibility_check", {}, ctx_001, caller="model")
    assert outcome_001.ok
    assert output_001.status == EligibilityStatus.satisfied

    # Test cust-002: should be not_satisfied with income_below_minimum
    state_002 = make_state("cust-002")
    ctx_002 = ToolContext(state=state_002, now=now)
    outcome_002, output_002 = registry.execute("run_eligibility_check", {}, ctx_002, caller="model")
    assert outcome_002.ok
    assert output_002.status == EligibilityStatus.not_satisfied
    assert any(r.code == "income_below_minimum" for r in output_002.reasons)

    # Test cust-003: should be manual_review (self_employed)
    state_003 = make_state("cust-003")
    ctx_003 = ToolContext(state=state_003, now=now)
    outcome_003, output_003 = registry.execute("run_eligibility_check", {}, ctx_003, caller="model")
    assert outcome_003.ok
    assert output_003.status == EligibilityStatus.manual_review
    assert any(r.code == "self_employed_manual_review" for r in output_003.reasons)


def test_process_document_reject_hook_and_empty():
    """Test process_document rejection hooks."""
    config_dir = Path("config/orchestrator")
    data = StubData.load(config_dir)
    policy_search = StubPolicySearch(config_dir)
    registry = build_stub_registry(data, policy_search)

    now = datetime.now(UTC)
    app = make_app(product_code=Product.personal_loan)
    state = SessionState(
        session_id="test",
        customer_id="cust-001",
        created_at=now,
        updated_at=now,
        active_flow=Flow.credit_application,
        application=app
    )
    ctx = ToolContext(state=state, now=now)

    # Test empty file rejection
    outcome_empty, output_empty = registry.execute(
        "process_document",
        {
            "document_id": "doc1",
            "doc_type": "id_card",
            "filename": "empty.pdf",
            "size_bytes": 0
        },
        ctx,
        caller="code"
    )
    assert outcome_empty.ok
    assert output_empty.status == "rejected"
    assert output_empty.rejection_reason == "The file is empty."

    # Test reject_ prefix rejection
    outcome_reject, output_reject = registry.execute(
        "process_document",
        {
            "document_id": "doc2",
            "doc_type": "id_card",
            "filename": "reject_blurry.pdf",
            "size_bytes": 1024
        },
        ctx,
        caller="code"
    )
    assert outcome_reject.ok
    assert output_reject.status == "rejected"
    assert output_reject.rejection_reason == "The document is unreadable; please upload a clearer copy."


def test_search_assigns_citation_ids_and_insufficient():
    """Test that search assigns citation IDs and handles insufficient evidence."""
    config_dir = Path("config/orchestrator")
    data = StubData.load(config_dir)
    policy_search = StubPolicySearch(config_dir)
    registry = build_stub_registry(data, policy_search)

    now = datetime.now(UTC)
    state = SessionState(
        session_id="test",
        customer_id="cust-001",
        created_at=now,
        updated_at=now,
        active_flow=Flow.product_info
    )
    ctx = ToolContext(state=state, now=now)

    # Valid search should assign citation IDs
    outcome1, output1 = registry.execute(
        "search_banking_policies",
        {"text": "early repayment documents"},
        ctx,
        caller="model"
    )
    assert outcome1.ok
    assert output1.status == "ok"
    assert len(output1.passages) > 0
    assert output1.simulated is True

    # Check citation IDs are assigned and stored
    for passage in output1.passages:
        assert passage.citation_id.startswith("c")
        assert passage.citation_id in state.retrieved_sources

    # Nonsense query should return insufficient_evidence
    outcome2, output2 = registry.execute(
        "search_banking_policies",
        {"text": "xyzzy quantum flibbertigibbet"},
        ctx,
        caller="model"
    )
    assert outcome2.ok
    assert output2.status == "insufficient_evidence"
    assert len(output2.passages) == 0


def test_registry_flags_match_table():
    """Test that model_callable flags match the table in the brief."""
    config_dir = Path("config/orchestrator")
    data = StubData.load(config_dir)
    policy_search = StubPolicySearch(config_dir)
    registry = build_stub_registry(data, policy_search)

    # Expected model-callable tools from the table
    expected_model_callable = {
        "submit_application",
        "search_banking_policies",
        "get_credit_products",
        "get_customer_profile",
        "run_eligibility_check",
        "calculate_loan_offer",
        "get_application_status",
        "request_human_review",
    }

    # Check each tool
    all_tools = {
        "search_banking_policies",
        "get_credit_products",
        "get_customer_profile",
        "get_product_requirements",
        "run_eligibility_check",
        "process_document",
        "calculate_loan_offer",
        "create_loan_application",
        "submit_application",
        "get_application_status",
        "request_human_review",
    }

    actual_model_callable = set()
    for tool_name in all_tools:
        spec = registry.get(tool_name)
        assert spec is not None, f"Tool {tool_name} not registered"
        if spec.model_callable:
            actual_model_callable.add(tool_name)

    assert actual_model_callable == expected_model_callable


def test_config_files_load():
    """Test that config files load and have expected structure."""
    config_dir = Path("config/orchestrator")
    data = StubData.load(config_dir)

    # Check products
    assert len(data.products) == 3
    assert Product.personal_loan in data.products
    assert Product.refinancing_unsecured in data.products
    assert Product.mortgage_casa_ta in data.products

    # Check customers
    assert len(data.customers) >= 3
    assert "cust-001" in data.customers
    assert "cust-002" in data.customers
    assert "cust-003" in data.customers

    # Check customer structure
    cust_001 = data.customers["cust-001"]
    assert "profile" in cust_001
    assert "stated" in cust_001
    assert "documents" in cust_001
    assert cust_001["profile"]["full_name"] == "Ana Popescu"
    assert cust_001["profile"]["age"] == 34

    # Check requirements
    assert len(data.requirements) == 3
    assert Product.personal_loan in data.requirements

    # Check eligibility rules
    assert len(data.eligibility_rules) == 3
    rule = data.eligibility_rules[Product.personal_loan]
    assert rule.min_age == 18
    assert rule.max_age_at_maturity == 70
    assert rule.min_monthly_income == Decimal("2500")
    assert rule.max_dti == Decimal("0.40")


def test_request_human_review_sets_escalation():
    """Test that request_human_review sets state.escalation."""
    config_dir = Path("config/orchestrator")
    data = StubData.load(config_dir)
    policy_search = StubPolicySearch(config_dir)
    registry = build_stub_registry(data, policy_search)

    now = datetime.now(UTC)
    state = SessionState(
        session_id="test",
        customer_id="cust-001",
        created_at=now,
        updated_at=now,
        active_flow=Flow.product_info
    )
    ctx = ToolContext(state=state, now=now)

    # Initially no escalation
    assert state.escalation is None

    # Request review
    outcome, output = registry.execute(
        "request_human_review",
        {"reason": "Customer needs assistance with complex case"},
        ctx,
        caller="model"
    )

    assert outcome.ok
    assert "representative" in output.message

    # Check escalation is set
    assert state.escalation is not None
    assert state.escalation.reason == "Customer needs assistance with complex case"
    assert state.escalation.created_at == now
    # No timeline promise: a representative follows up.
    assert "business day" not in output.message
    assert "representative" in output.message


def test_synthetic_passages_are_neutral():
    """Stub passages carry no bank voice and no incorrect facts."""
    import yaml

    passages = yaml.safe_load(Path("config/orchestrator/policy_passages.yaml").read_text(encoding="utf-8"))["passages"]
    texts = {p["topic"]: p["text"] for p in passages}
    assert all(p["publisher"] == "Synthetic stub" for p in passages)
    assert not any(t.startswith("Our ") or " our " in t.lower() for t in texts.values())
    assert "without penalties" not in texts["early_repayment"]
    assert "fee" in texts["early_repayment"]
    assert "Interbank" not in texts["variable_rate_ircc"]
    assert "consumer credit" in texts["variable_rate_ircc"]
    assert "BNR" in texts["variable_rate_ircc"]


def test_non_stub_policy_search_not_simulated():
    """Test that non-stub PolicySearch results in simulated=False."""
    from src.models.knowledge import SearchResult, SearchStatus

    config_dir = Path("config/orchestrator")
    data = StubData.load(config_dir)

    # Create a fake non-stub policy search
    class FakePolicySearch:
        def search(self, query):
            return SearchResult(status=SearchStatus.ok, passages=[])

    fake_search = FakePolicySearch()
    registry = build_stub_registry(data, fake_search)

    now = datetime.now(UTC)
    state = SessionState(
        session_id="test",
        customer_id="cust-001",
        created_at=now,
        updated_at=now,
        active_flow=Flow.product_info
    )
    ctx = ToolContext(state=state, now=now)

    # Initially used_stubs is False
    assert state.used_stubs is False

    # Search
    outcome, output = registry.execute(
        "search_banking_policies",
        {"text": "test query"},
        ctx,
        caller="model"
    )

    assert outcome.ok
    assert output.simulated is False
    assert state.used_stubs is False


def test_offer_term_ordering_and_explicit_limit_rejections():
    """Valid requested term first; no silent clamping to different loan terms."""
    config_dir = Path("config/orchestrator")
    data = StubData.load(config_dir)
    policy_search = StubPolicySearch(config_dir)
    registry = build_stub_registry(data, policy_search)

    now = datetime.now(UTC)

    # Helper to build state with specific term and check offer terms
    def check_offers(term_months: int, options: list[int] | None, expected_terms: list[int]):
        app = make_app(
            product_code=Product.personal_loan,
            requirements=ProductRequirements(
                product_code=Product.personal_loan,
                fields=[],
                documents=[]
            ),
            fields={
                "amount": FieldValue(
                    kind="money",
                    value=Decimal("30000"),
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                ),
                "term_months": FieldValue(
                    kind="integer",
                    value=term_months,
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                ),
            }
        )
        app.eligibility = EligibilityRecord(
            result=data.eligibility_rules[Product.personal_loan].make_satisfied_result(),
            input_fingerprint=fingerprint(app, []),
            verified_inputs=True
        )

        state = SessionState(
            session_id="test",
            customer_id="cust-001",
            created_at=now,
            updated_at=now,
            active_flow=Flow.credit_application,
            application=app
        )
        ctx = ToolContext(state=state, now=now)

        outcome, output = registry.execute(
            "calculate_loan_offer",
            {"term_options_months": options},
            ctx,
            caller="model"
        )

        assert outcome.ok
        actual_terms = [o.term_months for o in output.offers]
        assert actual_terms == expected_terms, f"Expected {expected_terms}, got {actual_terms}"
        if not expected_terms:
            assert output.status == "invalid"
            assert output.errors[0].code == "TERM_OUT_OF_RANGE"
        assert app.fields["term_months"].value == term_months

    check_offers(60, [12, 24], [60, 24])
    check_offers(100, None, [])
    check_offers(60, [60, 48], [60, 48])
    check_offers(3, None, [])
    check_offers(60, [18, 84], [60, 18])
    check_offers(200, [36, 60], [])


def test_stub_search_matches_word_forms():
    """Inflected forms ('documente') match passage words ('documents')."""
    from src.models.knowledge import SearchQuery, SearchStatus

    search = StubPolicySearch(Path("config/orchestrator"))
    result = search.search(SearchQuery(text="Ce documente îmi trebuie?"))
    assert result.status == SearchStatus.ok
    assert result.passages[0].header == "Required Documents for Personal Loans"
    # a short shared stem is not a match
    assert search.search(SearchQuery(text="xyzzy docu")).status == SearchStatus.insufficient_evidence
