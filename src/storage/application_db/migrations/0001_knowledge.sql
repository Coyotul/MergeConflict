-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Text search configuration for Romanian with unaccent
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'romanian') THEN
        -- Romanian stemmer is available
        CREATE TEXT SEARCH CONFIGURATION ro_unaccent (COPY = romanian);
        ALTER TEXT SEARCH CONFIGURATION ro_unaccent
            ALTER MAPPING FOR hword, hword_part, word
            WITH unaccent, romanian_stem;
    ELSE
        -- Fall back to simple stemmer
        CREATE TEXT SEARCH CONFIGURATION ro_unaccent (COPY = simple);
        ALTER TEXT SEARCH CONFIGURATION ro_unaccent
            ALTER MAPPING FOR hword, hword_part, word
            WITH unaccent, simple;
    END IF;
END$$;

-- Knowledge documents table
CREATE TABLE knowledge_documents (
    id bigserial PRIMARY KEY,
    canonical_key text UNIQUE NOT NULL,
    source_url text NOT NULL,
    title text NOT NULL,
    doc_kind text NOT NULL,
    publisher text NOT NULL DEFAULT 'Raiffeisen Bank Romania',
    language text NOT NULL DEFAULT 'ro',
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'withdrawn')),
    last_seen_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- Knowledge document versions table
CREATE TABLE knowledge_document_versions (
    id bigserial PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES knowledge_documents ON DELETE CASCADE,
    content_hash text NOT NULL,
    version_label text,
    effective_from date NOT NULL,
    effective_date_source text NOT NULL CHECK (effective_date_source IN ('document_text', 'filename', 'sitemap_lastmod', 'fetched_at')),
    fetched_at timestamptz NOT NULL,
    sitemap_lastmod date,
    raw_path text NOT NULL,
    campaign_valid_until date,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    parser_name text NOT NULL,
    parser_version text NOT NULL,
    UNIQUE (document_id, content_hash)
);

-- Knowledge chunks table
CREATE TABLE knowledge_chunks (
    id bigserial PRIMARY KEY,
    version_id bigint NOT NULL REFERENCES knowledge_document_versions ON DELETE CASCADE,
    ordinal int NOT NULL,
    kind text NOT NULL,
    topic text NOT NULL,
    products text[] NOT NULL,
    authority text NOT NULL,
    section_path text[] NOT NULL,
    page int,
    anchor text,
    header text NOT NULL,
    text text NOT NULL,
    token_count int NOT NULL,
    prev_chunk_id bigint,
    next_chunk_id bigint,
    parent_section_key text,
    embedding vector(1024) NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('ro_unaccent', header || ' ' || text)) STORED
);

-- Indexes for knowledge_chunks
CREATE INDEX idx_knowledge_chunks_embedding ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_knowledge_chunks_tsv ON knowledge_chunks USING gin (tsv);
CREATE INDEX idx_knowledge_chunks_products ON knowledge_chunks USING gin (products);
CREATE INDEX idx_knowledge_chunks_topic ON knowledge_chunks (topic);
CREATE INDEX idx_knowledge_chunks_version_id ON knowledge_chunks (version_id);

-- Knowledge chunk links table
CREATE TABLE knowledge_chunk_links (
    chunk_id bigint NOT NULL REFERENCES knowledge_chunks ON DELETE CASCADE,
    target_canonical_key text NOT NULL,
    anchor_text text NOT NULL,
    link_kind text NOT NULL CHECK (link_kind IN ('card', 'teaser', 'inline')),
    ordinal int NOT NULL,
    PRIMARY KEY (chunk_id, target_canonical_key)
);

CREATE INDEX idx_knowledge_chunk_links_target ON knowledge_chunk_links (target_canonical_key);

-- Index runs table
CREATE TABLE index_runs (
    id bigserial PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    embedding_model text NOT NULL,
    chunker_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    documents_seen int DEFAULT 0,
    versions_created int DEFAULT 0,
    failures int DEFAULT 0
);
