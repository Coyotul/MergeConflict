"""Chunk primitives and utilities."""
from dataclasses import dataclass, field
from datetime import date

from src.models.knowledge import ChunkKind, LinkKind, Product


CHUNKER_VERSION = "1"
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
    current_tokens = 0

    for line in lines:
        line_tokens = estimate_tokens(line)

        # If adding this line would exceed limit and current is not empty, flush
        if current and current_tokens + line_tokens > max_tokens:
            pieces.append("\n".join(current))
            current = []
            current_tokens = 0

        # Add line to current piece
        current.append(line)
        current_tokens += line_tokens

    # Flush remaining
    if current:
        pieces.append("\n".join(current))

    # Add repeat header to all pieces after the first
    if repeat_header and len(pieces) > 1:
        for i in range(1, len(pieces)):
            pieces[i] = repeat_header + "\n" + pieces[i]

    return pieces


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
