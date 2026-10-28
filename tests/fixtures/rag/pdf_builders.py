"""PDF test fixture builders using PyMuPDF."""
import pymupdf as fitz


def make_pdf(pages: list[list[tuple[float, float, str]]], fontsize: float = 9) -> bytes:
    """Build a PDF from positioned text spans.

    Args:
        pages: Each page is a list of (x, y, text) tuples for insert_text calls
        fontsize: Font size for text

    Returns:
        PDF bytes
    """
    doc = fitz.open()

    for page_items in pages:
        page = doc.new_page(width=595, height=842)  # A4 size
        for x, y, text in page_items:
            # Use default font which supports Unicode/diacritics
            page.insert_text((x, y), text, fontsize=fontsize)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def make_pdf_from_lines(lines: list[str], per_page: int = 40, fontsize: float = 9) -> bytes:
    """Build a PDF from text lines with automatic pagination.

    Args:
        lines: Text lines to write
        per_page: Maximum lines per page
        fontsize: Font size for text

    Returns:
        PDF bytes
    """
    doc = fitz.open()

    line_height = fontsize + 4  # Spacing between lines
    margin_left = 50
    margin_top = 50

    page = None
    line_count = 0

    for line in lines:
        if page is None or line_count >= per_page:
            page = doc.new_page(width=595, height=842)
            line_count = 0

        y = margin_top + line_count * line_height

        # Use insert_text for simple line insertion
        # For long lines, they'll just extend beyond the page (PyMuPDF will still extract them)
        page.insert_text((margin_left, y), line, fontsize=fontsize)

        line_count += 1

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
