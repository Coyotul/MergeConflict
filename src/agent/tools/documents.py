"""Real, owner-scoped OCR/extraction tools; the model cannot accept or store evidence."""
from decimal import Decimal
from typing import Mapping

from src.agent.orchestration.fields import FieldValueError, parse_field_value
from src.agent.orchestration.state import DocumentStatus, ExtractedField, Flow
from src.agent.tools.contracts import (
    DocumentVerificationItem, ProcessDocumentInput, ProcessDocumentOutput,
    VerifyDocumentsInput, VerifyDocumentsOutput,
    ReadDocumentExtractionInput, ReadDocumentExtractionOutput,
)
from src.agent.tools.registry import ToolContext, ToolRegistry, ToolSpec
from src.core.errors import ToolUnavailable
from src.models.document_processing import (
    DocumentKind, DocumentProcessingStatus, ExtractedIdentity, ExtractedIncome,
    ExtractedStatement, ProcessedDocumentResponse,
)
from src.parsers.validation.cnp_validator import parse_cnp
from src.parsers.validation.document_validator import DocumentValidator, normalized_name
from src.services.document_processing.service import DocumentProcessingService

DOCUMENT_KINDS = {
    "id_card": DocumentKind.IDENTITY,
    "payslip": DocumentKind.INCOME,
    "bank_statement": DocumentKind.STATEMENT,
}
MIN_EXTRACTION_CONFIDENCE = 0.85


