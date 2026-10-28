"""Writes chunks (with embeddings) and their outgoing links, and runs the retrieval queries.

The connection must have the pgvector adapter registered
(pgvector.psycopg.register_vector).
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pgvector import Vector
from psycopg import Connection

from src.models.knowledge import (
    Authority,
    ChunkKind,
    DocKind,
    IndexInfo,
    LinkKind,
    Product,
    RelatedLink,
    Topic,
)


@dataclass
class ChunkRecord:
    """A chunk ready to store."""
    ordinal: int
    kind: str
    topic: str
    products: list[str]
    authority: str
    section_path: list[str]
    page: int | None
    anchor: str | None
    header: str
    text: str
    token_count: int
    parent_section_key: str | None
    embedding: list[float]


@dataclass
class ChunkLinkRecord:
    """A link from a chunk to another document."""
    target_canonical_key: str
    anchor_text: str
    link_kind: LinkKind
    ordinal: int


def insert_chunks(conn: Connection, version_id: int, records: list[ChunkRecord]) -> list[int]:
    """Insert chunks in ordinal order, then link neighbours; returns ids in ordinal order."""
    ids: list[int] = []
    for r in sorted(records, key=lambda rec: rec.ordinal):
        row = conn.execute(
            """
            INSERT INTO knowledge_chunks (
                version_id, ordinal, kind, topic, products, authority, section_path, page, anchor,
                header, text, token_count, parent_section_key, embedding
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                version_id, r.ordinal, r.kind, r.topic, r.products, r.authority, r.section_path,
                r.page, r.anchor, r.header, r.text, r.token_count, r.parent_section_key,
                Vector(r.embedding),
            ),
        ).fetchone()
        ids.append(row[0])

    for i, chunk_id in enumerate(ids):
        prev_id = ids[i - 1] if i > 0 else None
        next_id = ids[i + 1] if i + 1 < len(ids) else None
        conn.execute(
            "UPDATE knowledge_chunks SET prev_chunk_id = %s, next_chunk_id = %s WHERE id = %s",
            (prev_id, next_id, chunk_id),
        )
    return ids


def insert_chunk_links(conn: Connection, chunk_id: int, links: list[ChunkLinkRecord]) -> None:
    """Store a chunk's links; a repeated target for the same chunk is kept once."""
    for link in links:
        conn.execute(
            """
            INSERT INTO knowledge_chunk_links (chunk_id, target_canonical_key, anchor_text, link_kind, ordinal)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (chunk_id, target_canonical_key) DO NOTHING
            """,
            (chunk_id, link.target_canonical_key, link.anchor_text, str(link.link_kind), link.ordinal),
        )


# Per document, the version in force on %(as_of)s: the greatest (effective_from, ingested_at)
# among versions that are already effective.
IN_FORCE_CTE = """
in_force AS (
    SELECT DISTINCT ON (v.document_id) v.id
    FROM knowledge_document_versions v
    WHERE v.effective_from <= %(as_of)s
    ORDER BY v.document_id, v.effective_from DESC, v.ingested_at DESC
)
"""

CHUNK_JOINS = """
    FROM knowledge_chunks c
    JOIN knowledge_document_versions v ON v.id = c.version_id
    JOIN knowledge_documents d ON d.id = v.document_id
"""


@dataclass
class CandidateFilters:
    """Which chunks a search may return."""
    as_of: date
    topics: list[Topic]
    products: list[Product] | None
    doc_kinds: list[DocKind] | None
    include_superseded: bool
    include_withdrawn: bool


@dataclass
class Candidate:
    """A chunk found by one retriever, with that retriever's score."""
    chunk_id: int
    score: float


@dataclass
class PassageRow:
    """Everything needed to build a Passage and its Citation for one chunk."""
    chunk_id: int
    document_id: int
    doc_kind: DocKind
    kind: ChunkKind
    topic: Topic
    products: list[Product]
    authority: Authority
    header: str
    text: str
    publisher: str
    title: str
    url: str
    canonical_key: str
    page: int | None
    anchor: str | None
    section_path: list[str]
    version_label: str | None
    effective_date: date
    fetched_at: datetime
    campaign_valid_until: date | None
    in_force: bool
    withdrawn: bool


def _filter_clauses(f: CandidateFilters) -> tuple[list[str], dict[str, Any]]:
    """WHERE clauses (aliases c = chunk, v = version, d = document) and parameters for the filters."""
    where = ["v.effective_from <= %(as_of)s", "c.topic = ANY(%(topics)s)"]
    params: dict[str, Any] = {"as_of": f.as_of, "topics": [str(t) for t in f.topics]}
    if not f.include_superseded:
        where.append("v.id IN (SELECT id FROM in_force)")
    if not f.include_withdrawn:
        where.append("d.status = 'active'")
    if f.products is not None:
        where.append("c.products && %(products)s")
        params["products"] = [str(p) for p in f.products]
    if f.doc_kinds is not None:
        where.append("d.doc_kind = ANY(%(doc_kinds)s)")
        params["doc_kinds"] = [str(k) for k in f.doc_kinds]
    return where, params


def dense_candidates(conn: Connection, embedding: list[float], f: CandidateFilters, limit: int) -> list[Candidate]:
    """Nearest chunks by cosine similarity (score = 1 - cosine distance), best first."""
    where, params = _filter_clauses(f)
    params.update(q=Vector(embedding), limit=limit)
    rows = conn.execute(
        f"WITH {IN_FORCE_CTE} SELECT c.id, 1 - (c.embedding <=> %(q)s) {CHUNK_JOINS} "
        f"WHERE {' AND '.join(where)} ORDER BY c.embedding <=> %(q)s, c.id LIMIT %(limit)s",
        params,
    ).fetchall()
    return [Candidate(chunk_id=r[0], score=float(r[1])) for r in rows]


