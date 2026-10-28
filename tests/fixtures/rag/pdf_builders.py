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


def make_pdf_from_lines(lines: list[str], per_page: int = 40, fontsize: float = 6) -> bytes:
    """Build a PDF from text lines with automatic pagination and wrapping.

    Args:
        lines: Text lines to write
        per_page: Maximum lines per page
        fontsize: Font size for text (small fontsize to fit long lines)

    Returns:
        PDF bytes
    """
    doc = fitz.open()

    line_height = fontsize + 2  # Spacing between lines
    margin_left = 50
    margin_top = 50
    page_width = 595 - 100  # A4 width minus margins
    page_height = 842 - 100  # A4 height minus margins

    page = None
    y_position = margin_top

    for line in lines:
        if page is None:
            page = doc.new_page(width=595, height=842)
            y_position = margin_top

        # Calculate rough height needed for this textbox
        # Estimate 80-100 chars per line at fontsize 6
        estimated_lines = max(1, len(line) // 90)
        box_height = estimated_lines * line_height + 5

        # Check if we need a new page
        if y_position + box_height > margin_top + page_height:
            page = doc.new_page(width=595, height=842)
            y_position = margin_top

        # Use insert_textbox for automatic wrapping
        rect = fitz.Rect(margin_left, y_position, margin_left + page_width, y_position + box_height + 10)
        page.insert_textbox(rect, line, fontsize=fontsize, align=0)

        y_position += box_height

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
