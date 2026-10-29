"""Orchestrator tool checks: use file evidence, never canned values or model approval."""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.agent.orchestration.state import DocumentRecord, DocumentStatus, Flow, SessionState
from src.agent.tools.registry import ToolContext
from src.agent.tools.retrieval import StubPolicySearch
from src.agent.tools.stubs import StubData, build_stub_registry
from src.services.document_processing.service import DocumentProcessingService
from src.storage.secure_documents.store import SecureDocumentStore
from tests.fixtures.documents import income_text, identity_text, pdf_bytes, statement_text
from tests.unit.orchestrator.factories import make_collecting_app

CONFIG = Path(__file__).resolve().parents[3] / "config" / "orchestrator"
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.fixture
def tools(tmp_path):
    storage = SecureDocumentStore(tmp_path)
    service = DocumentProcessingService(storage)
    data = StubData.load(CONFIG)
    registry = build_stub_registry(data, StubPolicySearch(CONFIG), document_service=service)
    state = SessionState(
        session_id="session-1", customer_id="cust-001", created_at=NOW, updated_at=NOW,
        active_flow=Flow.credit_application,
        application=make_collecting_app(data.requirements[next(iter(data.products))]),
    )
    return storage, registry, ToolContext(state, NOW)


def stage(tools, doc_type, text, *, customer="cust-001", session="session-1"):
    storage, registry, ctx = tools
    data = pdf_bytes(text)
    saved = storage.store_document(
        customer_id=customer, session_id=session, filename=f"{doc_type}.pdf",
        content_bytes=data, mime_type="application/pdf", doc_kind=doc_type,
    )
    ctx.state.application.documents.append(DocumentRecord(
        document_id=saved["document_id"], doc_type=doc_type, filename=saved["original_filename"],
        status=DocumentStatus.processing, uploaded_at=NOW,
    ))
    arguments = dict(document_id=saved["document_id"], doc_type=doc_type,
                     filename=saved["original_filename"], size_bytes=len(data))
    return arguments


def test_income_values_come_from_the_uploaded_pdf_not_customer_demo_data(tools):
    """7500 in the file must be returned even though the old stub always returned 6200."""
    arguments = stage(tools, "payslip", income_text(net="7.500,00"))
    outcome, output = tools[1].execute("process_document", arguments, tools[2], caller="code")
    assert outcome.ok
    assert output.status == "accepted"
    assert output.extracted_fields["monthly_net_income"].value == "7500.00"
    assert output.simulated is False
    assert output.validation.valid
    assert "raw_text" not in output.extracted_data


def test_model_is_not_allowed_to_process_or_accept_an_upload_itself(tools):
    arguments = stage(tools, "id_card", identity_text())
    outcome, output = tools[1].execute("process_document", arguments, tools[2], caller="model")
    assert not outcome.ok and outcome.error_code == "not_model_callable"
    assert output is None


def test_model_has_a_read_only_verification_tool_scoped_to_the_current_application(tools):
    registry, ctx = tools[1:]
    assert "verify_application_documents" in {tool.name for tool in registry.model_tools(ctx.state)}
    outcome, output = registry.execute("verify_application_documents", {}, ctx, caller="model")
    assert outcome.ok and not output.complete and not output.ready_for_application
    outcome, _ = registry.execute("verify_application_documents", {"customer_id": "cust-002"}, ctx, caller="model")
    assert not outcome.ok and outcome.error_code == "invalid_arguments"


@pytest.mark.parametrize("customer,session", [("cust-002", "session-1"), ("cust-001", "session-2")])
def test_tool_cannot_read_someone_elses_uploaded_bytes(tools, customer, session):
    arguments = stage(tools, "id_card", identity_text(), customer=customer, session=session)
    outcome, output = tools[1].execute("process_document", arguments, tools[2], caller="code")
    assert outcome.ok and output.status == "rejected"
    assert output.extracted_fields == {}
    assert "POPESCU" not in str(output.model_dump())


