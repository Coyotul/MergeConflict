"""Document Processing Service orchestrator.

Coordinates OCR extraction, multi-rule regulatory validation and secure storage
for applicant credit documents.
"""

from datetime import datetime, timezone
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.models.document_processing import (
    CrossDocumentValidationSummary,
    DocumentKind,
    DocumentProcessingStatus,
    DocumentValidationSummary,
    ExtractedIdentity,
    ExtractedIncome,
    ExtractedStatement,
    ProcessedDocumentResponse,
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

        # 2. OCR & Text Extraction
        raw_text = ""
        if mime_type.lower() == "application/pdf" or filename.lower().endswith(".pdf"):
            try:
                raw_text = PdfExtractor.extract_text(content_bytes)
            except Exception as exc:
                raw_text = f"[OCR Extraction Warning: {exc}]"
        else:
            raw_text = f"[Image/Binary Document: {filename}]"

        # 3. Field Extraction based on document kind
        extracted_data_dict: Dict[str, Any] = {}
        validation_summary: DocumentValidationSummary

        if kind_enum == DocumentKind.IDENTITY:
            extracted_identity = IdCardExtractor.extract(raw_text)
            extracted_data_dict = extracted_identity.model_dump(mode="json")
            validation_summary = DocumentValidator.validate_identity(
                extracted_identity,
                allow_synthetic_cnp=allow_synthetic_cnp,
            )

        elif kind_enum == DocumentKind.INCOME:
            extracted_income = IncomeCertificateExtractor.extract(raw_text)
            extracted_data_dict = extracted_income.model_dump(mode="json")
            validation_summary = DocumentValidator.validate_income(extracted_income)

        elif kind_enum == DocumentKind.STATEMENT:
            extracted_statement = BankStatementExtractor.extract(raw_text)
            extracted_data_dict = extracted_statement.model_dump(mode="json")
            validation_summary = DocumentValidator.validate_statement(extracted_statement)

        else:
            raise ValueError(f"Unsupported document kind '{kind_enum}'.")

        # 4. Formulate Processed Response
        now = datetime.now(timezone.utc)
        return ProcessedDocumentResponse(
            document_id=stored_record["document_id"],
            customer_id=customer_id,
            kind=kind_enum,
            original_filename=filename,
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
