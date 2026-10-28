"""PDF test fixture builders using PyMuPDF."""
import pymupdf as fitz
from pathlib import Path


# Use Arial font for Romanian diacritic support
FONT_FILE = Path("C:/Windows/Fonts/arial.ttf")


def make_pdf(pages: list[list[tuple[float, float, str]]], fontsize: float = 9) -> bytes:
    """Build a PDF from positioned text spans.

    Args:
        pages: Each page is a list of (x, y, text) tuples for TextWriter calls
        fontsize: Font size for text

    Returns:
        PDF bytes
    """
    doc = fitz.open()

    # Load font once for all pages
    font = fitz.Font(fontfile=str(FONT_FILE))

    for page_items in pages:
        page = doc.new_page(width=595, height=842)  # A4 size
        tw = fitz.TextWriter(page.rect)

        for x, y, text in page_items:
            # Use TextWriter for proper font embedding
            tw.append((x, y), text, font=font, fontsize=fontsize)

        tw.write_text(page)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def make_pdf_from_lines(lines: list[str], fontsize: float = 6) -> bytes:
    """Build a PDF from text lines with automatic pagination and wrapping.

    Args:
        lines: Text lines to write
        fontsize: Font size for text (small fontsize to fit long lines)

    Returns:
        PDF bytes
    """
    doc = fitz.open()

    # Load font for proper diacritic support
    font = fitz.Font(fontfile=str(FONT_FILE))

    line_height = fontsize + 2  # Spacing between lines
    margin_left = 50
    margin_top = 50
    page_width = 595 - 100  # A4 width minus margins
    page_height = 842 - 100  # A4 height minus margins

    page = None
    y_position = margin_top
    tw = None

    def new_page():
        nonlocal page, y_position, tw
        if tw is not None:
            tw.write_text(page)
        page = doc.new_page(width=595, height=842)
        y_position = margin_top
        tw = fitz.TextWriter(page.rect)

    for line in lines:
        if page is None:
            new_page()

        # Wrap text manually by words
        words = line.split()
        current_line = ""
        x_position = margin_left

        for word in words:
            if font.text_length(word, fontsize=fontsize) > page_width:
                raise ValueError(f"word wider than the page, it would be clipped: {word[:40]!r}")
            test_line = current_line + (" " if current_line else "") + word
            # Estimate width (rough approximation)
            text_width = font.text_length(test_line, fontsize=fontsize)

            if text_width > page_width and current_line:
                # Write current line and start new one
                if y_position + line_height > margin_top + page_height:
                    new_page()

                tw.append((margin_left, y_position), current_line, font=font, fontsize=fontsize)
                y_position += line_height
                current_line = word
            else:
                current_line = test_line

        # Write remaining text
        if current_line:
            if y_position + line_height > margin_top + page_height:
                new_page()

            tw.append((margin_left, y_position), current_line, font=font, fontsize=fontsize)
            y_position += line_height

    # Write final page
    if tw is not None:
        tw.write_text(page)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
