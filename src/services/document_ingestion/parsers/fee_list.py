"""Fee list PDF parser."""
import re
from src.services.document_ingestion.chunking import (
    ChunkDraft,
    ParsedDocument,
    pack_lines,
    MAX_TOKENS,
    CHUNKER_VERSION,
)
from src.services.document_ingestion.parsers.pdf_rows import pdf_lines
from src.models.knowledge import ChunkKind


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

    # Must not be a value line
    # Lines starting with just a number (no dots) followed by currency/unit are value lines
    if re.match(r"^\d+\s+(lei|euro|eur|usd|leu|intrari|intrare)", line, re.IGNORECASE):
        return False

    # Check if entire line matches value patterns
    value_patterns = [
        r"^\d[\d.,]*\s*(lei|euro|eur|usd|%)(\s|/|$)",  # Numbers with currency
        r"^\d+\s+(lei|euro|eur|usd|intrari|intrare)",  # "10 lei", "10 intrari"
        r"^\d+\s+intrări\s+gratuite",  # "10 intrări gratuite pe an,"
    ]
    for pattern in value_patterns:
        if re.match(pattern, line, re.IGNORECASE):
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
    current_section = None
    current_section_path = []
    current_section_lines = []
    current_section_page = None
    column_header = None

    for page_num, line in lines:
        if is_section_heading(line):
            # Parse new section
            match = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.*)", line)
            number = match.group(1)

            # Determine depth
            depth = number.count(".") + 1

            # Get the top-level number
            top_level_num = number.split(".")[0]

            # Check if we're changing top-level section
            current_top_level = None
            if current_section_path:
                current_match = re.match(r"^(\d+)", current_section_path[0])
                if current_match:
                    current_top_level = current_match.group(1)

            # Flush if we're moving to a different top-level section
            if current_top_level is not None and top_level_num != current_top_level:
                if current_section_lines:
                    _flush_section(
                        chunks,
                        current_section_path,
                        current_section_lines,
                        current_section_page,
                        column_header,
                    )
                    current_section_lines = []
                    column_header = None

            # Update section path based on depth
            if depth == 1:
                current_section_path = [line]
            else:
                # Keep first element (top-level section), update/add subsection
                if current_section_path:
                    current_section_path = [current_section_path[0], line]
                else:
                    current_section_path = [line]

            if current_section_page is None or depth == 1:
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
        metadata_text="\n".join(line for _, line in lines),
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