class DocumentTools:
    def __init__(self, service: DocumentProcessingService, profiles: Mapping[str, dict]):
        self.service = service
        self.profiles = profiles

    @staticmethod
    def rejected(reason: str, *, review: bool = False) -> ProcessDocumentOutput:
        return ProcessDocumentOutput(
            status="rejected", rejection_reason=reason, extracted_fields={},
            simulated=False, human_review_required=review,
        )

    def process(self, input: ProcessDocumentInput, ctx: ToolContext) -> ProcessDocumentOutput:
        app = ctx.state.application
        record = next((d for d in app.documents if d.document_id == input.document_id), None) if app else None
        if record is None or record.doc_type != input.doc_type or record.status != DocumentStatus.processing:
            return self.rejected("The document is not a pending upload in this application.")
        if input.doc_type not in DOCUMENT_KINDS:
            return self.rejected("This document type has no automatic extractor and requires human review.", review=True)
        try:
            _, stored = self.service.storage.get_document_bytes(
                input.document_id, customer_id=ctx.state.customer_id, session_id=ctx.state.session_id,
            )
            if (stored["kind"] != input.doc_type or stored["size_bytes"] != input.size_bytes
                    or stored["original_filename"] != input.filename):
                return self.rejected("The uploaded document metadata does not match its stored evidence.")
            result = self.service.process_stored_document(
                input.document_id, ctx.state.customer_id, DOCUMENT_KINDS[input.doc_type],
                session_id=ctx.state.session_id, as_of=ctx.now.date(), allow_synthetic_cnp=False,
            )
        except (PermissionError, FileNotFoundError, ValueError):
            return self.rejected("The document is missing, belongs to another session, or failed its integrity check.")
        except OSError as exc:
            raise ToolUnavailable("Document storage is temporarily unavailable; please retry the upload.") from exc
        return self._output(input.doc_type, result, ctx)

    def _output(self, doc_type: str, result: ProcessedDocumentResponse, ctx: ToolContext) -> ProcessDocumentOutput:
        data = dict(result.extracted_data or {})
        data.pop("raw_text", None)
        validation = result.validation
        reason = None
        review = validation.status == DocumentProcessingStatus.FLAGGED_FOR_HUMAN_REVIEW
        values: dict[str, str] = {}
        if not validation.valid or review:
            reason = "; ".join(rule.description for rule in validation.rules_evaluated if not rule.passed)
            reason = reason or "Document validation failed; please upload a clear, current copy."
        elif doc_type == "id_card":
            identity = ExtractedIdentity.model_validate(data)
            name = f"{identity.first_name} {identity.last_name}".strip()
            profile = self.profiles.get(ctx.state.customer_id, {}).get("profile", {})
            expected_name = profile.get("full_name")
            if not expected_name or normalized_name(name) != normalized_name(expected_name):
                reason, review = "The identity document does not match the customer profile; human identity verification is required.", True
            meta = parse_cnp(identity.cnp, as_of=ctx.now.date())
            values = {"full_name": name, "age": str(meta.age_years)}
        elif doc_type == "payslip":
            income = ExtractedIncome.model_validate(data)
            cnp = parse_cnp(income.employee_cnp, as_of=ctx.now.date())
            if not income.employee_name or not (cnp.is_valid_format and cnp.is_valid_date and cnp.is_valid_checksum):
                reason = "The income document is missing a complete employee name or valid CNP."
            values = {
                "employer_name": income.employer_name,
                "monthly_net_income": str(Decimal(str(income.monthly_net_income)).quantize(Decimal("0.01"))),
            }
        elif doc_type == "bank_statement":
            statement = ExtractedStatement.model_validate(data)
            if not statement.account_holder:
                reason = "The statement must identify its account holder."
            elif statement.currency != "RON":
                reason, review = "Foreign-currency statements require authorized human review; amounts are not converted or guessed.", True
            elif statement.existing_monthly_obligations is None:
                reason, review = "The statement does not explicitly verify the monthly debt total; human debt verification is required.", True
            else:
                values["existing_monthly_obligations"] = str(
                    Decimal(str(statement.existing_monthly_obligations)).quantize(Decimal("0.01"))
                )

        confidence = float(data.get("confidence_score", 0))
        fields = {}
        app = ctx.state.application
        specs = [s for s in app.requirements.fields if s.required and s.verified_by == doc_type] if app and app.requirements else []
        if reason is None:
            for spec in specs:
                try:
                    parse_field_value(spec, values.get(spec.name))
                except FieldValueError:
                    reason = "The document does not contain all required fields in a usable format."
                    break
            if confidence < MIN_EXTRACTION_CONFIDENCE:
                reason, review = "The extracted fields have low confidence and require human review.", True
            if reason is None:
                fields = {
                    name: ExtractedField(value=value, confidence=confidence, location=f"{doc_type} extraction")
                    for name, value in values.items()
                }
        return ProcessDocumentOutput(
            status="rejected" if reason else "accepted", rejection_reason=reason,
            extracted_fields=fields, simulated=False, human_review_required=review,
            validation=validation, extracted_data=data, sha256_hash=result.sha256_hash,
        )

    def verify(self, input: VerifyDocumentsInput, ctx: ToolContext) -> VerifyDocumentsOutput:
        app = ctx.state.application
        items = []
        extracted = {}
        for requirement in app.requirements.documents:
            records = [d for d in app.documents if d.doc_type == requirement.doc_type]
            if not records:
                items.append(DocumentVerificationItem(doc_type=requirement.doc_type, status="missing"))
                continue
            doc = max(records, key=lambda record: record.uploaded_at)
            item = DocumentVerificationItem(
                doc_type=doc.doc_type, status="rejected", human_review_required=doc.human_review_required,
            )
            try:
                _, stored = self.service.storage.get_document_bytes(
                    doc.document_id, customer_id=ctx.state.customer_id, session_id=ctx.state.session_id,
                )
                if stored["kind"] != doc.doc_type or not doc.sha256_hash or doc.sha256_hash != stored["sha256_hash"]:
                    raise ValueError("Document evidence does not match the application.")
                result = ProcessedDocumentResponse.model_validate(stored["processing_result"])
                if result.document_id != doc.document_id or result.sha256_hash != doc.sha256_hash:
                    raise ValueError("Processing result does not match the application.")
                data = result.extracted_data or {}
                # Recheck time-sensitive rules against this turn, without rerunning OCR or writing files.
                if doc.doc_type == "id_card":
                    value = ExtractedIdentity.model_validate(data)
                    result.validation = DocumentValidator.validate_identity(value, as_of=ctx.now.date(), allow_synthetic_cnp=False)
                elif doc.doc_type == "payslip":
                    value = ExtractedIncome.model_validate(data)
                    result.validation = DocumentValidator.validate_income(value, as_of=ctx.now.date())
                elif doc.doc_type == "bank_statement":
                    value = ExtractedStatement.model_validate(data)
                    result.validation = DocumentValidator.validate_statement(value, as_of=ctx.now.date())
                else:
                    raise ValueError("Unsupported document type.")
                output = self._output(doc.doc_type, result, ctx)
                item.integrity_verified = True
                item.status = output.status
                item.human_review_required = output.human_review_required
                item.rule_codes = [rule.code for rule in result.validation.rules_evaluated if not rule.passed]
                item.reasons = [output.rejection_reason] if output.rejection_reason else []
                item.extracted_fields = output.extracted_fields
                if result.validation.valid:
                    extracted[doc.doc_type] = value
            except (PermissionError, FileNotFoundError, ValueError, KeyError):
                item.human_review_required = True
                item.reasons = ["The stored document or its verification record is unavailable or failed its integrity check."]
            except OSError as exc:
                raise ToolUnavailable("Document storage is temporarily unavailable; verification is blocked.") from exc
            items.append(item)

        cross = self.service.cross_validate_application(
            identity_doc=extracted.get("id_card"), income_doc=extracted.get("payslip"),
            statement_doc=extracted.get("bank_statement"),
        )
        complete = all(item.status != "missing" for item in items)
        if cross.human_review_required:
            for item in items:
                if item.status != "missing":
                    item.status = "rejected"
                    item.human_review_required = True
                    item.reasons = [*item.reasons, *cross.reasons]
                item.extracted_fields = {}
        return VerifyDocumentsOutput(
            documents=items, cross_validation=cross, complete=complete,
            ready_for_application=complete and cross.consistent and not cross.human_review_required
            and all(item.status == "accepted" and not item.human_review_required for item in items),
        )

    def read_extraction(self, input: ReadDocumentExtractionInput, ctx: ToolContext) -> ReadDocumentExtractionOutput:
        """Read-only access to server-derived fields after fresh ownership/integrity checks."""
        verified = self.verify(VerifyDocumentsInput(), ctx)
        item = next((item for item in verified.documents if item.doc_type == input.doc_type), None)
        if item is None:
            item = DocumentVerificationItem(doc_type=input.doc_type, status="missing")
        if verified.cross_validation.human_review_required:
            item.status = "rejected"
            item.human_review_required = True
            item.reasons = verified.cross_validation.reasons
        return ReadDocumentExtractionOutput(document=item)


