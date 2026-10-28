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
                spans = [s for s in line["spans"] if s["text"].strip()]
                text = normalize_text("".join(s["text"] for s in spans))
                if text:
                    bold = all(s["flags"] & BOLD_FLAG for s in spans)
                    lines.append((page_num, text, bold))
    doc.close()
    return lines


def _is_heading(text: str, bold: bool) -> bool:
    if NUMBERED_HEADING_RE.match(text) and len(text) < 120:
        return True
    return bold and len(text) < 100


def parse_pdf_generic(data: bytes) -> ParsedDocument:
    """Parse a PDF into generic chunks.

    A short document (under 600 estimated tokens) becomes one chunk with no
    section path. A longer one is split on heading lines (numbered, or bold and
    short), and each section is packed with pack_lines.
    """
    lines = _text_lines(data)
    full_text = "\n".join(text for _, text, _ in lines)
    title = lines[0][1] if lines else ""

    chunks: list[ChunkDraft] = []
    if lines and estimate_tokens(full_text) < SHORT_DOCUMENT_TOKENS:
        chunks.append(ChunkDraft(kind=ChunkKind.generic, section_path=[], text=full_text, page=lines[0][0]))
    elif lines:
        # Sections: (path, start page, body lines). The title line is not body text.
        sections: list[tuple[list[str], int, list[str]]] = [([], lines[0][0], [])]
        for i, (page, text, bold) in enumerate(lines):
            if _is_heading(text, bold):
                sections.append(([text], page, []))
            elif i > 0:
                sections[-1][2].append(text)
        for path, page, body in sections:
            for piece in pack_lines(body):
                chunks.append(ChunkDraft(kind=ChunkKind.generic, section_path=list(path), text=piece, page=page))

    return ParsedDocument(
        title=title,
        chunks=chunks,
        metadata_text=full_text,
        parser_name="pdf_generic",
        parser_version=CHUNKER_VERSION,
    )
