"""Generic PDF parser for PDFs without a dedicated template."""
import re

import pymupdf as fitz

from src.models.knowledge import ChunkKind
from src.services.document_ingestion.chunking import (
    CHUNKER_VERSION,
    ChunkDraft,
    ParsedDocument,
    estimate_tokens,
    pack_lines,
)
from src.services.document_ingestion.normalize import normalize_text

SHORT_DOCUMENT_TOKENS = 600
BOLD_FLAG = 16
NUMBERED_HEADING_RE = re.compile(r"^\d+\.\s+\S")


def _text_lines(data: bytes) -> list[tuple[int, str, bool]]:
    """(page, text, all_spans_bold) for every non-empty text line, 1-indexed pages."""
    doc = fitz.open(stream=data, filetype="pdf")
    lines = []
    for page_num, page in enumerate(doc, start=1):
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                # Whitespace-only spans separate words, so they are joined too; only
                # the spans with visible text decide whether the line is bold.
                text = normalize_text("".join(s["text"] for s in line["spans"]))
                if text:
                    bold = all(s["flags"] & BOLD_FLAG for s in line["spans"] if s["text"].strip())
                    lines.append((page_num, text, bold))
    doc.close()
    return lines


def _is_heading(text: str, bold: bool) -> bool:
    if NUMBERED_HEADING_RE.match(text) and len(text) < 120:
        return True
    return bold and len(text) < 100


class _Section:
    def __init__(self, path: list[str], page: int, body: list[str]):
        self.path = path
        self.page = page
        self.body = body
        self.has_own_body = False


def _sections(lines: list[tuple[int, str, bool]]) -> list[_Section]:
    """Split the lines after the title into sections on heading lines.

    A bold heading nests under the numbered heading before it. A heading with no
    body of its own (a bold table cell, a heading directly followed by another) is
    not lost: its text and its carried lines open the next section's body, unless it
    is the next section's parent.
    """
    sections = [_Section([], lines[0][0], [])]
    parent: str | None = None
    for page, text, bold in lines[1:]:
        if not _is_heading(text, bold):
            sections[-1].body.append(text)
            sections[-1].has_own_body = True
            continue
        numbered = bool(NUMBERED_HEADING_RE.match(text))
        path = [text] if numbered or parent is None else [parent, text]
        carried: list[str] = []
        previous = sections[-1]
        if not previous.has_own_body:
            sections.pop()
            carried = list(previous.body)
            heading = previous.path[-1] if previous.path else None
            if heading and heading not in path and carried[-1:] != [heading]:
                carried.append(heading)
        # A heading continuing a run of body-less headings (e.g. table cells) is text too.
        sections.append(_Section(path, page, carried + [text] if carried else []))
        parent = text if numbered else parent
    last = sections[-1]
    if not last.has_own_body and last.path and last.path[-1] not in last.body:
        last.body.append(last.path[-1])
    return sections


def parse_pdf_generic(data: bytes) -> ParsedDocument:
    """Parse a PDF into generic chunks.

    A short document (under 600 estimated tokens) becomes one chunk with no
    section path. A longer one is split on heading lines (numbered, or bold and
    short; see _sections), and each section is packed with pack_lines.
    """
    lines = _text_lines(data)
    full_text = "\n".join(text for _, text, _ in lines)
    title = lines[0][1] if lines else ""

    chunks: list[ChunkDraft] = []
    if lines and estimate_tokens(full_text) < SHORT_DOCUMENT_TOKENS:
        chunks.append(ChunkDraft(kind=ChunkKind.generic, section_path=[], text=full_text, page=lines[0][0]))
    elif lines:
        for section in _sections(lines):
            for piece in pack_lines(section.body):
                chunks.append(ChunkDraft(kind=ChunkKind.generic, section_path=list(section.path), text=piece,
                                         page=section.page))

    return ParsedDocument(
        title=title,
        chunks=chunks,
        metadata_text=full_text,
        parser_name="pdf_generic",
        parser_version=CHUNKER_VERSION,
    )