def keyword_candidates(conn: Connection, terms: list[str], f: CandidateFilters, limit: int) -> list[Candidate]:
    """Chunks matching any term in full-text search, scored by ts_rank_cd, best first.

    The terms are OR-ed into a tsquery passed as a bound parameter; callers pass plain
    word tokens (see ranking.query_terms), so no tsquery operator reaches the parser.
    """
    if not terms:
        return []
    where, params = _filter_clauses(f)
    params.update(tsq=" | ".join(terms), limit=limit)
    rows = conn.execute(
        f"WITH {IN_FORCE_CTE}, query AS (SELECT to_tsquery('ro_unaccent', %(tsq)s) AS q) "
        f"SELECT c.id, ts_rank_cd(c.tsv, query.q, 32) AS score {CHUNK_JOINS} CROSS JOIN query "
        f"WHERE c.tsv @@ query.q AND {' AND '.join(where)} ORDER BY score DESC, c.id LIMIT %(limit)s",
        params,
    ).fetchall()
    return [Candidate(chunk_id=r[0], score=float(r[1])) for r in rows]


def dense_scores_for(conn: Connection, embedding: list[float], chunk_ids: list[int]) -> dict[int, float]:
    """Cosine similarity of the given chunks to the query embedding."""
    if not chunk_ids:
        return {}
    rows = conn.execute(
        "SELECT id, 1 - (embedding <=> %s) FROM knowledge_chunks WHERE id = ANY(%s)",
        (Vector(embedding), chunk_ids),
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def fetch_passage_rows(conn: Connection, chunk_ids: list[int], as_of: date) -> dict[int, PassageRow]:
    """Passage and citation fields for the given chunks; `in_force` is relative to as_of."""
    if not chunk_ids:
        return {}
    rows = conn.execute(
        f"""
        WITH {IN_FORCE_CTE}
        SELECT c.id, d.id, d.doc_kind, c.kind, c.topic, c.products, c.authority, c.header, c.text,
               d.publisher, d.title, d.source_url, d.canonical_key, c.page, c.anchor, c.section_path,
               v.version_label, v.effective_from, v.fetched_at, v.campaign_valid_until,
               v.id IN (SELECT id FROM in_force), d.status = 'withdrawn'
        {CHUNK_JOINS}
        WHERE c.id = ANY(%(ids)s)
        """,
        {"as_of": as_of, "ids": chunk_ids},
    ).fetchall()
    return {
        r[0]: PassageRow(
            chunk_id=r[0], document_id=r[1], doc_kind=DocKind(r[2]), kind=ChunkKind(r[3]), topic=Topic(r[4]),
            products=[Product(p) for p in r[5]], authority=Authority(r[6]), header=r[7], text=r[8],
            publisher=r[9], title=r[10], url=r[11], canonical_key=r[12], page=r[13], anchor=r[14],
            section_path=list(r[15]), version_label=r[16], effective_date=r[17], fetched_at=r[18],
            campaign_valid_until=r[19], in_force=r[20], withdrawn=r[21],
        )
        for r in rows
    }


def fetch_neighbor_texts(conn: Connection, chunk_ids: list[int]) -> dict[int, tuple[str | None, str | None]]:
    """The (previous, next) chunk texts of each given chunk; None at a document edge."""
    if not chunk_ids:
        return {}
    rows = conn.execute(
        """
        SELECT c.id, p.text, n.text
        FROM knowledge_chunks c
        LEFT JOIN knowledge_chunks p ON p.id = c.prev_chunk_id
        LEFT JOIN knowledge_chunks n ON n.id = c.next_chunk_id
        WHERE c.id = ANY(%s)
        """,
        (chunk_ids,),
    ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def latest_index_info(conn: Connection) -> IndexInfo | None:
    """Embedding model and chunker of the most recent completed index run, if any."""
    row = conn.execute(
        """
        SELECT embedding_model, chunker_version, finished_at FROM index_runs
        WHERE status = 'completed' AND finished_at IS NOT NULL
        ORDER BY finished_at DESC, id DESC LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return IndexInfo(embedding_model=row[0], chunker_version=row[1], last_ingest_at=row[2])


def fetch_related_links(conn: Connection, chunk_ids: list[int], as_of: date) -> dict[int, list[RelatedLink]]:
    """Read-more links per chunk, keeping only targets that are indexed, active and effective on as_of."""
    if not chunk_ids:
        return {}
    rows = conn.execute(
        """
        SELECT l.chunk_id, COALESCE(NULLIF(btrim(d.title), ''), l.anchor_text), d.source_url,
               l.target_canonical_key, l.link_kind
        FROM knowledge_chunk_links l
        JOIN knowledge_documents d ON d.canonical_key = l.target_canonical_key
        WHERE l.chunk_id = ANY(%(ids)s)
          AND d.status = 'active'
          AND EXISTS (SELECT 1 FROM knowledge_document_versions v
                      WHERE v.document_id = d.id AND v.effective_from <= %(as_of)s)
        ORDER BY l.chunk_id, l.ordinal
        """,
        {"ids": chunk_ids, "as_of": as_of},
    ).fetchall()
    links: dict[int, list[RelatedLink]] = {}
    for chunk_id, title, url, key, kind in rows:
        links.setdefault(chunk_id, []).append(
            RelatedLink(title=title, url=url, canonical_key=key, link_kind=LinkKind(kind))
        )
    return links
