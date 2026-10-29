from src.agent.tools.registry import ToolContext
"""Session-owned pricing through real composition, API, offers and confirmation."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.agent.orchestration.progress import eligibility_input_names, fingerprint
from src.agent.orchestration.prompting import build_context
from src.agent.orchestration.state import EligibilityRecord, SessionState
from src.agent.tools import pricing
from src.api.app import create_app
from src.core.composition import build_orchestrator
from src.core.settings import OrchestratorSettings
from src.integrations.llm.chat import FakeChatModel
from src.models.knowledge import Product
from src.services.conversations.store import InMemorySessionStore
from src.services.pricing.models import DISCLAIMER
from src.agent.tools.stubs import StubData
from tests.unit.orchestrator.factories import call, make_verified_app, respond, seed_application
from tests.fixtures import documents as _docs
from tests.fixtures.documents import image_bytes, pdf_bytes  # noqa: F401

# Documents for the demo customer cust-alex-morgan: the name matches the profile, the CNP is
# checksum-valid with Alex's birth date (1988-04-12, so 38 at the 2026-10-28 reference date).
CNP = _docs.cnp_for("188041241001")


def identity_text(**kw):
    return _docs.identity_text(**{"first_name": "ALEX", "last_name": "MORGAN", "cnp": CNP, **kw})


def income_text(**kw):
    return _docs.income_text(**{"name": "ALEX MORGAN", "cnp": CNP, **kw})


def statement_text(**kw):
    return _docs.statement_text(**{"holder": "ALEX MORGAN", **kw})


def document_bytes(doc_type):
    return _docs.document_bytes(doc_type, first_name="ALEX", last_name="MORGAN", cnp=CNP)
from src.agent.tools.documents import DOCUMENT_KINDS


ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
CUSTOMER = "cust-alex-morgan"


@pytest.fixture
def priced_chat(tmp_path):
    data = StubData.load(ROOT / "config" / "orchestrator")
    app = make_verified_app(data.requirements[Product.personal_loan], NOW)
    app.fields["term_months"].value = 60
    app.eligibility = EligibilityRecord(
        result=data.eligibility_rules[Product.personal_loan].make_satisfied_result(),
        input_fingerprint=fingerprint(app, eligibility_input_names(app)), verified_inputs=True,
    )
    # Fully offline scripted model; the pricing service/registry/composition are real.
    model = FakeChatModel([
        respond("Hello"),
        call("calculate_loan_offer", {"term_options_months": [36]}), respond("Select a simulation"),
        respond("Review and confirm"),
        call("calculate_loan_offer"), respond("Updated pricing"),
        respond("The old offer is not current"),
    ])
    settings = OrchestratorSettings(model="fake", session_store="memory", retrieval="stub",
                                    config_dir=ROOT / "config" / "orchestrator",
                                    uploads_dir=tmp_path / "uploads")
    store = InMemorySessionStore()
    orchestrator = build_orchestrator(settings, model=model, store=store, clock=lambda: NOW)
    with TestClient(create_app(settings, orchestrator=orchestrator)) as client:
        headers = {"X-Customer-Id": CUSTOMER}
        response = client.post("/chat/sessions", json={}, headers=headers)
        assert response.status_code == 201
        sid = response.json()["session_id"]
        doc_tools = orchestrator._registry.get("process_document").handler.__self__
        ctx = ToolContext(state=store.get(sid), now=NOW)
        for doc in app.documents:
            raw = document_bytes(doc.doc_type)
            stored = doc_tools.service.storage.store_document(
                customer_id=CUSTOMER, session_id=sid, document_id=doc.document_id,
                filename=doc.filename, content_bytes=raw, mime_type="application/pdf", doc_kind=doc.doc_type,
            )
            proc = doc_tools.service.process_stored_document(
                doc.document_id, customer_id=CUSTOMER, declared_kind=DOCUMENT_KINDS[doc.doc_type], session_id=sid, as_of=NOW.date()
            )
            output = doc_tools._output(doc.doc_type, proc, ctx)
            doc.sha256_hash = stored["sha256_hash"]
            doc.extracted_fields = output.extracted_fields
        app.eligibility = EligibilityRecord(
            result=data.eligibility_rules[Product.personal_loan].make_satisfied_result(),
            input_fingerprint=fingerprint(app, eligibility_input_names(app)), verified_inputs=True,
        )
        seed_application(store, sid, app)
        yield client, store, model, sid, headers


def price_and_select(context):
    client, store, model, sid, headers = context
    response = client.post(f"/chat/sessions/{sid}/messages", json={"text": "Show my offers"}, headers=headers)
    assert response.status_code == 200
    payload = response.json()
    offer = next(b for b in payload["blocks"] if b["type"] == "offers")["offers"][0]
    selection = client.post(f"/chat/sessions/{sid}/offer-selection", json={"offer_id": offer["offer_id"]}, headers=headers)
    assert selection.status_code == 200
    return offer, selection.json()


def test_cross_customer_cannot_price_or_select_another_session(priced_chat):
    client, store, _, sid, headers = priced_chat
    before = store.get(sid).model_dump(mode="json")
    for suffix, payload in (("messages", {"text": "Calculate offers"}), ("offer-selection", {"offer_id": "guessed"})):
        denied = client.post(f"/chat/sessions/{sid}/{suffix}", json=payload, headers={"X-Customer-Id": "cust-andrei-stan"})
        assert denied.status_code == 403
    assert store.get(sid).model_dump(mode="json") == before


@pytest.mark.parametrize("failure", ["invalid", "unavailable"])
def test_failed_recalculation_removes_stale_offers_selection_and_summary(priced_chat, monkeypatch, failure):
    client, store, _, sid, headers = priced_chat
    offer, selected = price_and_select(priced_chat)
    if failure == "invalid":
        state = store.get(sid)
        state.application.fields["amount"].value = Decimal("1000")
        store.save(state, state.version)
    else:
        def unavailable(_):
            raise FileNotFoundError("unavailable pricing configuration")
        monkeypatch.setattr(pricing.pricing_service, "load_product", unavailable)
    result = client.post(f"/chat/sessions/{sid}/messages", json={"text": "Recalculate"}, headers=headers)
    assert result.status_code == 200
    app = store.get(sid).application
    assert app.offers is None and app.selected_offer_id is None and app.summary is None
    assert app.application_id is None
    assert not any(block["type"] in ("offers", "application_summary") for block in result.json()["blocks"])
    assert result.json()["awaiting"]["kind"] != "offer_choice"
    rejected = client.post(f"/chat/sessions/{sid}/offer-selection", json={"offer_id": offer["offer_id"]}, headers=headers)
    assert rejected.status_code == 200
    assert store.get(sid).application.selected_offer_id is None


def test_real_composition_uses_pricing_service_and_preserves_disclosures(priced_chat):
    client, store, model, sid, headers = priced_chat
    offer, selected = price_and_select(priced_chat)
    assert offer["monthly_installment"] == {"amount": "621.22", "currency": "RON"}
    assert offer["total_repayment"]["amount"] == "37273.16"
    assert offer["total_cost"]["amount"] == "7473.16"
    assert offer["fees"]["amount"] == "500.00"
    assert any("DAE/APR: 9.58%" in text for text in offer["assumptions"])
    assert any("Net amount paid out: 29800.00" in text for text in offer["assumptions"])
    assert DISCLAIMER in offer["assumptions"]
    assert selected["awaiting"]["kind"] == "text"
    assert store.get(sid).application.summary.offer.model_dump(mode="json") == offer
    assert store.get(sid).application.application_id is None
    context = build_context(store.get(sid), [], [], [])
    assert context["offers"][0]["assumptions"] == offer["assumptions"]
    assert context["offers"][0]["fees"] == "500.00"
    persisted = SessionState.model_validate_json(store.get(sid).model_dump_json())
    assert persisted.application.offers.offers[0].assumptions == offer["assumptions"]
    assert persisted.application.offers.offers[0].monthly_installment.amount == Decimal("621.22")
    tool_messages = [m.content for m in store.messages(sid) if m.role == "tool"]
    assert any('"status":"ok"' in text and '"monthly_installment":{"amount":"621.22"' in text for text in tool_messages)
