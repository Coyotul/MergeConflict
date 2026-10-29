"""Driver tests: DemoChatModel agent (offline), scripted stand-in customer."""
import io
import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from pypdf import PdfReader

from scripts.credit_sources.setup import create_database
from scripts.eval.customer import CustomerAction
from scripts.eval.driver import (
    ConversationResult,
    Scenario,
    build_eval_app,
    customer_documents,
    load_scenarios,
    run_conversation,
)
from scripts.eval.models import EvalModelError
from src.core.settings import OrchestratorSettings
from src.integrations.llm.chat import FakeChatModel
from src.parsers.validation.cnp_validator import compute_cnp_checksum

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config" / "orchestrator"
BINDINGS = CONFIG_DIR / "customer_bindings.yaml"
SCENARIOS = REPO_ROOT / "config" / "eval" / "scenarios.yaml"
TMP_ROOT = Path(__file__).parent / ".test_tmp"


@pytest.fixture(scope="module")
def credit_db():
    path = TMP_ROOT / f"credit-{uuid4().hex}"
    path.mkdir(parents=True)
    yield create_database(path / "credit_sources.db")
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def work_dir():
    path = TMP_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def make_app(work_dir: Path, credit_db: Path):
    return build_eval_app(OrchestratorSettings(
        model="fake", retrieval="stub", trace="file", traces_dir=work_dir / "traces",
        session_store="memory", sessions_dir=work_dir / "sessions", uploads_dir=work_dir / "uploads",
        config_dir=CONFIG_DIR, credit_sources_db=credit_db, customer_bindings_path=BINDINGS,
    ))


class ScriptedCustomer:
    """Stand-in for SimulatedCustomer: returns scripted actions, records the views it saw."""

    def __init__(self, actions: list):
        self.actions = list(actions)
        self.views = []

    def next_action(self, view):
        self.views.append(view)
        item = self.actions.pop(0) if self.actions else {"type": "say", "text": "ok"}
        if isinstance(item, Exception):
            raise item
        return CustomerAction(**item)


def scenario(**overrides) -> Scenario:
    data = {"id": "t", "customer_id": "cust-alex-morgan", "brief": "test", "checks": [], "rubric": []}
    data.update(overrides)
    return Scenario(**data)


def run(work_dir, credit_db, customer, *, max_turns=10, app=None, documents=None,
        **scenario_overrides) -> ConversationResult:
    app = app or make_app(work_dir, credit_db)
    return run_conversation(app, scenario(**scenario_overrides), customer, max_turns=max_turns,
                            documents=documents or {}, traces_dir=work_dir / "traces")


def test_driver_runs_until_customer_done(work_dir, credit_db):
    customer = ScriptedCustomer([{"type": "say", "text": "Vreau un credit"}, {"type": "done", "reason": "enough"}])
    result = run(work_dir, credit_db, customer)
    assert result.stop_reason == "customer_done"
    assert result.trace_path.exists()
    assert result.trace_path == work_dir / "traces" / f"{result.session_id}.jsonl"
    assert len(result.transcript) == 1
    item = result.transcript[0]
    assert item["turn"] == 1 and item["customer"] == "Vreau un credit" and item["agent"]
    assert isinstance(item["awaiting_before"], list) and isinstance(item["tool_results"], list)
    # The customer saw the greeting before its first action, and the reply after it.
    assert customer.views[0].transcript[0][0] == "agent"
    assert customer.views[1].transcript[-1][0] == "agent"
    assert result.error is None


def test_driver_stops_at_max_turns(work_dir, credit_db):
    customer = ScriptedCustomer([])  # says "ok" forever
    result = run(work_dir, credit_db, customer, max_turns=3)
    assert result.stop_reason == "max_turns"
    assert len(result.transcript) == 3


def test_driver_records_switch_turn(work_dir, credit_db):
    customer = ScriptedCustomer([
        {"type": "say", "text": "Vreau un credit"},
        {"type": "say", "text": "Actually I want a mortgage", "switch": True},
        {"type": "done", "reason": "enough"},
    ])
    result = run(work_dir, credit_db, customer)
    assert len(result.switch_turn_ids) == 1
    assert result.switch_turn_ids == [result.transcript[1]["turn_id"]]


