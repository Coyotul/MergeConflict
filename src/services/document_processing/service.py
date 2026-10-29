"""Document Processing Service orchestrator.

Coordinates OCR extraction, multi-rule regulatory validation and secure storage
for applicant credit documents.
"""

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from src.models.document_processing import (
    CrossDocumentValidationSummary,
    DocumentKind,
    DocumentProcessingStatus,
    DocumentValidationSummary,
    ExtractedIdentity,
    ExtractedIncome,
    ExtractedStatement,
    ProcessedDocumentResponse,
    RuleEvaluation,
)
from src.parsers.extraction.bank_statement_extractor import BankStatementExtractor
from src.parsers.extraction.id_card_extractor import IdCardExtractor
from src.parsers.extraction.income_certificate_extractor import IncomeCertificateExtractor
from src.parsers.ocr.pdf_extractor import PdfExtractor
from src.parsers.validation.document_validator import DocumentValidator
from src.storage.secure_documents.store import SecureDocumentStore


class DocumentProcessingService:
    def __init__(self, storage_store: Optional[SecureDocumentStore] = None):
        self.storage = storage_store or SecureDocumentStore()

    def process_and_store(
        self,
        content: Union[bytes, Path],
        filename: str,
        mime_type: str,
        customer_id: str,
        declared_kind: Union[DocumentKind, str],
        application_id: Optional[str] = None,
        allow_synthetic_cnp: bool = True,
        *,
        as_of: Optional[date] = None,
    ) -> ProcessedDocumentResponse:
        """Process an uploaded document through the complete pipeline:

        1. Ingest & Store securely in SecureDocumentStore.
        2. Run OCR & Structured field extraction.
        3. Run regulatory & mathematical validation rules.
        4. Update document record and return typed result.
        """
        # Read content bytes
        if isinstance(content, Path):
            content_bytes = content.read_bytes()
            if not filename:
                filename = content.name
        else:
            content_bytes = content

        kind_enum = DocumentKind(declared_kind.value if hasattr(declared_kind, "value") else declared_kind)

        # 1. Secure Storage
        stored_record = self.storage.store_document(
            customer_id=customer_id,
            filename=filename,
            content_bytes=content_bytes,
            mime_type=mime_type,
            doc_kind=kind_enum.value,
            application_id=application_id,
        )

        try:
            return self.process_stored_document(
                stored_record["document_id"], customer_id, kind_enum,
                as_of=as_of, allow_synthetic_cnp=allow_synthetic_cnp,
            )
        except Exception:
            self.storage.delete_document(stored_record["document_id"], customer_id=customer_id)
            raise

    def process_stored_document(
        self, document_id: str, customer_id: str, declared_kind: Union[DocumentKind, str],
        *, session_id: Optional[str] = None, as_of: Optional[date] = None,
        allow_synthetic_cnp: bool = False,
    ) -> ProcessedDocumentResponse:
        """OCR and validate already-staged, owner-bound bytes; do not create a second file."""
        content_bytes, stored_record = self.storage.get_document_bytes(
            document_id, customer_id=customer_id, session_id=session_id,
        )
        kind_enum = DocumentKind(declared_kind)
        as_of = as_of or date.today()
        try:
            if stored_record["mime_type"] == "application/pdf":
                raw_text = PdfExtractor.extract_text(content_bytes)
            else:
                raw_text = PdfExtractor.extract_image_text(content_bytes)
        except Exception:
            raw_text = ""
            validation_summary = self._extraction_failure(
                "DOC_OCR_FAILED", "The document could not be read safely. Upload a clear, unlocked copy; scanned files require Windows OCR.",
            )
        else:
            validation_summary = self._extraction_failure(
                "DOC_TEXT_UNREADABLE", "No readable document text was found. Upload a clearer copy.",
            ) if not raw_text.strip() else None

        # 3. Field Extraction based on document kind
        extracted_data_dict: Dict[str, Any] = {}
        try:
            if validation_summary is None and kind_enum == DocumentKind.IDENTITY:
                extracted_identity = IdCardExtractor.extract(raw_text)
                extracted_data_dict = extracted_identity.model_dump(mode="json", exclude={"raw_text"})
                validation_summary = DocumentValidator.validate_identity(
                    extracted_identity, allow_synthetic_cnp=allow_synthetic_cnp, as_of=as_of,
                )
            elif validation_summary is None and kind_enum == DocumentKind.INCOME:
                extracted_income = IncomeCertificateExtractor.extract(raw_text)
                extracted_data_dict = extracted_income.model_dump(mode="json", exclude={"raw_text"})
                validation_summary = DocumentValidator.validate_income(extracted_income, as_of=as_of)
            elif validation_summary is None and kind_enum == DocumentKind.STATEMENT:
                extracted_statement = BankStatementExtractor.extract(raw_text)
                extracted_data_dict = extracted_statement.model_dump(mode="json", exclude={"raw_text"})
                validation_summary = DocumentValidator.validate_statement(extracted_statement, as_of=as_of)
        except ValueError:
            extracted_data_dict = {}
            validation_summary = self._extraction_failure(
                "DOC_FIELDS_UNREADABLE", "The document contains incomplete or malformed field amounts; upload a clear copy with explicit values.",
            )

        # 4. Formulate Processed Response
        now = datetime.now(timezone.utc)
        response = ProcessedDocumentResponse(
            document_id=stored_record["document_id"],
            customer_id=customer_id,
            kind=kind_enum,
            original_filename=stored_record["original_filename"],
            mime_type=stored_record["mime_type"],
            file_size_bytes=stored_record["size_bytes"],
            sha256_hash=stored_record["sha256_hash"],
            storage_path=stored_record["stored_path"],
            uploaded_at=datetime.fromisoformat(stored_record["stored_at"]),
            processed_at=now,
            status=validation_summary.status,
            extracted_data=extracted_data_dict,
            validation=validation_summary,
        )
        self.storage.save_processing_result(
            document_id, response.model_dump(mode="json"), customer_id=customer_id, session_id=session_id,
        )
        return response

    @staticmethod
    def _extraction_failure(code: str, reason: str) -> DocumentValidationSummary:
        return DocumentValidationSummary(
            valid=False, status=DocumentProcessingStatus.REJECTED, failed_rules_count=1,
            reasons=[reason], human_review_required=False,
            rules_evaluated=[RuleEvaluation(code=code, description=reason, passed=False, detail=reason)],
        )

    def cross_validate_application(
        self,
        identity_doc: Optional[ExtractedIdentity] = None,
        income_doc: Optional[ExtractedIncome] = None,
        statement_doc: Optional[ExtractedStatement] = None,
    ) -> CrossDocumentValidationSummary:
        """Cross-validate an applicant's dossier across all submitted document types."""
        return DocumentValidator.cross_validate(
            identity=identity_doc,
            income=income_doc,
            statement=statement_doc,
        )

    def get_document_file(self, document_id: str, customer_id: Optional[str] = None):
        """Retrieve stored document bytes with tamper-evidence check."""
        return self.storage.get_document_bytes(document_id, customer_id=customer_id)
