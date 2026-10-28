from fastapi import APIRouter

from src.api.gateway.dependencies import Context, Services
from src.api.gateway.errors import ERROR_RESPONSES
from src.models.banking import DocumentValidation, PolicySearchResult, Product, RequiredDocuments
from src.models.common import ApiResponse
from src.models.requests import DocumentInput, PolicySearchInput


router = APIRouter(tags=["Products and evidence"], responses=ERROR_RESPONSES)


@router.get("/products", operation_id="get_credit_products")
def products(context: Context, services: Services) -> ApiResponse[list[Product]]:
    return ApiResponse(data=list(services.catalogue.products))


@router.get("/products/{product_id}/required-documents", operation_id="get_required_documents")
def required_documents(product_id: str, context: Context, services: Services) -> ApiResponse[RequiredDocuments]:
    return ApiResponse(data=services.documents.required(product_id))


@router.post("/policies/search", operation_id="search_banking_policies")
def search_policies(input: PolicySearchInput, context: Context, services: Services) -> ApiResponse[PolicySearchResult]:
    """Keyword search over versioned fictional sources; not semantic RAG."""
    return ApiResponse(data=services.retrieval.search(input))


@router.post("/documents/validate", operation_id="validate_document")
def validate_document(input: DocumentInput, context: Context, services: Services) -> ApiResponse[DocumentValidation]:
    """Validate metadata shape only. Does not upload, OCR or verify any file."""
    return ApiResponse(data=services.documents.validate(input))