"""Writes chunks (with embeddings) and their outgoing links.

The connection must have the pgvector adapter registered
(pgvector.psycopg.register_vector).
"""
from dataclasses import dataclass

from pgvector import Vector
from psycopg import Connection

from src.models.knowledge import LinkKind


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
