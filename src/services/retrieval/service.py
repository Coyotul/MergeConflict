"""Hybrid retrieval: dense + keyword candidates, fused and filtered into cited, flagged passages."""
from collections.abc import Callable
from typing import TYPE_CHECKING

import psycopg
from pgvector.psycopg import register_vector

from src.core.errors import EmbeddingModelUnavailable, KnowledgeStoreUnavailable
from src.core.settings import RagSettings
from src.models.knowledge import (
    Citation,
    Passage,
    PassageContext,
    Scores,
    SearchQuery,
    SearchResult,
    SearchStatus,
)
from src.services.retrieval.ranking import (
    apply_authority,
    apply_hub_deferral,
    dedupe_passages,
    detect_conflicts,
    passage_flags,
    passes_evidence_threshold,
    query_terms,
    rrf_fuse,
)
from src.storage.vector_index.repository import (
    CandidateFilters,
    PassageRow,
    dense_candidates,
    dense_scores_for,
    fetch_neighbor_texts,
    fetch_passage_rows,
    fetch_related_links,
    keyword_candidates,
    latest_index_info,
)

if TYPE_CHECKING:
    from src.integrations.llm.embeddings import Embedder


class RetrievalService:
    """Searches the knowledge index. Each search opens its own read-only connection and closes it."""

    def __init__(self, connect: Callable[[], psycopg.Connection], embedder: "Embedder", settings: RagSettings):
        self.connect = connect
        self.embedder = embedder
        self.settings = settings

    def search(self, query: SearchQuery) -> SearchResult:
        """Run a hybrid search; raises EmbeddingModelUnavailable or KnowledgeStoreUnavailable on failure.

        KnowledgeStoreUnavailable also covers an index with no completed ingest run.
        """
        try:
            embedding = self.embedder.embed_query(query.text)
        except EmbeddingModelUnavailable:
            raise
        except Exception as exc:
            raise EmbeddingModelUnavailable(f"query embedding failed: {exc}") from exc

        try:
            conn = self.connect()
        except psycopg.Error as exc:
            raise KnowledgeStoreUnavailable(f"knowledge store unreachable: {exc}") from exc
        try:
            conn.read_only = True
            register_vector(conn)
            return self._search(conn, query, embedding)
        except psycopg.errors.SyntaxError:
            # Every query is parameterized and keyword terms are plain word tokens, so a syntax
            # error is a bug in this module, not a store problem.
            raise
        except psycopg.Error as exc:
            # Unreachable or dropped connections, missing tables or extensions (an unmigrated or
            # wrong database), permissions: the store cannot serve the search.
            raise KnowledgeStoreUnavailable(f"knowledge store query failed: {exc}") from exc
        finally:
            conn.close()

    def _search(self, conn: psycopg.Connection, query: SearchQuery, embedding: list[float]) -> SearchResult:
        s = self.settings
        filters = CandidateFilters(
            as_of=query.as_of,
            topics=sorted(query.effective_topics),
            products=query.products,
            doc_kinds=query.doc_kinds,
            include_superseded=query.include_superseded,
            include_withdrawn=query.include_withdrawn,
        )
        index_info = latest_index_info(conn)
        if index_info is None:
            # Without a completed ingest run, "no evidence" would be a false answer.
            raise KnowledgeStoreUnavailable("knowledge index is empty: run scripts/rag/ingest.py")
        dense = dense_candidates(conn, embedding, filters, s.candidate_k)
        keyword = keyword_candidates(conn, query_terms(query.text), filters, s.candidate_k)

        dense_scores = {c.chunk_id: c.score for c in dense}
        keyword_scores = {c.chunk_id: c.score for c in keyword}
        dense_scores.update(dense_scores_for(conn, embedding, [c.chunk_id for c in keyword if c.chunk_id not in dense_scores]))
        if not passes_evidence_threshold([c.score for c in dense], s):
            return SearchResult(status=SearchStatus.insufficient_evidence, index_info=index_info)

        # Authority weighting needs every candidate's row, so rows are fetched for all fused candidates
        # (at most 2 * candidate_k), then the top 3 * top_k are turned into passages.
        fused = rrf_fuse(dense, keyword, s.rrf_k, s.keyword_weight)
        rows = fetch_passage_rows(conn, list(fused), query.as_of)
        fused = {cid: score for cid, score in fused.items() if cid in rows}
        weighted = apply_authority(fused, {cid: rows[cid].authority for cid in fused}, s.authority_weights)
        ranked = sorted(weighted, key=lambda cid: (-weighted[cid], cid))[: 3 * query.top_k]

        passages = dedupe_passages([
            _passage(rows[cid], Scores(dense=dense_scores.get(cid), keyword=keyword_scores.get(cid), fused=weighted[cid]))
            for cid in ranked
        ])[: query.top_k]
        for p in passages:
            p.flags, p.warnings = passage_flags(rows[p.chunk_id], query.as_of)
        apply_hub_deferral(passages)
        conflicts = detect_conflicts(passages)

        ids = [p.chunk_id for p in passages]
        if query.expand_context:
            neighbours = fetch_neighbor_texts(conn, ids)
            for p in passages:
                previous, following = neighbours.get(p.chunk_id, (None, None))
                p.context = PassageContext(previous=previous, next=following)
        links = fetch_related_links(conn, ids, query.as_of)
        for p in passages:
            p.related_links = links.get(p.chunk_id, [])

        return SearchResult(status=SearchStatus.ok, passages=passages, conflicts=conflicts, index_info=index_info)


def _passage(row: PassageRow, scores: Scores) -> Passage:
    return Passage(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        doc_kind=row.doc_kind,
        kind=row.kind,
        topic=row.topic,
        products=row.products,
        authority=row.authority,
        header=row.header,
        text=row.text,
        citation=Citation(
            publisher=row.publisher,
            title=row.title,
            url=row.url,
            canonical_key=row.canonical_key,
            page=row.page,
            anchor=row.anchor,
            section_path=row.section_path,
            version_label=row.version_label,
            effective_date=row.effective_date,
            fetched_at=row.fetched_at,
            campaign_valid_until=row.campaign_valid_until,
        ),
        scores=scores,
    )
