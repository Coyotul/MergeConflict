"""Document parsers for ingestion."""
from src.models.knowledge import DocKind
from src.services.document_ingestion.sources import SourceConfig
from src.services.document_ingestion.chunking import ParsedDocument


def parse_document(doc_kind: DocKind, data: bytes, url: str, cfg: SourceConfig) -> ParsedDocument:
    """Parse a document based on its kind.

    Dispatches to the appropriate parser:
    - category_hub → parse_category_hub
    - other HTML kinds → parse_html_page
    - PDF kinds → parsers from Tasks 5-6 (NotImplementedError for now)
    """
    from src.services.document_ingestion.parsers.html_page import parse_html_page
    from src.services.document_ingestion.parsers.category_hub import parse_category_hub

    # Category hub
    if doc_kind == DocKind.category_hub:
        return parse_category_hub(data, url, cfg)

    # HTML kinds
    html_kinds = {
        DocKind.product_page,
        DocKind.guide,
        DocKind.faq_page,
        DocKind.article,
    }
    if doc_kind in html_kinds:
        return parse_html_page(data, url, cfg)

    # PDF kinds (not yet implemented)
    pdf_kinds = {
        DocKind.fee_list,
        DocKind.general_terms,
        DocKind.cost_sheet,
        DocKind.pdf_generic,
    }
    if doc_kind in pdf_kinds:
        raise NotImplementedError(f"PDF parsing for {doc_kind} comes in Tasks 5-6")

    raise ValueError(f"Unknown doc_kind: {doc_kind}")
