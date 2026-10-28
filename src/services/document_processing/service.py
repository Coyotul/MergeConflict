"""Metadata format checks only; no bytes, OCR, extraction or verification."""

from src.core.catalogue import Catalogue
from src.models.banking import DocumentKind, DocumentValidation, RequiredDocuments
from src.models.requests import DocumentInput


class DocumentService:
    def __init__(self, catalogue: Catalogue):
        self.catalogue = catalogue

    def required(self, product_id: str) -> RequiredDocuments:
        product = self.catalogue.product(product_id)
        return RequiredDocuments(
            product_id=product.id, required=product.required_documents,
            optional=[kind for kind in DocumentKind if kind not in product.required_documents],
            allowed_mime_types=["application/pdf", "image/jpeg", "image/png"],
            max_size_bytes=10 * 1024 * 1024, policy_version=product.policy_version,
        )

    @staticmethod
    def validate(input: DocumentInput) -> DocumentValidation:
        return DocumentValidation(
            kind=input.kind,
            reasons=[
                "Filename, declared MIME type and declared size pass metadata validation.",
                "No file content was uploaded or processed. No OCR, extraction or authenticity check occurred.",
                "FORMAT_ACCEPTED does not mean identity, income or document authenticity is verified.",
            ],
        )