def test_driver_rejects_unrequested_upload_then_customer_error(work_dir, credit_db):
    customer = ScriptedCustomer([
        {"type": "upload", "doc_type": "payslip"},
        {"type": "choose_offer", "offer_id": "nope"},
    ])
    result = run(work_dir, credit_db, customer)
    assert result.stop_reason == "customer_error"
    assert "payslip" in customer.views[1].feedback
    assert result.error
    assert result.transcript == []


def test_driver_customer_model_error_is_customer_error(work_dir, credit_db):
    customer = ScriptedCustomer([EvalModelError("bad json twice")])
    result = run(work_dir, credit_db, customer)
    assert result.stop_reason == "customer_error"
    assert "bad json twice" in result.error


def test_driver_records_agent_error(work_dir, credit_db):
    app = make_app(work_dir, credit_db)
    customer = ScriptedCustomer([{"type": "say", "text": "Vreau un credit"}, {"type": "say", "text": "renovare"}])

    class BreakAfterFirst(ScriptedCustomer):
        def next_action(self, view):
            if len(self.views) == 1:  # the agent's model goes down after the first turn
                app.state.orchestrator._model = FakeChatModel(lambda messages: "!unavailable")
            return super().next_action(view)

    customer = BreakAfterFirst(customer.actions)
    result = run(work_dir, credit_db, customer, app=app)
    assert result.stop_reason == "agent_error"
    assert "503" in result.error
    assert len(result.transcript) == 1  # the partial conversation is kept
    assert result.trace_path.exists()


ALEX_ANSWERS = ("Vreau un credit", "pentru renovare", "30000 lei", "60 luni",
                "employed", "67", "7000", "FICTIV Employer's Studio 1", "0", "ok")


def test_driver_stops_when_eligibility_shown(work_dir, credit_db):
    customer = ScriptedCustomer([{"type": "say", "text": t} for t in ALEX_ANSWERS])
    result = run(work_dir, credit_db, customer, max_turns=15, stop_when="eligibility_result")
    assert result.stop_reason == "stop_when"
    assert len(result.transcript) == len(ALEX_ANSWERS)
    assert "run_eligibility_check (model) ok" in result.transcript[-1]["tool_results"]
    assert "missing_field purpose" in result.transcript[1]["awaiting_before"]


def test_driver_uploads_requested_document(work_dir, credit_db):
    customer = ScriptedCustomer([{"type": "say", "text": t} for t in ALEX_ANSWERS]
                                + [{"type": "upload", "doc_type": "id_card"}, {"type": "done", "reason": "ok"}])
    docs = customer_documents("cust-alex-morgan", CONFIG_DIR, credit_db, BINDINGS)
    result = run(work_dir, credit_db, customer, max_turns=15, documents=docs)
    assert result.stop_reason == "customer_done", result.error
    assert "id_card" in customer.views[-2].document_types
    assert result.transcript[-1]["customer"] == "[uploaded id_card]"
    assert "process_document (code) ok" in result.transcript[-1]["tool_results"]


ELENA_TO_OFFERS = (
    [{"type": "say", "text": t} for t in ("Vreau un credit", "pentru renovare", "20000 lei", "48 luni", "employed",
                                          "67", "4500", "FICTIV Employer's Studio 1", "0", "ok")]
    + [{"type": "upload", "doc_type": d} for d in ("id_card", "payslip", "bank_statement")]
    + [{"type": "say", "text": "da"}]
)


def test_generated_documents_reach_offers(work_dir, credit_db):
    """Elena's generated documents pass real processing, so offers can be shown (knows_loan's path)."""
    customer = ScriptedCustomer(ELENA_TO_OFFERS)
    docs = customer_documents("cust-elena-popa", CONFIG_DIR, credit_db, BINDINGS)
    result = run(work_dir, credit_db, customer, max_turns=20, documents=docs,
                 customer_id="cust-elena-popa", stop_when="offers_shown")
    assert result.stop_reason == "stop_when", result.transcript[-1]
    assert "calculate_loan_offer (model) ok" in result.transcript[-1]["tool_results"]


class ChooseFirstOffer(ScriptedCustomer):
    def next_action(self, view):
        if view.offers:
            self.views.append(view)
            return CustomerAction(type="choose_offer", offer_id=view.offers[0]["offer_id"])
        return super().next_action(view)


