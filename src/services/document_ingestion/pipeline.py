"""Versioned ingestion: raw file -> parsed chunks -> document, version, chunks and links in Postgres."""
import hashlib
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pgvector.psycopg import register_vector
from psycopg import Connection
from pydantic import BaseModel

from src.core.errors import IngestionError
from src.models.knowledge import AUTHORITY_BY_DOC_KIND, DocKind, Product
from src.services.document_ingestion.chunking import CHUNKER_VERSION, ChunkDraft, build_header, estimate_tokens
from src.services.document_ingestion.manifest import ManifestEntry
from src.services.document_ingestion.metadata import (
    canonical_key,
    extract_campaign_window,
    extract_effective_date,
    shared_dated_folders,
)
from src.services.document_ingestion.parsers import parse_document
from src.services.document_ingestion.sources import (
    SourceConfig,
    classify_document,
    classify_topic,
    fee_section_products,
)
from src.storage.document_store.raw_store import read_raw
from src.storage.document_store.repository import DocumentRepository, NewVersion
from src.storage.vector_index.repository import ChunkLinkRecord, ChunkRecord, insert_chunk_links, insert_chunks

if TYPE_CHECKING:
    from src.integrations.llm.embeddings import Embedder

KNOWLEDGE_TABLES = "knowledge_chunk_links, knowledge_chunks, knowledge_document_versions, knowledge_documents"


class IngestOutcome(StrEnum):
    """What happened to one manifest entry."""
    created = "created"
    unchanged = "unchanged"
    failed = "failed"
    withdrawn = "withdrawn"
    skipped = "skipped"


class IngestReport(BaseModel):
    """Result of one ingestion run, keyed by entry URL."""
    run_id: int
    outcomes: dict[str, IngestOutcome]
    errors: dict[str, str]
    warnings: dict[str, list[str]]


