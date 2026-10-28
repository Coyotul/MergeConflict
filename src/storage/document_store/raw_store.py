"""Content-addressed store for raw fetched files."""
import hashlib
from pathlib import Path


def save_raw(raw_dir: Path, data: bytes, suffix: str) -> tuple[str, Path]:
    """Write data to raw_dir/{sha256}{suffix} and return (sha256, path)."""
    sha256 = hashlib.sha256(data).hexdigest()
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{sha256}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return sha256, path


def read_raw(path: Path) -> bytes:
    """Read the raw bytes of a stored file."""
    return path.read_bytes()
