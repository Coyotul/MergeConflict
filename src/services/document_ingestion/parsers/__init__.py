"""Document parsers for ingestion."""
from src.models.knowledge import DocKind
from src.services.document_ingestion.sources import SourceConfig
from src.services.document_ingestion.chunking import ParsedDocument


def parse_document(doc_kind: DocKind, data: bytes, url: str, cfg: SourceConfig) -> ParsedDocument:
    """Parse a document based on its kind.

    Dispatches to the appropriate parser:
    - category_hub → parse_category_hub
    - other HTML kinds → parse_html_page
    - fee_list, general_terms, cost_sheet, pdf_generic → their PDF parsers
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

    # PDF kinds
    if doc_kind == DocKind.fee_list:
        from src.services.document_ingestion.parsers.fee_list import parse_fee_list
        return parse_fee_list(data)

    if doc_kind == DocKind.general_terms:
        from src.services.document_ingestion.parsers.general_terms import parse_general_terms
        return parse_general_terms(data)

    if doc_kind == DocKind.cost_sheet:
        from src.services.document_ingestion.parsers.cost_sheet import parse_cost_sheet
        return parse_cost_sheet(data)

    if doc_kind == DocKind.pdf_generic:
        from src.services.document_ingestion.parsers.pdf_generic import parse_pdf_generic
        return parse_pdf_generic(data)

    raise ValueError(f"Unknown doc_kind: {doc_kind}")
