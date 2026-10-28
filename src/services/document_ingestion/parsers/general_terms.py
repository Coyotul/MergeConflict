"""General terms PDF parser."""
import re
from src.services.document_ingestion.chunking import (
    ChunkDraft,
    ParsedDocument,
    estimate_tokens,
    MAX_TOKENS,
    CHUNKER_VERSION,
)
from src.services.document_ingestion.parsers.pdf_rows import pdf_lines
from src.models.knowledge import ChunkKind


def parse_general_terms(data: bytes) -> ParsedDocument:
    """Parse a general terms PDF.

    Args:
        data: PDF bytes

    Returns:
        ParsedDocument with clause chunks
    """
    lines = pdf_lines(data, skip_first_page=False)

    # Title is first line
    title = lines[0][1] if lines else "Condiții generale"

    chunks = []
    current_chapter = None
    current_chapter_title = None
    current_section_num = None
    current_section_title = None
    current_section_text = []

    for page_num, line in lines:
        # Check for chapter
        chapter_match = re.match(r"^(\d+)\.\s+([A-ZĂÂÎȘȚ][A-ZĂÂÎȘȚ ,\-]{5,})$", line)
        if chapter_match:
            # Flush previous section
            if current_section_text:
                _flush_section(
                    chunks,
                    current_chapter,
                    current_chapter_title,
                    current_section_num,
                    current_section_title,
                    current_section_text,
                )
                current_section_text = []
                current_section_num = None
                current_section_title = None

            current_chapter = chapter_match.group(1)
            current_chapter_title = chapter_match.group(2).title()
            continue

        # Check for section within a chapter
        # Can be either "N.M" format (e.g., "N.1") or numeric (e.g., "5.1")
        if current_chapter:
            section_match = re.match(r"^((?:N\.\d+)|\d+\.\d+)\.?\s+(.*)", line)
            if section_match:
                # Flush previous section
                if current_section_text:
                    _flush_section(
                        chunks,
                        current_chapter,
                        current_chapter_title,
                        current_section_num,
                        current_section_title,
                        current_section_text,
                    )

                current_section_num = section_match.group(1)
                section_content = section_match.group(2)

                # Extract section title (up to first sub-clause, capped at 90 chars)
                # Sub-clause pattern: N.M.K (e.g., "5.1.1" or "N.1.1")
                subclause_match = re.search(r"(?<!\S)(?:(?:N\.\d+\.\d+)|\d+\.\d+\.\d+)", section_content)
                if subclause_match:
                    current_section_title = section_content[:subclause_match.start()].strip()
                else:
                    current_section_title = section_content

                # Cap at 90 chars
                if len(current_section_title) > 90:
                    current_section_title = current_section_title[:90]

                current_section_text = [section_content]
            else:
                # Continue current section
                if current_section_num:
                    current_section_text.append(line)

    # Flush last section
    if current_section_text:
        _flush_section(
            chunks,
            current_chapter,
            current_chapter_title,
            current_section_num,
            current_section_title,
            current_section_text,
        )

    return ParsedDocument(
        title=title,
        chunks=chunks,
        metadata_text="\n".join(line for _, line in lines),
        parser_name="general_terms",
        parser_version=CHUNKER_VERSION,
    )


def _flush_section(
    chunks: list[ChunkDraft],
    chapter: str,
    chapter_title: str,
    section_num: str,
    section_title: str,
    text_lines: list[str],
) -> None:
    """Flush a section as one or more chunks."""
    if not text_lines or not chapter or not section_num:
        return

    section_text = "\n".join(text_lines)
    section_path = [f"{chapter}. {chapter_title}", f"{section_num} {section_title}"]

    # Check if section is short enough for single chunk
    if estimate_tokens(section_text) <= MAX_TOKENS:
        chunks.append(
            ChunkDraft(
                kind=ChunkKind.clause,
                section_path=section_path,
                text=section_text,
            )
        )
        return

    # Long section: split by sub-clauses
    # Split at sub-clause numbers, even mid-line
    # Sub-clause pattern: N.M.K (e.g., "5.1.1", "5.1.2", "N.1.1")
    subclause_pattern = r"(?<!\S)((?:(?:N\.\d+\.\d+)|\d+\.\d+\.\d+))\.?\s+"
    parts = re.split(subclause_pattern, section_text)

    # Reconstruct sub-clauses
    subclauses = []
    i = 0
    while i < len(parts):
        if i == 0 and not re.match(r"(?:(?:N\.\d+\.\d+)|\d+\.\d+\.\d+)", parts[i]):
            # First part before any subclause number
            if parts[i].strip():
                subclauses.append(parts[i])
            i += 1
        elif i + 1 < len(parts) and re.match(r"(?:(?:N\.\d+\.\d+)|\d+\.\d+\.\d+)", parts[i]):
            # This is a subclause number followed by its text
            subclauses.append(parts[i] + " " + parts[i + 1])
            i += 2
        else:
            if parts[i].strip():
                subclauses.append(parts[i])
            i += 1

    # Pack sub-clauses
    packed = _pack_clauses(subclauses)

    for piece in packed:
        chunks.append(
            ChunkDraft(
                kind=ChunkKind.clause,
                section_path=section_path.copy(),
                text=piece,
            )
        )


def _pack_clauses(clauses: list[str]) -> list[str]:
    """Pack clauses up to MAX_TOKENS with sentence windowing for over-long ones."""
    if not clauses:
        return []

    result = []
    current = []
    current_tokens = 0

    for clause in clauses:
        clause_tokens = estimate_tokens(clause)

        # If single clause is over limit, window by sentences
        if clause_tokens > MAX_TOKENS:
            # Flush current
            if current:
                result.append("\n".join(current))
                current = []
                current_tokens = 0

            # Window this clause
            sentences = re.split(r"(?<=[.;])\s+", clause)
            sent_current = []
            sent_tokens = 0

            for i, sent in enumerate(sentences):
                sent_tokens_est = estimate_tokens(sent)

                if sent_current and sent_tokens + sent_tokens_est > MAX_TOKENS:
                    result.append(" ".join(sent_current))
                    # Overlap: start next window with last sentence
                    sent_current = [sent_current[-1] if sent_current else ""]
                    sent_tokens = estimate_tokens(sent_current[0]) if sent_current else 0

                sent_current.append(sent)
                sent_tokens += sent_tokens_est

            if sent_current:
                result.append(" ".join(sent_current))
        else:
            # Normal packing
            if current and current_tokens + clause_tokens > MAX_TOKENS:
                result.append("\n".join(current))
                current = []
                current_tokens = 0

            current.append(clause)
            current_tokens += clause_tokens

    # Flush remaining
    if current:
        result.append("\n".join(current))

    return result
