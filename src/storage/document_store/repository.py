"""Repository for knowledge documents and their versions."""
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from psycopg import Connection


@dataclass
class NewVersion:
    """A document version to insert."""
    content_hash: str
    version_label: str | None
    effective_from: date
    effective_date_source: str
    fetched_at: datetime
    sitemap_lastmod: date | None
    raw_path: str
    campaign_valid_until: date | None
    parser_name: str
    parser_version: str


class DocumentRepository:
    """Reads and writes knowledge_documents and knowledge_document_versions."""

    def __init__(self, conn: Connection):
        self.conn = conn

    def upsert_document(self, canonical_key: str, source_url: str, title: str, doc_kind: str) -> int:
        """Insert or update a document by canonical key; marks it active and seen now."""
        row = self.conn.execute(
            """
            INSERT INTO knowledge_documents (canonical_key, source_url, title, doc_kind, status, last_seen_at)
            VALUES (%s, %s, %s, %s, 'active', now())
            ON CONFLICT (canonical_key) DO UPDATE SET
                source_url = EXCLUDED.source_url,
                title = EXCLUDED.title,
                doc_kind = EXCLUDED.doc_kind,
                status = 'active',
                last_seen_at = now()
            RETURNING id
            """,
            (canonical_key, source_url, title, doc_kind),
        ).fetchone()
        return row[0]

    def find_version_by_hash(self, document_id: int, content_hash: str) -> int | None:
        """Return the id of the document's version with this content hash, if any."""
        row = self.conn.execute(
            "SELECT id FROM knowledge_document_versions WHERE document_id = %s AND content_hash = %s",
            (document_id, content_hash),
        ).fetchone()
        return row[0] if row else None

    def create_version(self, document_id: int, version: NewVersion) -> int:
        """Insert a new version of a document and return its id."""
        row = self.conn.execute(
            """
            INSERT INTO knowledge_document_versions (
                document_id, content_hash, version_label, effective_from, effective_date_source,
                fetched_at, sitemap_lastmod, raw_path, campaign_valid_until, parser_name, parser_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                document_id, version.content_hash, version.version_label, version.effective_from,
                version.effective_date_source, version.fetched_at, version.sitemap_lastmod,
                version.raw_path, version.campaign_valid_until, version.parser_name, version.parser_version,
            ),
        ).fetchone()
        return row[0]

    def mark_withdrawn(self, canonical_keys: Sequence[str]) -> int:
        """Mark documents withdrawn by canonical key; returns the number of rows updated."""
        cur = self.conn.execute(
            "UPDATE knowledge_documents SET status = 'withdrawn' WHERE canonical_key = ANY(%s)",
            (list(canonical_keys),),
        )
        return cur.rowcount
