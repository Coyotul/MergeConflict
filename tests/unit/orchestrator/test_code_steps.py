"""Deterministic steps the orchestrator takes itself: stale eligibility re-runs, product resets."""
from decimal import Decimal

from src.agent.orchestration.orchestrator import CustomerMessage
from src.agent.orchestration.progress import NeedKind, next_needs
from src.models.credit import EligibilityStatus
from src.models.knowledge import Product
from tests.unit.orchestrator.factories import call, make_collecting_app, make_verified_app, respond, seed_application

CUSTOMER = "cust-alex-morgan"
GREET = respond("Hello! How can I help?")
ELIGIBILITY_FIELDS = {
    "employment_type": "employed", "employment_months": 48,
    "monthly_net_income": Decimal("7000"), "employer_name": "TechCorp SRL",
    "existing_monthly_obligations": Decimal("0"),
}


def joined(messages) -> str:
    return "\n".join(m.content for m in messages)


def test_stale_eligibility_runs_before_the_model_is_asked(orchestrator_factory, stub_data):
    """Offers no longer depend on the model remembering to re-run eligibility first."""
    orch, store, model = orchestrator_factory([
        GREET,
        call("calculate_loan_offer"),
        respond("Here are your offers.", intent="credit_application"),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    seed_application(store, sid, make_verified_app(stub_data.requirements[Product.personal_loan]))

    orch.handle(sid, CUSTOMER, CustomerMessage("Show me the offers"))

    app = store.get(sid).application
    assert app.eligibility.result.status == EligibilityStatus.satisfied
    assert app.eligibility.verified_inputs is True
    assert app.offers is not None and len(app.offers.offers) >= 1
    assert "TOOL_REJECTED calculate_loan_offer" not in joined(model.calls[-1])


def test_eligibility_runs_when_the_last_required_field_arrives(orchestrator_factory, stub_data):
    requirements = stub_data.requirements[Product.personal_loan]
    values = dict(ELIGIBILITY_FIELDS)
    values.pop("existing_monthly_obligations")
    orch, store, model = orchestrator_factory([
        GREET,
        respond("Thanks, checking now.", intent="credit_application",
                updates=[{"field": "existing_monthly_obligations", "value": "0 RON"}]),
        respond("Here is the result.", intent="credit_application"),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    app = make_collecting_app(requirements, values)
    app.fields.update(make_verified_app(requirements).fields)  # identity fields as the profile sets them
    for name in ("existing_monthly_obligations",):
        app.fields.pop(name, None)
    seed_application(store, sid, app)

    orch.handle(sid, CUSTOMER, CustomerMessage("No other loans, 0 RON"))

    assert store.get(sid).application.eligibility is not None


def test_reply_is_rewritten_after_eligibility_runs_from_its_own_updates(orchestrator_factory, stub_data):
    """A reply written before the result existed gets one more step, with the result shown."""
    requirements = stub_data.requirements[Product.personal_loan]
    values = dict(ELIGIBILITY_FIELDS)
    values.pop("existing_monthly_obligations")
    orch, store, model = orchestrator_factory([
        GREET,
        respond("Thanks!", intent="credit_application",
                updates=[{"field": "existing_monthly_obligations", "value": "0 RON"}]),
        respond("You meet the preliminary conditions.", intent="credit_application"),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    app = make_collecting_app(requirements, values)
    app.fields.update({k: v for k, v in make_verified_app(requirements).fields.items() if k in ("full_name", "age")})
    seed_application(store, sid, app)

    resp = orch.handle(sid, CUSTOMER, CustomerMessage("No other loans, 0 RON"))

    last_prompt = joined(model.calls[-1])
    assert "TOOL_RESULT run_eligibility_check" in last_prompt
    assert "ELIGIBILITY_UPDATED" in last_prompt
    assert resp.messages[-1].text == "You meet the preliminary conditions."


def test_eligibility_not_run_while_fields_are_missing(orchestrator_factory, stub_data):
    orch, store, model = orchestrator_factory([GREET, respond("What is your income?", intent="credit_application")])
    sid = orch.start_session(CUSTOMER).session_id
    seed_application(store, sid, make_collecting_app(stub_data.requirements[Product.personal_loan]))

    orch.handle(sid, CUSTOMER, CustomerMessage("I want a loan"))

    assert store.get(sid).application.eligibility is None


def test_purpose_change_resets_the_product(orchestrator_factory, stub_data):
    """A new purpose without a product decision brings back choose_product; nothing downstream survives."""
    orch, store, model = orchestrator_factory([
        GREET,
        respond("Noted, a flat.", intent="credit_application",
                updates=[{"field": "purpose", "value": "buying a flat"},
                         {"field": "amount", "value": "300000 RON"}]),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    seed_application(store, sid, make_verified_app(stub_data.requirements[Product.personal_loan]))

    orch.handle(sid, CUSTOMER, CustomerMessage("Actually I'd rather buy a flat"))

    state = store.get(sid)
    app = state.application
    assert app.product_code is None
    assert app.requirements is None and app.eligibility is None and app.offers is None
    assert app.fields["amount"].value == Decimal("300000")  # stated values are kept
    assert next_needs(state)[0].kind == NeedKind.choose_product


def test_purpose_change_with_a_new_product_keeps_the_new_product(orchestrator_factory, stub_data):
    orch, store, model = orchestrator_factory([
        GREET,
        respond("Switching to a mortgage.", intent="credit_application",
                updates=[{"field": "purpose", "value": "buying a flat"},
                         {"field": "product_code", "value": "mortgage_casa_ta"}]),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    seed_application(store, sid, make_verified_app(stub_data.requirements[Product.personal_loan]))

    orch.handle(sid, CUSTOMER, CustomerMessage("Actually I'd rather buy a flat"))

    app = store.get(sid).application
    assert app.product_code == Product.mortgage_casa_ta
    assert app.requirements.product_code == Product.mortgage_casa_ta


def test_same_purpose_restated_keeps_the_product(orchestrator_factory, stub_data):
    orch, store, model = orchestrator_factory([
        GREET,
        respond("Yes, renovation.", intent="credit_application",
                updates=[{"field": "purpose", "value": " Renovation "}]),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    seed_application(store, sid, make_verified_app(stub_data.requirements[Product.personal_loan]))

    orch.handle(sid, CUSTOMER, CustomerMessage("It's for the renovation"))

    assert store.get(sid).application.product_code == Product.personal_loan