class IngestionPipeline:
    """Parses fetched documents and stores new versions with embedded chunks.

    Each document is written in its own transaction, so a failure leaves the
    previous version in force.
    """

    def __init__(self, conn: Connection, embedder: "Embedder", cfg: SourceConfig):
        register_vector(conn)
        self.conn = conn
        self.embedder = embedder
        self.cfg = cfg
        self.documents = DocumentRepository(conn)

    def ingest_entries(self, entries: list[ManifestEntry], raw_dir: Path) -> IngestReport:
        """Ingest every manifest entry and record the run in index_runs."""
        shared = shared_dated_folders([e.final_url for e in entries])
        with self.conn.transaction():
            run_id = self.conn.execute(
                "INSERT INTO index_runs (embedding_model, chunker_version, status) VALUES (%s, %s, 'running') RETURNING id",
                (self.embedder.model_name, CHUNKER_VERSION),
            ).fetchone()[0]

        outcomes: dict[str, IngestOutcome] = {}
        errors: dict[str, str] = {}
        warnings: dict[str, list[str]] = {}
        try:
            for entry in entries:
                outcome, messages = self._ingest_entry(entry, raw_dir, shared)
                outcomes[entry.url] = outcome
                if outcome is IngestOutcome.failed:
                    errors[entry.url] = "; ".join(messages)
                elif messages:
                    warnings[entry.url] = messages
        except BaseException:
            self._finish_run(run_id, "failed", outcomes)
            raise
        self._finish_run(run_id, "completed", outcomes)
        return IngestReport(run_id=run_id, outcomes=outcomes, errors=errors, warnings=warnings)

    def rebuild(self, entries: list[ManifestEntry], raw_dir: Path) -> IngestReport:
        """Empty the knowledge tables, then ingest everything again (used when the chunker changes)."""
        with self.conn.transaction():
            self.conn.execute(f"TRUNCATE {KNOWLEDGE_TABLES} RESTART IDENTITY")
        return self.ingest_entries(entries, raw_dir)

    def ingest_one(
        self, entry: ManifestEntry, data: bytes, shared_folders: frozenset[str] = frozenset()
    ) -> tuple[IngestOutcome, list[str]]:
        """Parse one document and store it as a new version unless its content is already stored.

        Returns the outcome and messages: the error for `failed`, parser warnings otherwise.
        """
        try:
            if entry.raw_path is None:
                raise IngestionError(f"{entry.url}: entry has no raw_path")
            doc_kind, doc_products = classify_document(entry.final_url, self.cfg)
            parsed = parse_document(doc_kind, data, entry.final_url, self.cfg)
            if not parsed.chunks:
                return IngestOutcome.failed, [f"{entry.final_url}: no extractable content"]

            effective_from, date_source = extract_effective_date(
                doc_kind, parsed.metadata_text, entry.final_url, entry.sitemap_lastmod, entry.fetched_at
            )
            version = NewVersion(
                content_hash=hashlib.sha256(data).hexdigest(),
                version_label=f"{effective_from.isoformat()} ({date_source})",
                effective_from=effective_from,
                effective_date_source=date_source,
                fetched_at=entry.fetched_at,
                sitemap_lastmod=entry.sitemap_lastmod,
                raw_path=entry.raw_path,
                campaign_valid_until=extract_campaign_window(parsed.metadata_text, effective_from),
                parser_name=parsed.parser_name,
                parser_version=parsed.parser_version,
            )

            with self.conn.transaction():
                document_id = self.documents.upsert_document(
                    canonical_key(entry.final_url, shared_folders), entry.final_url, parsed.title, str(doc_kind)
                )
                if self.documents.find_version_by_hash(document_id, version.content_hash) is not None:
                    return IngestOutcome.unchanged, parsed.warnings
                version_id = self.documents.create_version(document_id, version)

                authority = AUTHORITY_BY_DOC_KIND[doc_kind]
                headers = [build_header(parsed.title, c.section_path, effective_from) for c in parsed.chunks]
                embeddings = self.embedder.embed_documents(
                    [h + "\n" + c.text for h, c in zip(headers, parsed.chunks)]
                )
                records = [
                    ChunkRecord(
                        ordinal=i,
                        kind=str(chunk.kind),
                        topic=str(classify_topic(doc_kind, chunk.kind, chunk.section_path, chunk.text, self.cfg)),
                        products=[str(p) for p in self._chunk_products(doc_kind, chunk, doc_products)],
                        authority=str(authority),
                        section_path=chunk.section_path,
                        page=chunk.page,
                        anchor=chunk.anchor,
                        header=header,
                        text=chunk.text,
                        token_count=estimate_tokens(chunk.text),
                        parent_section_key=" › ".join(chunk.section_path[:2]),
                        embedding=embedding,
                    )
                    for i, (chunk, header, embedding) in enumerate(zip(parsed.chunks, headers, embeddings))
                ]
                chunk_ids = insert_chunks(self.conn, version_id, records)
                for chunk_id, chunk in zip(chunk_ids, parsed.chunks):
                    insert_chunk_links(self.conn, chunk_id, [
                        ChunkLinkRecord(
                            target_canonical_key=canonical_key(link.target_url, shared_folders),
                            anchor_text=link.anchor_text,
                            link_kind=link.link_kind,
                            ordinal=ordinal,
                        )
                        for ordinal, link in enumerate(chunk.links)
                    ])
            return IngestOutcome.created, parsed.warnings
        except Exception as exc:
            return IngestOutcome.failed, [str(exc)]

    def _ingest_entry(
        self, entry: ManifestEntry, raw_dir: Path, shared: frozenset[str]
    ) -> tuple[IngestOutcome, list[str]]:
        if entry.withdrawn:
            with self.conn.transaction():
                self.documents.mark_withdrawn([canonical_key(entry.url, shared)])
            return IngestOutcome.withdrawn, []
        if not entry.index or entry.raw_path is None or entry.status_code != 200:
            return IngestOutcome.skipped, []
        raw_file = Path(entry.raw_path)
        if not raw_file.is_absolute():
            raw_file = raw_dir / raw_file
        try:
            data = read_raw(raw_file)
        except OSError as exc:
            return IngestOutcome.failed, [f"{entry.url}: cannot read raw file: {exc}"]
        return self.ingest_one(entry, data, shared)

    def _chunk_products(self, doc_kind: DocKind, chunk: ChunkDraft, doc_products: list[Product]) -> list[Product]:
        if chunk.products_override is not None:
            return chunk.products_override
        if doc_kind is DocKind.fee_list:
            section_products = fee_section_products(chunk.section_path, self.cfg)
            if section_products is not None:
                return section_products
        return doc_products

    def _finish_run(self, run_id: int, status: str, outcomes: dict[str, IngestOutcome]) -> None:
        counts = list(outcomes.values())
        with self.conn.transaction():
            self.conn.execute(
                """
                UPDATE index_runs SET status = %s, finished_at = now(), documents_seen = %s,
                    versions_created = %s, failures = %s
                WHERE id = %s
                """,
                (status, len(counts), counts.count(IngestOutcome.created),
                 counts.count(IngestOutcome.failed), run_id),
            )