def test_mismatched_document_type_does_not_reinterpret_stored_evidence(tools):
    arguments = stage(tools, "id_card", identity_text())
    arguments["doc_type"] = "payslip"
    _, output = tools[1].execute("process_document", arguments, tools[2], caller="code")
    assert output.status == "rejected" and not output.extracted_fields


def test_invalid_cnp_checksum_is_not_waived_for_orchestrator_uploads(tools):
    arguments = stage(tools, "id_card", identity_text(cnp="1920515410012"))
    _, output = tools[1].execute("process_document", arguments, tools[2], caller="code")
    assert output.status == "rejected"
    assert any(rule.code == "ID_CNP_CHECKSUM" and not rule.passed for rule in output.validation.rules_evaluated)


def test_id_card_for_a_different_profile_requires_human_review(tools):
    arguments = stage(tools, "id_card", identity_text(first_name="MARIA"))
    _, output = tools[1].execute("process_document", arguments, tools[2], caller="code")
    assert output.status == "rejected" and output.human_review_required
    assert not output.extracted_fields


def test_statement_without_explicit_debt_total_does_not_invent_zero_obligations(tools):
    arguments = stage(tools, "bank_statement", statement_text().split("Obligatii lunare")[0])
    _, output = tools[1].execute("process_document", arguments, tools[2], caller="code")
    assert output.status == "rejected" and output.human_review_required
    assert "existing_monthly_obligations" not in output.extracted_fields


def test_fixed_term_income_is_flagged_instead_of_silently_accepted(tools):
    arguments = stage(tools, "payslip", income_text(contract="DETERMINATA"))
    _, output = tools[1].execute("process_document", arguments, tools[2], caller="code")
    assert output.status == "rejected" and output.human_review_required


def test_unsupported_property_report_never_gets_fake_extracted_values(tools):
    arguments = stage(tools, "property_valuation", "Property report - value 999999 RON")
    _, output = tools[1].execute("process_document", arguments, tools[2], caller="code")
    assert output.status == "rejected" and output.human_review_required
    assert not output.extracted_fields


def test_model_can_read_verified_extraction_but_cannot_supply_paths_or_override_acceptance(tools):
    arguments = stage(tools, "payslip", income_text(net="7.500,00"))
    _, processed = tools[1].execute("process_document", arguments, tools[2], caller="code")
    doc = tools[2].state.application.documents[-1]
    doc.status = DocumentStatus.accepted
    doc.sha256_hash = processed.sha256_hash
    doc.extracted_data = processed.extracted_data
    outcome, read = tools[1].execute("read_document_extraction", {"doc_type": "payslip"}, tools[2], caller="model")
    assert outcome.ok
    assert read.document.status == "accepted"
    assert read.document.extracted_fields["monthly_net_income"].value == "7500.00"
    for arguments in ({"doc_type": "payslip", "path": "../other.pdf"}, {"doc_type": "payslip", "accept": True}):
        outcome, read = tools[1].execute("read_document_extraction", arguments, tools[2], caller="model")
        assert not outcome.ok and outcome.error_code == "invalid_arguments"


def test_read_only_extraction_rechecks_the_hash_instead_of_replaying_stale_fields(tools):
    arguments = stage(tools, "payslip", income_text())
    _, processed = tools[1].execute("process_document", arguments, tools[2], caller="code")
    doc = tools[2].state.application.documents[-1]
    doc.status = DocumentStatus.accepted
    doc.sha256_hash = processed.sha256_hash
    doc.extracted_data = processed.extracted_data
    _, stored = tools[0].get_document_bytes(doc.document_id, customer_id="cust-001", session_id="session-1")
    (tools[0].root_dir / stored["stored_path"]).write_bytes(pdf_bytes("Tampered"))
    outcome, read = tools[1].execute("read_document_extraction", {"doc_type": "payslip"}, tools[2], caller="model")
    assert outcome.ok and read.document.status == "rejected"
    assert not read.document.extracted_fields