"""PDF row rebuilding and text extraction utilities."""
from dataclasses import dataclass
from collections import defaultdict
import pymupdf as fitz

from src.services.document_ingestion.normalize import normalize_text


@dataclass
class Word:
    """A word extracted from a PDF page."""
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


def page_words(page: fitz.Page) -> list[Word]:
    """Extract words from a PDF page.

    Args:
        page: PyMuPDF page object

    Returns:
        List of Word objects with position and text
    """
    words = []
    for word_data in page.get_text("words"):
        # word_data is (x0, y0, x1, y1, "word", block_no, line_no, word_no)
        x0, y0, x1, y1, text = word_data[:5]
        words.append(Word(x0, y0, x1, y1, text))
    return words


def rebuild_rows(words: list[Word], y_tolerance: float = 3.0, column_gap: float = 12.0) -> list[str]:
    """Rebuild text rows from words with column detection.

    Groups words by vertical center within tolerance, sorts each row by x,
    and joins with " | " where the gap exceeds column_gap, else with " ".

    Args:
        words: List of Word objects
        y_tolerance: Maximum vertical distance for words to be on same row
        column_gap: Minimum horizontal gap to insert column separator

    Returns:
        List of text rows
    """
    if not words:
        return []

    # Group words by row based on vertical center
    rows = defaultdict(list)
    for word in words:
        y_center = (word.y0 + word.y1) / 2
        # Find existing row within tolerance
        found_row = None
        for row_y in rows:
            if abs(row_y - y_center) <= y_tolerance:
                found_row = row_y
                break
        if found_row is None:
            found_row = y_center
        rows[found_row].append(word)

    # Sort rows by y coordinate
    sorted_rows = sorted(rows.items(), key=lambda x: x[0])

    # Build text for each row
    result = []
    for _, row_words in sorted_rows:
        # Sort words in row by x coordinate
        row_words.sort(key=lambda w: w.x0)

        # Join words with column detection
        parts = []
        prev_word = None
        for word in row_words:
            if prev_word is None:
                parts.append(word.text)
            else:
                gap = word.x0 - prev_word.x1
                if gap >= column_gap:
                    parts.append(" | ")
                    parts.append(word.text)
                else:
                    parts.append(" ")
                    parts.append(word.text)
            prev_word = word

        result.append("".join(parts))

    return result


def pdf_lines(data: bytes, skip_first_page: bool = False) -> list[tuple[int, str]]:
    """Extract normalized lines from PDF, filtering page furniture.

    Args:
        data: PDF bytes
        skip_first_page: Whether to skip the first page (e.g., cover)

    Returns:
        List of (page_number, line) tuples, 1-indexed pages
    """
    doc = fitz.open(stream=data, filetype="pdf")
    line_pages = defaultdict(set)  # Track which pages each line appears on

    # Get total pages before processing
    total_pages = len(doc) if not skip_first_page else len(doc) - 1

    # First pass: collect all lines and track pages
    all_lines = []
    for page_num in range(len(doc)):
        if skip_first_page and page_num == 0:
            continue

        page = doc[page_num]
        words = page_words(page)
        rows = rebuild_rows(words)

        for row in rows:
            normalized = normalize_text(row)
            if normalized and normalized != "Banking 1:1":
                all_lines.append((page_num + 1, normalized))
                line_pages[normalized].add(page_num + 1)

    doc.close()

    # Filter out lines that appear on >= 50% of pages (only if we have multiple pages)
    # For small documents, don't filter
    lines = []
    if total_pages >= 2:
        threshold = total_pages * 0.5
        for page_num, line in all_lines:
            # Count distinct pages, not occurrences
            if len(line_pages[line]) < threshold:
                lines.append((page_num, line))
    else:
        lines = all_lines

    return lines
