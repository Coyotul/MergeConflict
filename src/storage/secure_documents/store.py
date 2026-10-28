"""Secure Document Storage adapter.

Provides access-controlled, tamper-evident file storage for applicant documents,
with SHA-256 hashing, path traversal defenses and metadata indexing.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional
import uuid


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_STORAGE_ROOT = ROOT_DIR / "data" / "local" / "secure_documents"

ALLOWED_MIME_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/jpg"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit


class SecureDocumentStore:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = (root_dir or DEFAULT_STORAGE_ROOT).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.root_dir / "document_registry.json"
        self._registry: Dict[str, dict] = self._load_registry()

    def _load_registry(self) -> Dict[str, dict]:
        if not self.metadata_file.exists():
            return {}
        try:
            return json.loads(self.metadata_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_registry(self) -> None:
        self.metadata_file.write_text(json.dumps(self._registry, indent=2), encoding="utf-8")

    def store_document(
        self,
        customer_id: str,
        filename: str,
        content_bytes: bytes,
        mime_type: str,
        doc_kind: str,
        application_id: Optional[str] = None,
    ) -> dict:
        """Store applicant document bytes securely with integrity hashing."""
        if len(content_bytes) > MAX_FILE_SIZE_BYTES:
            raise ValueError(f"File size exceeds maximum allowed ({len(content_bytes)} > {MAX_FILE_SIZE_BYTES} bytes).")

        normalized_mime = mime_type.lower().strip()
        if normalized_mime not in ALLOWED_MIME_TYPES:
            raise ValueError(f"Unsupported MIME type '{mime_type}'. Allowed types: {list(ALLOWED_MIME_TYPES)}")

        # Calculate SHA-256 hash
        sha256 = hashlib.sha256(content_bytes).hexdigest()

        # Sanitize customer folder
        safe_customer = "".join(c for c in customer_id if c.isalnum() or c in ("-", "_"))
        cust_dir = self.root_dir / safe_customer
        cust_dir.mkdir(parents=True, exist_ok=True)

        # Unique storage file name (prevents collision and path traversal)
        doc_id = f"doc_{uuid.uuid4().hex[:16]}"
        suffix = Path(filename).suffix.lower() or (".pdf" if normalized_mime == "application/pdf" else ".bin")
        stored_filename = f"{doc_id}{suffix}"
        target_path = cust_dir / stored_filename

        target_path.write_bytes(content_bytes)

        record = {
            "document_id": doc_id,
            "customer_id": safe_customer,
            "application_id": application_id,
            "kind": doc_kind,
            "original_filename": filename,
            "mime_type": normalized_mime,
            "size_bytes": len(content_bytes),
            "sha256_hash": sha256,
            "stored_path": str(target_path.relative_to(self.root_dir)),
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

        self._registry[doc_id] = record
        self._save_registry()
        return record

    def get_document_bytes(self, document_id: str, customer_id: Optional[str] = None) -> Tuple_Bytes_Meta:
        """Retrieve stored document bytes and verify its SHA-256 integrity."""
        record = self._registry.get(document_id)
        if not record:
            raise FileNotFoundError(f"Document with ID '{document_id}' not found.")

        if customer_id and record["customer_id"] != customer_id:
            raise PermissionError(f"Access denied: Document does not belong to customer '{customer_id}'.")

        file_path = self.root_dir / record["stored_path"]
        if not file_path.exists():
            raise FileNotFoundError(f"Stored file '{file_path}' is missing on disk.")

        data = file_path.read_bytes()

        # Check integrity
        current_hash = hashlib.sha256(data).hexdigest()
        if current_hash != record["sha256_hash"]:
            raise ValueError(f"Tamper detected: SHA-256 mismatch for document {document_id}!")

        return data, record

    def verify_integrity(self, document_id: str) -> bool:
        """Verify whether the physical file on disk matches its recorded cryptographic hash."""
        record = self._registry.get(document_id)
        if not record:
            return False
        file_path = self.root_dir / record["stored_path"]
        if not file_path.exists():
            return False
        return hashlib.sha256(file_path.read_bytes()).hexdigest() == record["sha256_hash"]

    def list_customer_documents(self, customer_id: str) -> List[dict]:
        safe_customer = "".join(c for c in customer_id if c.isalnum() or c in ("-", "_"))
        return [doc for doc in self._registry.values() if doc["customer_id"] == safe_customer]


Tuple_Bytes_Meta = tuple[bytes, dict]