def register_document_tools(registry: ToolRegistry, service: DocumentProcessingService, profiles: Mapping[str, dict]) -> None:
    tools = DocumentTools(service, profiles)
    registry.register(ToolSpec(
        name="process_document", description="OCR, extract and deterministically validate an owned upload (server controlled).",
        input_model=ProcessDocumentInput, output_model=ProcessDocumentOutput, model_callable=False,
        flows=frozenset([Flow.credit_application]), handler=tools.process,
    ))
    registry.register(ToolSpec(
        name="verify_application_documents",
        description="Read-only verification of your application's stored documents: integrity, current validation rules and cross-document consistency. No paths or customer IDs accepted.",
        input_model=VerifyDocumentsInput, output_model=VerifyDocumentsOutput, model_callable=True,
        flows=frozenset([Flow.credit_application]), handler=tools.verify,
        precondition=lambda state: None if state.application and state.application.requirements else "No application document requirements are available.",
    ))
    registry.register(ToolSpec(
        name="read_document_extraction",
        description="Read verified fields extracted by the server's OCR/extraction pipeline for one document in this application. Never accepts file paths, raw bytes, customer IDs or acceptance overrides.",
        input_model=ReadDocumentExtractionInput, output_model=ReadDocumentExtractionOutput, model_callable=True,
        flows=frozenset([Flow.credit_application]), handler=tools.read_extraction,
        precondition=lambda state: None if state.application and state.application.requirements else "No application document requirements are available.",
    ))