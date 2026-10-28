"""Fee list PDF parser."""
import re
import unicodedata
from src.services.document_ingestion.chunking import (
    ChunkDraft,
    ParsedDocument,
    pack_lines,
    MAX_TOKENS,
    CHUNKER_VERSION,
)
from src.services.document_ingestion.parsers.pdf_rows import pdf_lines
from src.models.knowledge import ChunkKind


def _fold(text: str) -> str:
    """Lower-case and strip diacritics, for accent-insensitive matching."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def is_section_heading(line: str) -> bool:
    r"""Check if a line is a section heading.

    A section heading must:
    - Match pattern: ^\d+(\.\d+)*\.?\s+\S
    - Contain no |
    - Be shorter than 120 chars
    - Not be a value line
    """
    # Must match numbering pattern
    if not re.match(r"^\d+(\.\d+)*\.?\s+\S", line):
        return False

    # Must not contain column separator
    if "|" in line:
        return False

    # Must be short enough
    if len(line) >= 120:
        return False

    # Must not be a value line (accent-insensitive). A unit must not run on
    # into a word, so "1. Europa" stays a heading while "30 EUR/intrare" does not.
    folded = _fold(line)
    unit_end = r"(?![a-z])"
    # Whole line is an amount: "100 lei", "1.5 lei", "2.50 lei", "60 euro sau ..."
    if re.match(r"^\d[\d.,]*\s*(lei|euro|eur|usd|%)" + unit_end, folded):
        return False
    # Bare count followed by a unit: "5 intrari pe luna", "10 intrari gratuite"
    if re.match(r"^\d+\s+(leu|intrari|intrare)" + unit_end, folded):
        return False
    # Remainder after the number starts with an amount: "2. 5 lei", "3. 10% din suma"
    remainder = re.match(r"^\d+(?:\.\d+)*\.?\s+(.*)", folded).group(1)
    if re.match(r"^\d[\d.,]*\s*(lei|euro|eur|usd|%|leu|intrari)" + unit_end, remainder):
        return False

    return True


def parse_fee_list(data: bytes) -> ParsedDocument:
    """Parse a fee list PDF.

    Args:
        data: PDF bytes

    Returns:
        ParsedDocument with fee_table chunks
    """
    lines = pdf_lines(data, skip_first_page=True)

    # Extract title from cover page
    all_lines_with_cover = pdf_lines(data, skip_first_page=False)
    title = "Tarife și comisioane"
    for _, line in all_lines_with_cover[:10]:  # Check first 10 lines
        if "tarife" in line.lower():
            title = line
            break

    chunks = []
    current_section_path = []
    current_section_lines = []
    current_section_page = None
    column_header = None
    depth_1_heading = None  # Track current depth-1 heading

    for page_num, line in lines:
        if is_section_heading(line):
            # Check if this is a repeated heading (continuation page)
            # It's a repeat if it equals the current depth-1 or depth-2 heading
            if line in current_section_path:
                # Repeated heading on continuation page - don't flush, don't update page
                continue

            # Parse new section
            match = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.*)", line)
            number = match.group(1)

            # Determine depth
            depth = number.count(".") + 1

            # Flush previous section on ANY new heading
            if current_section_lines:
                _flush_section(
                    chunks,
                    current_section_path,
                    current_section_lines,
                    current_section_page,
                    column_header,
                )
                current_section_lines = []

            # Reset column header for new section
            column_header = None

            # Update section path based on depth
            if depth == 1:
                current_section_path = [line]
                depth_1_heading = line
            else:
                # Depth >= 2: use current depth-1 heading and this heading
                if depth_1_heading:
                    current_section_path = [depth_1_heading, line]
                else:
                    current_section_path = [line]

            # Set page to where this section starts
            current_section_page = page_num
        else:
            # Content line
            if current_section_path:
                # Check if this is a column header row (first | line with no digits in last cell)
                if column_header is None and "|" in line:
                    parts = line.split(" | ")
                    if parts and not re.search(r"\d", parts[-1]):
                        column_header = line
                current_section_lines.append(line)

    # Flush last section
    if current_section_lines:
        _flush_section(
            chunks,
            current_section_path,
            current_section_lines,
            current_section_page,
            column_header,
        )

    return ParsedDocument(
        title=title,
        chunks=chunks,
        # The cover carries the edition date: it is metadata text, but never chunk text.
        metadata_text="\n".join([line for page, line in all_lines_with_cover if page == 1] + [line for _, line in lines]),
        parser_name="fee_list",
        parser_version=CHUNKER_VERSION,
    )


def _flush_section(
    chunks: list[ChunkDraft],
    section_path: list[str],
    lines: list[str],
    page: int,
    column_header: str | None,
) -> None:
    """Flush accumulated section lines as chunks."""
    if not lines or not section_path:
        return

    # Pack lines into chunks
    pieces = pack_lines(lines, max_tokens=MAX_TOKENS, repeat_header=column_header)

    for piece in pieces:
        chunks.append(
            ChunkDraft(
                kind=ChunkKind.fee_table,
                section_path=section_path.copy(),
                text=piece,
                page=page,
            )
        )