def test_offers_reach_customer_and_driver_stops_before_confirmation(work_dir, credit_db):
    customer = ChooseFirstOffer(ELENA_TO_OFFERS)
    docs = customer_documents("cust-elena-popa", CONFIG_DIR, credit_db, BINDINGS)
    result = run(work_dir, credit_db, customer, max_turns=20, documents=docs, customer_id="cust-elena-popa")
    assert result.stop_reason == "awaiting_confirmation"
    offer = customer.views[-1].offers[0]
    assert set(offer) == {"offer_id", "term_months", "monthly_installment"}
    assert result.transcript[-1]["customer"] == f"[chose offer {offer['offer_id']}]"
    assert not any(e["type"] == "turn_started" and (e.get("event") or {}).get("kind") == "confirmation"
                   for e in map(json.loads, result.trace_path.read_text(encoding="utf-8").splitlines()))


def test_requested_documents_stay_open_once_requested():
    """After the first upload a real agent may await text (eligibility re-run) while still asking for
    the remaining documents; outstanding checklist items stay uploadable once documents were requested."""
    from scripts.eval.driver import _requested_documents
    checklist = {"type": "document_checklist", "items": [
        {"doc_type": "id_card", "label": "ID", "status": "accepted"},
        {"doc_type": "payslip", "label": "Payslip", "status": "requested"},
        {"doc_type": "bank_statement", "label": "Statement", "status": "rejected"},
    ]}
    text_body = {"awaiting": {"kind": "text"}, "blocks": [checklist]}
    assert _requested_documents(text_body, documents_requested=False) == []
    assert _requested_documents(text_body, documents_requested=True) == ["payslip", "bank_statement"]
    doc_body = {"awaiting": {"kind": "document", "document_types": ["payslip"]}, "blocks": [checklist]}
    assert _requested_documents(doc_body, documents_requested=True) == ["payslip"]


def test_customer_documents_match_profile(credit_db):
    docs = customer_documents("cust-alex-morgan", CONFIG_DIR, credit_db, BINDINGS)
    assert set(docs) == {"id_card", "payslip", "bank_statement"}
    texts = {k: "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(v)).pages) for k, v in docs.items()}
    assert "ALEX" in texts["id_card"] and "MORGAN" in texts["id_card"]
    assert "ALEX MORGAN" in texts["payslip"] and "ALEX MORGAN" in texts["bank_statement"]
    cnp = re.search(r"CNP: (\d{13})", texts["id_card"]).group(1)
    assert cnp[:7] == "1880412"  # sex digit of the bound CNP + birth date 1988-04-12
    assert int(cnp[-1]) == compute_cnp_checksum(cnp[:12])
    assert "8.500,00" in texts["payslip"]  # customers.yaml documents.payslip.monthly_net_income
    assert "FICTIV Employer's Studio 1" in texts["payslip"]
    assert "Angajat din data de 28.03.2021" in texts["payslip"]  # 2026-10-28 minus 67 months
    assert "Obligatii lunare credite existente: 0,00 RON" in texts["bank_statement"]


def test_customer_documents_female_and_obligations(credit_db):
    docs = customer_documents("cust-radu-mihai", CONFIG_DIR, credit_db, BINDINGS)
    statement = PdfReader(io.BytesIO(docs["bank_statement"])).pages[0].extract_text()
    assert "300,00" in statement
    docs = customer_documents("cust-maria-stoica", CONFIG_DIR, credit_db, BINDINGS)
    id_text = PdfReader(io.BytesIO(docs["id_card"])).pages[0].extract_text()
    assert "CNP: 2901201" in id_text


def test_load_scenarios_valid():
    scenarios = load_scenarios(SCENARIOS)
    assert [s.id for s in scenarios] == ["knows_loan", "unsure_type", "changes_mind", "rag_questions"]
    customers = {s.id: s.customer_id for s in scenarios}
    assert customers == {"knows_loan": "cust-elena-popa", "unsure_type": "cust-radu-mihai",
                         "changes_mind": "cust-alex-morgan", "rag_questions": "cust-maria-stoica"}
    for s in scenarios:
        names = {c["check"] for c in s.checks}
        assert {"no_model_tool_rejections", "no_failed_turns"} <= names
        assert s.rubric
    try:
        from scripts.eval.checks import run_check
    except ImportError:
        return  # Task 1 not merged yet
    for s in scenarios:
        for spec in s.checks:
            run_check(spec, [])  # raises ValueError on an unknown check name


def test_load_scenarios_rejects_duplicate_ids(work_dir):
    path = work_dir / "s.yaml"
    path.write_text("- {id: a, customer_id: c, brief: b}\n- {id: a, customer_id: c, brief: b}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_scenarios(path)
