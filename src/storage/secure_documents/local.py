"""Local filesystem storage for uploaded customer documents."""
import re
from pathlib import Path

MAX_FILENAME_LENGTH = 100
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def sanitize_filename(filename: str) -> str:
    """Keep only [A-Za-z0-9._-], truncated to 100 characters.

    A name that ends up empty (or only dots) becomes "upload".
    """
    cleaned = _UNSAFE_CHARS.sub("", filename)[:MAX_FILENAME_LENGTH]
    if not cleaned.strip("."):
        return "upload"
    return cleaned


class LocalDocumentStorage:
    """Writes uploads to <root>/<session_id>/<document_id>-<sanitized filename>."""

    def __init__(self, root: Path):
        self._root = Path(root)

    def save(self, session_id: str, document_id: str, filename: str, data: bytes) -> Path:
        """Write `data` and return its path. Raises ValueError for unsafe ids."""
        for name, value in (("session_id", session_id), ("document_id", document_id)):
            if not _SAFE_ID.match(value):
                raise ValueError(f"unsafe {name}: {value!r}")
        root = self._root.resolve()
        path = root / session_id / f"{document_id}-{sanitize_filename(filename)}"
        if not path.resolve().is_relative_to(root):
            raise ValueError("upload path escapes the storage root")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
