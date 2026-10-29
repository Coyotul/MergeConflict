"""Runs one scenario conversation in-process: simulated customer <-> real chat API.

The customer only sees the chat (transcript, what the agent awaits, offers); the
driver never confirms an application and records why the conversation stopped.
"""
import io
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from scripts.eval.customer import CustomerView
from src.api.app import create_app
from src.core.settings import OrchestratorSettings
from tests.fixtures.documents import cnp_for, document_bytes

EVAL_CLOCK = datetime(2026, 10, 28, 12, tzinfo=UTC)
DATASET_DATE = date(2026, 10, 28)
DOC_TYPES = ("id_card", "payslip", "bank_statement")

StopReason = Literal["customer_done", "stop_when", "awaiting_confirmation", "max_turns",
                     "customer_error", "agent_error"]


class Scenario(BaseModel):
    id: str
    customer_id: str
    brief: str
    stop_when: Literal["offers_shown", "eligibility_result", "never"] = "never"
    checks: list[dict] = []
    rubric: list[str] = []


class ConversationResult(BaseModel):
    scenario_id: str
    session_id: str
    stop_reason: StopReason
    transcript: list[dict]
    switch_turn_ids: list[str]
    trace_path: Path
    error: str | None = None


def load_scenarios(path: Path) -> list[Scenario]:
    """Scenarios from a YAML list; ids must be unique."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of scenarios")
    scenarios = [Scenario.model_validate(item) for item in data]
    ids = [s.id for s in scenarios]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"{path}: duplicate scenario ids {duplicates}")
    return scenarios


def build_eval_app(settings: OrchestratorSettings) -> FastAPI:
    """create_app with the orchestrator clock pinned to the dataset date."""
    app = create_app(settings)
    app.state.orchestrator._clock = lambda: EVAL_CLOCK
    return app


# ---- documents ----------------------------------------------------------------


def _ro_amount(value) -> str:
    """4500 -> '4.500,00' (Romanian thousands/decimal separators)."""
    text = f"{Decimal(str(value)):,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _months_before(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    for d in (day.day, 30, 29, 28):
        try:
            return date(year, month, d)
        except ValueError:
            continue
    raise ValueError(f"cannot subtract {months} months from {day}")


def customer_documents(customer_id: str, config_dir: Path, db_path: Path, bindings_path: Path) -> dict[str, bytes]:
    """id_card, payslip and bank_statement PDFs carrying the customer's own figures.

    Name and figures come from customers.yaml; the CNP is checksum-valid, built from the
    sex digit of the bound (dataset) CNP and the person's birth date in `persons`.
    """
    customers = yaml.safe_load((Path(config_dir) / "customers.yaml").read_text(encoding="utf-8"))["customers"]
    if customer_id not in customers:
        raise ValueError(f"unknown customer {customer_id}")
    customer = customers[customer_id]
    bindings = yaml.safe_load(Path(bindings_path).read_text(encoding="utf-8"))["bindings"]
    bound = next((b["cnp"] for b in bindings if b["customer_id"] == customer_id), None)
    if bound is None:
        raise ValueError(f"no CNP binding for {customer_id}")
    with sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT birth_date FROM persons WHERE cnp = ?", (bound,)).fetchone()
    if row is None:
        raise ValueError(f"no person for {customer_id} in {db_path}")
    birth = date.fromisoformat(row[0])
    cnp = cnp_for(f"{bound[0]}{birth:%y%m%d}41001")

    first_name, _, last_name = customer["profile"]["full_name"].upper().partition(" ")
    docs = customer["documents"]
    payslip = docs["payslip"]
    figures = dict(
        first_name=first_name, last_name=last_name, cnp=cnp,
        net=_ro_amount(payslip["monthly_net_income"]),
        employer=payslip["employer_name"],
        employment_start=_months_before(DATASET_DATE, int(payslip["employment_months"])),
        obligations=_ro_amount(docs["bank_statement"]["existing_monthly_obligations"]),
    )
    return {doc_type: document_bytes(doc_type, **figures) for doc_type in DOC_TYPES}


# ---- conversation -------------------------------------------------------------


def _offers(body: dict) -> list[dict]:
    for block in reversed(body.get("blocks") or []):
        if block.get("type") == "offers":
            return [{
                "offer_id": o["offer_id"],
                "term_months": o["term_months"],
                "monthly_installment": f"{o['monthly_installment']['amount']} {o['monthly_installment'].get('currency', 'RON')}",
            } for o in block.get("offers") or []]
    return []


def _agent_text(body: dict) -> str:
    return "\n\n".join(m["text"] for m in body.get("messages") or [] if m.get("role") == "assistant")


_OUTSTANDING = {"requested", "rejected"}


def _requested_documents(body: dict, *, documents_requested: bool) -> list[str]:
    """Document types the customer may upload now.

    `awaiting.document_types` while the agent awaits a document. Once documents have been
    requested, a real agent may await text (e.g. the eligibility re-run after the first upload)
    while still asking for the rest, so the checklist's outstanding items stay uploadable.
    """
    awaiting = body.get("awaiting") or {}
    types = list(awaiting.get("document_types") or [])
    if awaiting.get("kind") == "document" or not documents_requested:
        return types
    for block in body.get("blocks") or []:
        if block.get("type") == "document_checklist":
            types += [i["doc_type"] for i in block.get("items") or []
                      if i.get("status") in _OUTSTANDING and i["doc_type"] not in types]
    return types


def _rejection(action, requested: list[str], offers: list[dict], documents: dict[str, bytes]) -> str | None:
    if action.type == "upload":
        if action.doc_type not in requested:
            return (f"The agent did not request a '{action.doc_type}' document. Requested document types: "
                    f"{', '.join(requested) or '(none)'}.")
        if action.doc_type not in documents:
            return f"No '{action.doc_type}' document is available to upload."
    if action.type == "choose_offer" and action.offer_id not in {o["offer_id"] for o in offers}:
        return (f"Offer '{action.offer_id}' is not one of the listed offers: "
                f"{', '.join(o['offer_id'] for o in offers) or '(none)'}.")
    return None


def _load_trace(path: Path) -> list[dict]:
    if not path.exists():
        return []
    from scripts.trace_report import load_events
    return load_events(path)


def _annotate(transcript: list[dict], events: list[dict]) -> None:
    """awaiting_before (needs of the turn's latest model_call) and tool_results per turn."""
    for item in transcript:
        turn_events = [e for e in events if e.get("turn_id") == item.get("turn_id")]
        calls = [e for e in turn_events if e.get("type") == "model_call"]
        needs = ((calls[-1].get("context") or {}).get("needs") or []) if calls else []
        if not isinstance(needs, list):
            needs = []
        item["awaiting_before"] = [
            " ".join(str(n.get(k)) for k in ("kind", "target") if n.get(k)) for n in needs if isinstance(n, dict)
        ]
        item["tool_results"] = [
            f"{e.get('tool')} ({e.get('caller')}) " + ("ok" if e.get("ok") else f"error {e.get('error_code')}")
            for e in turn_events if e.get("type") == "tool_call"
        ]


def run_conversation(app: FastAPI, scenario: Scenario, customer, *, max_turns: int,
                     documents: dict[str, bytes], traces_dir: Path) -> ConversationResult:
    """Play one conversation until a stop condition; never sends a confirmation.

    `customer` is anything with `next_action(CustomerView) -> CustomerAction`. An action the
    agent did not ask for (unrequested upload, unknown offer) is rejected and the customer is
    told once; a second rejection, or a simulator error, stops with `customer_error`.
    """
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-Customer-Id": scenario.customer_id}
    transcript: list[dict] = []
    switch_turn_ids: list[str] = []

    def result(stop_reason: StopReason, session_id: str = "", error: str | None = None) -> ConversationResult:
        trace_path = Path(traces_dir) / f"{session_id}.jsonl"
        if session_id:
            _annotate(transcript, _load_trace(trace_path))
        return ConversationResult(
            scenario_id=scenario.id, session_id=session_id, stop_reason=stop_reason, transcript=transcript,
            switch_turn_ids=switch_turn_ids, trace_path=trace_path, error=error,
        )

    r = client.post("/chat/sessions", json={}, headers=headers)
    if r.status_code != 201:
        return result("agent_error", error=f"HTTP {r.status_code} starting session: {r.text[:500]}")
    body = r.json()
    session_id = body["session_id"]
    base = f"/chat/sessions/{session_id}"
    chat: list[tuple[str, str]] = [("agent", m["text"]) for m in body.get("messages") or [] if m.get("role") == "assistant"]

    turns = 0
    rejected = False
    documents_requested = False
    feedback: str | None = None
    while True:
        if turns >= max_turns:
            return result("max_turns", session_id)
        awaiting = body.get("awaiting") or {}
        documents_requested = documents_requested or awaiting.get("kind") == "document"
        requested = _requested_documents(body, documents_requested=documents_requested)
        offers = _offers(body)
        view = CustomerView(
            transcript=list(chat), awaiting_kind=str(awaiting.get("kind", "text")),
            document_types=requested, offers=offers, feedback=feedback,
        )
        try:
            action = customer.next_action(view)
        except Exception as e:  # simulator failure: reported separately, never an agent result
            return result("customer_error", session_id, f"{type(e).__name__}: {e}")
        if action.type == "done":
            return result("customer_done", session_id)

        problem = _rejection(action, requested, offers, documents)
        if problem is not None:
            if rejected:
                return result("customer_error", session_id, f"rejected customer action twice: {problem}")
            rejected, feedback = True, problem
            continue
        feedback = None

        if action.type == "say":
            said = action.text
            r = client.post(f"{base}/messages", json={"text": action.text}, headers=headers)
        elif action.type == "upload":
            said = f"[uploaded {action.doc_type}]"
            files = {"file": (f"{action.doc_type}.pdf", io.BytesIO(documents[action.doc_type]), "application/pdf")}
            r = client.post(f"{base}/documents", data={"doc_type": action.doc_type}, files=files, headers=headers)
        else:  # choose_offer
            said = f"[chose offer {action.offer_id}]"
            r = client.post(f"{base}/offer-selection", json={"offer_id": action.offer_id}, headers=headers)

        if r.status_code != 200:
            return result("agent_error", session_id, f"HTTP {r.status_code} on {action.type}: {r.text[:500]}")
        body = r.json()
        turns += 1
        reply = _agent_text(body)
        if action.type == "say" and action.switch:
            switch_turn_ids.append(body["turn_id"])
        transcript.append({"turn": turns, "turn_id": body["turn_id"], "customer": said, "agent": reply,
                           "awaiting_before": [], "tool_results": []})
        chat.append(("customer", said))
        chat.append(("agent", reply))

        block_types = {b.get("type") for b in body.get("blocks") or []}
        if (body.get("awaiting") or {}).get("kind") == "confirmation":
            return result("awaiting_confirmation", session_id)
        if (scenario.stop_when == "offers_shown" and "offers" in block_types) or (
                scenario.stop_when == "eligibility_result" and "eligibility_result" in block_types):
            return result("stop_when", session_id)
