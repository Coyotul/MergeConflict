"""Crawl manifest: one JSON object per fetched URL (JSON lines)."""
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel


class ManifestEntry(BaseModel):
    """One fetched URL and where its raw bytes are stored."""
    url: str
    final_url: str
    fetched_at: datetime
    status_code: int | None
    content_type: str | None
    sitemap_lastmod: date | None
    sha256: str | None
    raw_path: str | None
    error: str | None = None
    index: bool = True
    withdrawn: bool = False


def read_manifest(path: Path) -> list[ManifestEntry]:
    """Read every entry from a JSON lines manifest, skipping blank lines."""
    with open(path, encoding="utf-8") as f:
        return [ManifestEntry.model_validate_json(line) for line in f if line.strip()]


def write_manifest(path: Path, entries: list[ManifestEntry]) -> None:
    """Rewrite the whole manifest with the given entries."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for e in entries:
            f.write(e.model_dump_json() + "\n")
