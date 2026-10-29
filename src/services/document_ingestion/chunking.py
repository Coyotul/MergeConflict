"""Chunk primitives and utilities."""
import re
from dataclasses import dataclass, field
from datetime import date

from src.models.knowledge import ChunkKind, LinkKind, Product


CHUNKER_VERSION = "2"
MAX_TOKENS = 500


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length."""
    return max(1, len(text) // 4)


@dataclass
class ExtractedLink:
    """A link extracted from document content."""
    target_url: str  # absolute, no query or fragment
    anchor_text: str
    link_kind: LinkKind


@dataclass
class ChunkDraft:
    """A draft chunk before final storage."""
    kind: ChunkKind
    section_path: list[str]
    text: str
    page: int | None = None
    anchor: str | None = None
    products_override: list[Product] | None = None
    links: list[ExtractedLink] = field(default_factory=list)


@dataclass
class ParsedDocument:
    """Result of parsing a document."""
    title: str
    chunks: list[ChunkDraft]
    metadata_text: str  # cleaned full text for date/campaign detection
    parser_name: str
    parser_version: str = CHUNKER_VERSION
    warnings: list[str] = field(default_factory=list)


def pack_lines(lines: list[str], max_tokens: int = MAX_TOKENS, repeat_header: str | None = None) -> list[str]:
    """Pack lines into chunks respecting token limits.

    Greedy packing on line boundaries. A single line over the limit becomes
    its own piece and is not split. repeat_header is prepended to every piece
    after the first.
    """
    if not lines:
        return []

    pieces = []
    current = []

    for line in lines:
        # Estimate the joined candidate piece, including the header that will
        # be prepended to it if it is not the first piece.
        prefix = [repeat_header] if repeat_header and pieces else []
        if current and estimate_tokens("\n".join(prefix + current + [line])) > max_tokens:
            pieces.append("\n".join(current))
            current = []

        current.append(line)

    # Flush remaining
    if current:
        pieces.append("\n".join(current))

    # Add repeat header to all pieces after the first
    if repeat_header and len(pieces) > 1:
        for i in range(1, len(pieces)):
            pieces[i] = repeat_header + "\n" + pieces[i]

    return pieces


def split_long_text(text: str, max_tokens: int = MAX_TOKENS) -> list[str]:
    """Split text over max_tokens into pieces of at most max_tokens.

    Packs whole sentences; a sentence that alone exceeds the limit is packed by words,
    and a word that alone exceeds it is cut by characters. Text within the limit is
    returned as one piece. For prose only: atomic units (a FAQ pair, a worked example,
    a table row) are never passed here.
    """
    if estimate_tokens(text) <= max_tokens:
        return [text]
    max_chars = max_tokens * 4 + 3  # estimate_tokens(s) <= max_tokens  <=>  len(s) < 4 * (max_tokens + 1)

    def pack(parts: list[str], split_part) -> list[str]:
        pieces: list[str] = []
        current = ""
        for part in parts:
            if len(part) > max_chars:
                if current:
                    pieces.append(current)
                    current = ""
                pieces.extend(split_part(part))
                continue
            candidate = f"{current} {part}" if current else part
            if len(candidate) > max_chars:
                pieces.append(current)
                candidate = part
            current = candidate
        if current:
            pieces.append(current)
        return pieces

    def by_chars(word: str) -> list[str]:
        return [word[i:i + max_chars] for i in range(0, len(word), max_chars)]

    def by_words(sentence: str) -> list[str]:
        return pack(sentence.split(), by_chars)

    return pack(re.split(r"(?<=[.!?;])\s+", text.strip()), by_words)


def build_header(title: str, section_path: list[str], effective_date: date) -> str:
    """Build chunk header.

    Format: "Raiffeisen Bank › {title} › {p1} › {p2} · {YYYY-MM-DD}"
    Empty path parts are skipped. With no path, the format is
    "Raiffeisen Bank › {title} · {date}".
    """
    parts = ["Raiffeisen Bank", title]

    # Add non-empty path parts
    for part in section_path:
        if part:
            parts.append(part)

    header = " › ".join(parts)
    header += f" · {effective_date}"

    return header
