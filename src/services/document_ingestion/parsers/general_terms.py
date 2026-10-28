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
        # Must start with current chapter number (e.g., "5.1" in chapter 5)
        if current_chapter:
            section_pattern = rf"^({current_chapter}\.(\d+))\.?\s+(.*)"
            section_match = re.match(section_pattern, line)
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
                section_content = section_match.group(3)

                # Extract section title (up to first sub-clause, capped at 90 chars)
                # Sub-clause pattern: N.M.K (e.g., "5.1.1")
                subclause_pattern = rf"(?<!\S){current_chapter}\.\d+\.\d+"
                subclause_match = re.search(subclause_pattern, section_content)
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
    # Sub-clause pattern: N.M.K (e.g., "5.1.1", "5.1.2") using current chapter
    subclause_pattern = rf"(?<!\S)({chapter}\.\d+\.\d+)\.?\s+"
    parts = re.split(subclause_pattern, section_text)

    # Reconstruct sub-clauses
    subclauses = []
    i = 0
    subclause_check = rf"{chapter}\.\d+\.\d+"
    while i < len(parts):
        if i == 0 and not re.match(subclause_check, parts[i]):
            # First part before any subclause number
            if parts[i].strip():
                subclauses.append(parts[i])
            i += 1
        elif i + 1 < len(parts) and re.match(subclause_check, parts[i]):
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

    for clause in clauses:
        clause_tokens = estimate_tokens(clause)

        # If single clause is over limit, window by sentences
        if clause_tokens > MAX_TOKENS:
            # Flush current
            if current:
                result.append("\n".join(current))
                current = []

            # Window this clause
            sentences = re.split(r"(?<=[.;])\s+", clause)
            sent_current = []

            for sent in sentences:
                sent_tokens_est = estimate_tokens(sent)

                # Handle single sentence over limit - hard split by words
                if sent_tokens_est > MAX_TOKENS:
                    # Flush current window
                    if sent_current:
                        result.append(" ".join(sent_current))
                        sent_current = []

                    # Hard split this sentence
                    words = sent.split()
                    word_chunk = []
                    for word in words:
                        # Try adding this word
                        test_chunk = word_chunk + [word]
                        test_text = " ".join(test_chunk)
                        test_tokens = estimate_tokens(test_text)

                        if test_tokens > MAX_TOKENS and word_chunk:
                            # Flush what we have
                            result.append(" ".join(word_chunk))
                            word_chunk = [word]
                        else:
                            word_chunk.append(word)

                    if word_chunk:
                        result.append(" ".join(word_chunk))
                    continue

                # Estimate the joined window, not the sum of its parts
                if sent_current and estimate_tokens(" ".join(sent_current + [sent])) > MAX_TOKENS:
                    result.append(" ".join(sent_current))
                    # Overlap: start next window with last sentence, if it still fits
                    overlap = sent_current[-1]
                    if estimate_tokens(" ".join([overlap, sent])) > MAX_TOKENS:
                        sent_current = [sent]
                    else:
                        sent_current = [overlap, sent]
                else:
                    sent_current.append(sent)

            if sent_current:
                result.append(" ".join(sent_current))
        else:
            # Normal packing: estimate the joined chunk, not the sum of its parts
            if current and estimate_tokens("\n".join(current + [clause])) > MAX_TOKENS:
                result.append("\n".join(current))
                current = []

            current.append(clause)

    # Flush remaining
    if current:
        result.append("\n".join(current))

    return result
