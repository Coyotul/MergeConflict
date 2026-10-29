"""Secure Document Storage adapter.

Provides access-controlled, tamper-evident file storage for applicant documents,
with SHA-256 hashing, path traversal defenses and metadata indexing.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Dict, List, Optional
import uuid

from src.storage.secure_documents.local import sanitize_filename
from src.storage.secure_documents.validation import MIME_SUFFIXES, validate_document_bytes


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_STORAGE_ROOT = ROOT_DIR / "data" / "local" / "secure_documents"

ALLOWED_MIME_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/jpg"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_ROOT_LOCKS: dict[Path, threading.RLock] = {}
_ROOT_LOCKS_GUARD = threading.Lock()


class SecureDocumentStore:
    def __init__(self, root_dir: Optional[Path] = None, *, max_file_size_bytes: int = MAX_FILE_SIZE_BYTES):
        if max_file_size_bytes <= 0:
            raise ValueError("The upload size limit must be positive.")
        self.root_dir = Path(root_dir or DEFAULT_STORAGE_ROOT).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_size_bytes = max_file_size_bytes
        self.metadata_file = self.root_dir / "document_registry.json"
        with _ROOT_LOCKS_GUARD:
            self._lock = _ROOT_LOCKS.setdefault(self.root_dir, threading.RLock())
        self._registry: Dict[str, dict] = self._load_registry()

    def _load_registry(self) -> Dict[str, dict]:
        self._safe_path("document_registry.json")
        if not self.metadata_file.exists():
            return {}
        try:
            registry = json.loads(self.metadata_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("The document registry is corrupt; access is blocked.") from exc
        if not isinstance(registry, dict) or any(
            not isinstance(record, dict) or record.get("document_id") != doc_id
            for doc_id, record in registry.items()
        ):
            raise ValueError("The document registry has invalid records; access is blocked.")
        return registry

    def _save_registry(self) -> None:
        self._safe_path("document_registry.json")
        temp = self.root_dir / f"registry-{uuid.uuid4().hex}.tmp"
        try:
            with temp.open("x", encoding="utf-8") as stream:
                json.dump(self._registry, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.metadata_file)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _validate_id(value: str, name: str) -> None:
        if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
            raise ValueError(f"Unsafe {name}; use 1-128 letters, digits, underscores or hyphens.")

    def _safe_path(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Document path escapes the storage root.")
        target = self.root_dir / relative
        for component in [target, *target.parents]:
            if component == self.root_dir:
                break
            if component.is_symlink() or (hasattr(component, "is_junction") and component.is_junction()):
                raise ValueError("Document path contains a symbolic link or junction.")
        if not target.resolve().is_relative_to(self.root_dir):
            raise ValueError("Document path escapes the storage root.")
        return target

    @contextmanager
    def _write_transaction(self):
        """Serialize threads, store instances and local worker processes; fail on stale locks."""
        with self._lock:
            lock_path = self._safe_path("document_registry.lock")
            deadline = time.monotonic() + 5.0
            while True:
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    break
                except FileExistsError:
                    if time.monotonic() >= deadline:
                        raise OSError("Document registry is locked; retry or inspect the local worker lock.")
                    time.sleep(0.01)
            try:
                self._registry = self._load_registry()
                yield
            finally:
                os.close(fd)
                lock_path.unlink(missing_ok=True)

    def _owned_record(self, document_id: str, customer_id: Optional[str], session_id: Optional[str]) -> dict:
        self._validate_id(document_id, "document_id")
        record = self._registry.get(document_id)
        if record is None:
            raise FileNotFoundError("The requested document was not found.")
        if customer_id is not None:
            self._validate_id(customer_id, "customer_id")
            if record.get("customer_id") != customer_id:
                raise PermissionError("Access denied: document belongs to another customer.")
        if session_id is not None:
            self._validate_id(session_id, "session_id")
            if record.get("session_id") != session_id:
                raise PermissionError("Access denied: document belongs to another session.")
        return record

    def store_document(
        self,
        customer_id: str,
        filename: str,
        content_bytes: bytes,
        mime_type: str,
        doc_kind: str,
        application_id: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> dict:
        """Store applicant document bytes securely with integrity hashing."""
        self._validate_id(customer_id, "customer_id")
        if session_id is not None:
            self._validate_id(session_id, "session_id")
        doc_id = document_id or f"doc_{uuid.uuid4().hex}"
        self._validate_id(doc_id, "document_id")
        normalized_mime = validate_document_bytes(content_bytes, mime_type, self.max_file_size_bytes)

        # Calculate SHA-256 hash
        sha256 = hashlib.sha256(content_bytes).hexdigest()

        # Hash the exact customer ID: Windows case-folding and reserved names cannot merge tenants.
        customer_folder = hashlib.sha256(customer_id.encode("utf-8")).hexdigest()
        relative = str(Path(customer_folder) / f"{doc_id}{MIME_SUFFIXES[normalized_mime]}")
        target_path = self._safe_path(relative)

        record = {
            "document_id": doc_id,
            "customer_id": customer_id,
            "session_id": session_id,
            "application_id": application_id,
            "kind": doc_kind,
            "original_filename": sanitize_filename(filename),
            "mime_type": normalized_mime,
            "size_bytes": len(content_bytes),
            "sha256_hash": sha256,
            "stored_path": str(target_path.relative_to(self.root_dir)),
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "processing_status": "UPLOADED",
            "processing_result": None,
        }

        with self._write_transaction():
            if doc_id in self._registry:
                raise ValueError("Document ID already exists; uploads cannot overwrite stored evidence.")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            self._safe_path(relative)
            created = False
            try:
                with target_path.open("xb") as stream:
                    created = True
                    stream.write(content_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._registry[doc_id] = record
                self._save_registry()
            except Exception:
                self._registry.pop(doc_id, None)
                if created:
                    target_path.unlink(missing_ok=True)
                raise
        return deepcopy(record)

    def get_document_bytes(
        self, document_id: str, customer_id: Optional[str] = None, *, session_id: Optional[str] = None
    ) -> Tuple_Bytes_Meta:
        """Retrieve stored document bytes and verify its SHA-256 integrity."""
        with self._lock:
            self._registry = self._load_registry()
            record = self._owned_record(document_id, customer_id, session_id)
            file_path = self._safe_path(record["stored_path"])
            with file_path.open("rb") as stream:
                data = stream.read(self.max_file_size_bytes + 1)
            if len(data) != record["size_bytes"] or hashlib.sha256(data).hexdigest() != record["sha256_hash"]:
                raise ValueError("Tamper detected: size or SHA-256 integrity mismatch.")
            return data, deepcopy(record)

    def verify_integrity(self, document_id: str) -> bool:
        """Verify whether the physical file on disk matches its recorded cryptographic hash."""
        try:
            self.get_document_bytes(document_id)
            return True
        except (OSError, ValueError, KeyError):
            return False

    def list_customer_documents(self, customer_id: str) -> List[dict]:
        self._validate_id(customer_id, "customer_id")
        with self._lock:
            self._registry = self._load_registry()
            return deepcopy([doc for doc in self._registry.values() if doc["customer_id"] == customer_id])

    def save_processing_result(
        self, document_id: str, result: dict, *, customer_id: str, session_id: Optional[str] = None
    ) -> None:
        """Persist deterministic extraction/validation separately from untrusted original bytes."""
        with self._write_transaction():
            record = self._owned_record(document_id, customer_id, session_id)
            if result.get("document_id") != document_id or result.get("sha256_hash") != record["sha256_hash"]:
                raise ValueError("Processing result does not match the stored document.")
            record["processing_result"] = deepcopy(result)
            record["processing_status"] = result["status"]
            self._save_registry()

    def delete_document(
        self, document_id: str, *, customer_id: str, session_id: Optional[str] = None
    ) -> None:
        """Remove an uncommitted upload; ownership checks apply to cleanup too."""
        with self._write_transaction():
            record = self._owned_record(document_id, customer_id, session_id)
            target = self._safe_path(record["stored_path"])
            del self._registry[document_id]
            self._save_registry()
            target.unlink(missing_ok=True)


Tuple_Bytes_Meta = tuple[bytes, dict]
