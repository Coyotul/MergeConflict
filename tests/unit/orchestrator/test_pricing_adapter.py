"""Real service -> registered tool -> offer/state contract regression tests."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from src.agent.orchestration.progress import eligibility_input_names, fingerprint
from src.agent.orchestration.prompting import build_context
from src.agent.orchestration.actions import Respond, parse_model_output
from src.agent.orchestration.demo_model import DemoChatModel
from src.agent.orchestration.state import EligibilityRecord, FieldSource, FieldValue, Flow, OffersRecord, SessionState
from src.agent.tools import pricing
from src.agent.tools.contracts import CalculateOffersInput
from src.agent.tools.registry import ToolContext, ToolErrorCode
from src.agent.tools.retrieval import StubPolicySearch
from src.agent.tools.stubs import build_stub_registry
from src.models.credit import EligibilityStatus
from src.models.knowledge import Product
from src.services.pricing.models import DISCLAIMER, LoanOfferRequest
from src.services.pricing.service import calculate_loan_offer
from src.integrations.llm.chat import ChatMessage
from tests.unit.orchestrator.conftest import CONFIG_DIR
from tests.unit.orchestrator.factories import make_verified_app

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.fixture
def pricing_context(stub_data):
    def make(code=Product.personal_loan, amount="30000", term=60, now=NOW):
        app = make_verified_app(stub_data.requirements[code], now)
        app.fields["amount"].value = Decimal(amount)
        app.fields["term_months"].value = term
        if code == Product.mortgage_casa_ta:
            app.fields["property_value"] = FieldValue(
                kind="money", value=Decimal("500000"), source=FieldSource.document,
                document_id="doc-property_valuation", confirmed=True, updated_at=now,
            )
        app.eligibility = EligibilityRecord(
            result=stub_data.eligibility_rules[code].make_satisfied_result(),
            input_fingerprint=fingerprint(app, eligibility_input_names(app)), verified_inputs=True,
        )
        return ToolContext(state=SessionState(
            session_id="pricing-session", customer_id="cust-001", created_at=now, updated_at=now,
            active_flow=Flow.credit_application, application=app,
        ), now=now)
    return make


@pytest.fixture
def registry(stub_data):
    return build_stub_registry(stub_data, StubPolicySearch(CONFIG_DIR))


@pytest.mark.parametrize("code,amount,term", [
    (Product.personal_loan, "30000", 60),
    (Product.refinancing_unsecured, "50000", 120),
    (Product.mortgage_casa_ta, "350900", 300),
])
def test_registered_tool_matches_engine_without_recalculating(registry, pricing_context, code, amount, term):
    ctx = pricing_context(code, amount, term)
    before = ctx.state.model_dump(mode="json")
    expected = calculate_loan_offer(LoanOfferRequest(
        product_id=pricing.PRODUCT_IDS[code], amount=Decimal(amount), term_months=term,
        simulation_date=NOW.date(), net_monthly_income=Decimal("6200"),
        existing_monthly_debt_payments=Decimal("400"),
        property_value=Decimal("500000") if code == Product.mortgage_casa_ta else None,
    ))
    outcome, result = registry.execute("calculate_loan_offer", {}, ctx, caller="model")
    assert outcome.ok and result.status == "ok"
    offer = result.offers[0]
    assert offer.product_code == code
    assert offer.monthly_installment.amount == expected.first_monthly_payment
    assert offer.annual_interest_rate_percent == expected.rate.rate_periods[0].annual_rate
    assert offer.total_repayment.amount == expected.totals.total_payable
    assert offer.total_cost.amount == expected.totals.total_cost_of_credit
    assert offer.fees.amount == sum((fee.amount for fee in expected.fees), Decimal(0)) + expected.totals.monthly_charges
    assert all(text in offer.assumptions for text in expected.assumptions + expected.warnings + [DISCLAIMER])
    assert any(f"DAE/APR: {expected.dae}%" in text for text in offer.assumptions)
    assert any(f"Net amount paid out: {expected.net_amount_paid_out}" in text for text in offer.assumptions)
    assert offer.indicative and offer.simulated
    assert outcome.output["offers"][0]["monthly_installment"]["amount"] == str(expected.first_monthly_payment)
    assert ctx.state.model_dump(mode="json") == before  # handler does not create/submit/change eligibility


def test_mortgage_discloses_future_payment_incomplete_dae_and_ltv(registry, pricing_context):
    ctx = pricing_context(Product.mortgage_casa_ta, "350900", 300)
    ctx.state.application.fields["property_value"].value = Decimal("360000")
    ctx.state.application.eligibility.input_fingerprint = fingerprint(ctx.state.application, eligibility_input_names(ctx.state.application))
    _, result = registry.execute("calculate_loan_offer", {}, ctx, caller="model")
    offer = result.offers[0]
    assert offer.monthly_installment.amount == Decimal("2155.79")
    assert any("2713.05 RON" in text for text in offer.assumptions)
    assert any("DAE_INCOMPLETE" in text for text in offer.assumptions)
    assert any("LTV_ABOVE_LIMIT" in text for text in offer.assumptions)
    assert any("not a stress test" in text for text in offer.assumptions)


def test_explicit_utc_simulation_date_and_no_inferred_options(registry, pricing_context, monkeypatch):
    now = datetime(2026, 10, 1, 0, 30, tzinfo=timezone(timedelta(hours=3)))
    ctx = pricing_context(Product.mortgage_casa_ta, "350900", 300, now)
    original = pricing.pricing_service.calculate_loan_offer
    calls = []
    def capture(request):
        calls.append(request)
        return original(request)
    monkeypatch.setattr(pricing.pricing_service, "calculate_loan_offer", capture)
    outcome, result = registry.execute("calculate_loan_offer", {}, ctx, caller="model")
    assert outcome.ok and result.status == "ok"
    assert calls[0].simulation_date.isoformat() == "2026-09-30"
    assert calls[0].salary_account.value == "none"
    assert calls[0].with_insurance is False and calls[0].first_home is False
    assert calls[0].base_annual_rate is None
    assert any("IRCC 5.56%" in text for text in result.offers[0].assumptions)


@pytest.mark.parametrize("arguments", [
    {"amount": "1"}, {"product_id": "../../settings"}, {"simulation_date": "2020-01-01"},
    {"base_annual_rate": "0"}, {"with_insurance": True}, {"customer_id": "cust-002"},
    {"salary_account": "premium"}, {"term_options_months": [True]}, {"term_options_months": [18.5]},
    {"term_options_months": ["36"]}, {"term_options_months": [12, 18, 24, 36]},
])
def test_tool_rejects_injected_trusted_fields_and_noninteger_options(registry, pricing_context, arguments):
    ctx = pricing_context()
    before = ctx.state.model_dump(mode="json")
    outcome, output = registry.execute("calculate_loan_offer", arguments, ctx, caller="model")
    assert not outcome.ok and outcome.error_code == ToolErrorCode.invalid_arguments and output is None
    assert ctx.state.model_dump(mode="json") == before


@pytest.mark.parametrize("code,amount,term,error", [
    (Product.personal_loan, "2499.99", 60, "AMOUNT_OUT_OF_RANGE"),
    (Product.personal_loan, "250000.01", 60, "AMOUNT_OUT_OF_RANGE"),
    (Product.personal_loan, "30000", 84, "TERM_OUT_OF_RANGE"),
    (Product.refinancing_unsecured, "30000", 12, "TERM_OUT_OF_RANGE"),
    (Product.mortgage_casa_ta, "350900", 36, "TERM_TOO_SHORT"),
])
def test_primary_request_is_not_silently_clamped(registry, pricing_context, code, amount, term, error):
    ctx = pricing_context(code, amount, term)
    outcome, output = registry.execute("calculate_loan_offer", {"term_options_months": [60]}, ctx, caller="model")
    assert outcome.ok and output.status == "invalid" and output.offers == []
    assert output.errors[0].code == error
    assert ctx.state.application.fields["term_months"].value == term
    assert ctx.state.application.fields["amount"].value == Decimal(amount)


def test_terms_deduplicate_keep_order_and_disclose_invalid_alternatives(registry, pricing_context):
    ctx = pricing_context()
    _, output = registry.execute("calculate_loan_offer", {"term_options_months": [60, 12, 48]}, ctx, caller="model")
    assert [offer.term_months for offer in output.offers] == [60, 48]
    assert [(e.term_months, e.code) for e in output.errors] == [(12, "TERM_OUT_OF_RANGE")]
    assert all(any("Alternative 12 months" in text for text in offer.assumptions) for offer in output.offers)


def test_missing_ircc_is_typed_failure_not_guessed_rate(registry, pricing_context):
    ctx = pricing_context(Product.mortgage_casa_ta, "350900", 300, datetime(2030, 1, 1, tzinfo=UTC))
    outcome, output = registry.execute("calculate_loan_offer", {}, ctx, caller="model")
    assert outcome.ok and output.status == "invalid" and output.offers == []
    assert output.errors[0].code == "INDEX_UNAVAILABLE"


def test_config_unavailable_returns_registry_error_not_old_stub(registry, pricing_context, monkeypatch):
    def missing(_):
        raise FileNotFoundError("private/config/path")
    monkeypatch.setattr(pricing.pricing_service, "load_product", missing)
    outcome, output = registry.execute("calculate_loan_offer", {}, pricing_context(), caller="model")
    assert outcome.error_code == ToolErrorCode.tool_unavailable and output is None
    assert "private/config/path" not in outcome.error_message


@pytest.mark.parametrize("mutation", ["eligibility_missing", "not_satisfied", "unverified", "document_rejected", "submitted"])
def test_pricing_preserves_eligibility_document_and_submission_gates(registry, pricing_context, mutation):
    ctx = pricing_context()
    app = ctx.state.application
    if mutation == "eligibility_missing":
        app.eligibility = None
    elif mutation == "not_satisfied":
        app.eligibility.result.status = EligibilityStatus.not_satisfied
    elif mutation == "unverified":
        app.eligibility.verified_inputs = False
    elif mutation == "document_rejected":
        app.documents[1].status = "rejected"
    else:
        app.application_id = "APP-existing"
    outcome, output = registry.execute("calculate_loan_offer", {}, ctx, caller="model")
    assert outcome.error_code == ToolErrorCode.precondition_failed and output is None


def test_stable_ids_include_date_product_version_and_pricing_result(registry, pricing_context, monkeypatch):
    ctx = pricing_context()
    def ident():
        return registry.execute("calculate_loan_offer", {}, ctx, caller="model")[1].offers[0].offer_id
    first = ident()
    assert ident() == first
    ctx.now = NOW + timedelta(days=1)
    assert ident() != first
    ctx.now = NOW
    original = pricing.pricing_service.calculate_loan_offer
    def changed_version(request):
        return original(request).model_copy(update={"product_version": "new-reviewed-version"})
    monkeypatch.setattr(pricing.pricing_service, "calculate_loan_offer", changed_version)
    assert ident() != first


def test_catalog_uses_engine_ranges_not_obsolete_stub_yaml(registry, pricing_context):
    outcome, output = registry.execute("get_credit_products", {}, pricing_context(), caller="model")
    assert outcome.ok
    for product in output.products:
        configured = pricing.pricing_service.load_product(pricing.PRODUCT_IDS[product.code])
        assert product.min_amount.amount == configured.amount.min
        assert product.max_amount.amount == configured.amount.max
        assert product.max_term_months == configured.term_months.max
        assert configured.version in product.rate_note
    personal = next(p for p in output.products if p.code == Product.personal_loan)
    assert (personal.min_term_months, personal.max_term_months) == (18, 60)


def test_income_missing_is_not_invented_as_affordability_pass(pricing_context):
    ctx = pricing_context()
    del ctx.state.application.fields["monthly_net_income"]
    output = pricing.calculate_offers(CalculateOffersInput(), ctx)
    assert output.status == "ok"
    assert any("Affordability is not calculated" in text for text in output.offers[0].assumptions)
    assert not any("within limit: true" in text for text in output.offers[0].assumptions)


def test_allowlist_does_not_expose_uncollected_existing_loan_simulations(registry, pricing_context):
    names = {spec.name for spec in registry.model_tools(pricing_context().state)}
    assert "calculate_loan_offer" in names
    assert "simulate_early_repayment" not in names
    assert "compare_refinancing_options" not in names


def test_three_mortgage_offers_fit_mock_reply_without_losing_warnings(registry, pricing_context):
    import json

    ctx = pricing_context(Product.mortgage_casa_ta, "350900", 300)
    outcome, output = registry.execute("calculate_loan_offer", {"term_options_months": [240, 360]}, ctx, caller="model")
    assert outcome.ok and len(output.offers) == 3
    ctx.state.application.offers = OffersRecord(offers=output.offers, input_fingerprint="test")
    context = build_context(ctx.state, [], [], [])
    messages = [ChatMessage(role="user", content="Show my mortgage simulations"),
                ChatMessage(role="assistant", content="{}"),
                ChatMessage(role="user", content=outcome.as_message()),
                ChatMessage(role="system", content="CONTEXT_JSON: " + json.dumps(context))]
    action = parse_model_output(DemoChatModel().complete(messages))
    assert isinstance(action.action, Respond)
    assert len(action.action.message) <= 4000
    assert "DAE_INCOMPLETE" in action.action.message and DISCLAIMER in action.action.message
    for offer in output.offers:
        assert str(offer.monthly_installment.amount) in action.action.message
        assert f"{offer.term_months} luni:" in action.action.message


def test_unaffordable_simulation_does_not_rewrite_eligibility(registry, pricing_context):
    ctx = pricing_context()
    app = ctx.state.application
    app.fields["monthly_net_income"].value = Decimal("1000")
    app.fields["existing_monthly_obligations"].value = Decimal("900")
    app.eligibility.input_fingerprint = fingerprint(app, eligibility_input_names(app))
    original = app.eligibility.model_dump(mode="json")
    outcome, output = registry.execute("calculate_loan_offer", {}, ctx, caller="model")
    assert outcome.ok and output.status == "ok"
    assert any("within limit: false" in text for text in output.offers[0].assumptions)
    assert app.eligibility.model_dump(mode="json") == original
    assert app.application_id is None