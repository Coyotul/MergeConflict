# Local RAG Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrape Raiffeisen Bank Romania's public credit documentation and serve it through a local, retrieval-only search service. The service returns cited, version-aware passages for the future orchestrator.

**Architecture:**
- A polite scraper writes raw HTML/PDF plus a manifest into ignored `data/local/rag/`.
- An ingestion pipeline does the following:
  - parses each document kind with its own structure-aware chunker
  - normalizes Romanian text
  - derives metadata (canonical key, effective date, campaign window, products, topic)
  - embeds chunks locally with BGE-M3
  - stores everything in a local Docker PostgreSQL with pgvector and an unaccent/Romanian full-text configuration
  - parses category hub pages into one chunk per product card, keeping in-content links as "read more" pointers in `knowledge_chunk_links`
- `RetrievalService.search()` combines dense and keyword candidates as follows:
  - fuses them with RRF and weights them by authority
  - applies an evidence threshold
  - attaches citations, flags, hub-to-cost-sheet deferrals and conflict notices
  - resolves "read more" pointers at query time

**Tech Stack:** Python 3.11+, Pydantic v2, PostgreSQL 16 + pgvector (Docker), psycopg 3, sentence-transformers (BAAI/bge-m3), BeautifulSoup4, PyMuPDF, httpx, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-rag-retrieval-design.md`. Read it before starting any task; section numbers below (§n) refer to it.

## Global Constraints

- Python 3.11+ in `.venv`. Pydantic models at every module boundary (RULES.md).
- **Never commit Raiffeisen content.** Raw files, extracted text and the database stay in `data/local/` and the Docker volume. Test fixtures are **synthetic imitations**: invented product names such as "Credit Demo", invented numbers, no copied sentences.
- Every passage is attributed to `publisher = "Raiffeisen Bank Romania"`. Chunk headers start with `Raiffeisen Bank › `. No wording presents these products as the platform's own.
- No network calls during ingestion or retrieval. The embedding model is downloaded once and then used offline. Unit and integration tests never download a model; they use the fake embedder from Task 7.
- The Postgres port is bound to `127.0.0.1` only.
- Chunk target is 300–500 tokens, with `MAX_TOKENS = 500`. Token estimate is `max(1, len(text) // 4)`. Atomic units are never split: a FAQ pair, a worked example, a table row.
- Scraper limits:
  - ≤ 1 request / 2 s
  - 30 s timeout
  - 3 retries with exponential backoff
  - robots.txt obeyed
  - User-Agent `MergeConflict-RAG-Prototype/0.1 (local hackathon research)`
- Retrieved text is evidence, not instructions: `SearchResult.content_trust == "untrusted_evidence"`.
- Failures raise typed errors. They never come back as an empty `ok` result.
- Commits follow GIT_AGENT_PROTOCOL.md:
  - subject: `agent(rag): <action>`
  - body: `- Details:`, `- Status:` and `- Next:` lines
  - trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. **Unusable source file:** a scanned PDF with no text layer, or an HTML page with no main content. Ingestion reports `FAILED` with a reason and writes nothing; an older good version stays in force. Test: Task 8, `test_document_without_chunks_writes_nothing`.
2. **Hostile or odd query text:** whitespace only, longer than 1000 chars, or containing tsquery operators (`& | ! : * ( ) '`). Validation rejects the first two; the third searches normally with no SQL error. Tests: Task 2 `test_query_text_validation`, Task 9 `test_query_with_tsquery_operators_is_safe`.
3. **Database down or embedding model missing at search time:** a typed error (`KnowledgeStoreUnavailable` / `EmbeddingModelUnavailable`), never `status="ok"` with no passages. Test: Task 9, `test_search_raises_typed_errors`.
4. **Messy hrefs in page content:** `#`, `href=""`, `javascript:void(0)`, `tel:`/`mailto:`, relative paths, query strings or fragments, `http://` vs `https://`, or a missing `www`. Junk is ignored without crashing, and real targets normalize to one `canonical_key`, so the same page is never linked twice. Test: Task 4, `test_absolutize_odd_hrefs`.
5. **Crash mid-ingestion of a document** (e.g. the embedder raises): the transaction rolls back, no half-written version, and the previous version stays in force. Test: Task 8, `test_failed_ingest_rolls_back`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `requirements.txt` (modify) | Add runtime and test dependencies |
| `pytest.ini` | `pythonpath = .`, markers `integration` |
| `.env.example` | `RAG_DATABASE_URL`, `RAG_TEST_DATABASE_URL` |
| `infrastructure/local/docker-compose.yml` | pgvector Postgres 16, `127.0.0.1:5433`, named volume |
| `infrastructure/local/initdb/01-create-test-db.sql` | Creates `rag_test` database |
| `src/core/settings.py` | `RagSettings`, `load_rag_settings()` |
| `src/core/errors.py` | Typed RAG errors |
| `src/storage/application_db/migrations/0001_knowledge.sql` | Extensions, TS config, knowledge tables, `index_runs` |
| `src/storage/application_db/migrate.py` | Minimal SQL migration runner |
| `src/models/knowledge.py` | Shared enums and `SearchQuery` / `SearchResult` models |
| `src/services/document_ingestion/normalize.py` | Unicode/diacritic/whitespace normalization |
| `src/services/document_ingestion/sources.py` | `SourceConfig` (YAML) + document/topic classification |
| `src/services/document_ingestion/metadata.py` | Canonical key, effective date, campaign window |
| `src/services/document_ingestion/chunking.py` | `ChunkDraft`, `ParsedDocument`, token estimate, packing, header |
| `src/services/document_ingestion/parsers/__init__.py` | `parse_document()` dispatch |
| `src/services/document_ingestion/parsers/html_page.py` | Product page / guide / FAQ page / article; shared HTML cleanup and accordion helper |
| `src/services/document_ingestion/parsers/links.py` | In-content link extraction model and filtering (§9a) |
| `src/services/document_ingestion/parsers/category_hub.py` | Category hub pages: product cards, article-teaser block, FAQ |
| `src/services/document_ingestion/parsers/pdf_rows.py` | Word-coordinate row rebuilding |
| `src/services/document_ingestion/parsers/fee_list.py` | Fee list PDF |
| `src/services/document_ingestion/parsers/general_terms.py` | CGB PDF |
| `src/services/document_ingestion/parsers/cost_sheet.py` | Cost sheet template parser |
| `src/services/document_ingestion/parsers/pdf_generic.py` | Other PDFs |
| `src/services/document_ingestion/manifest.py` | `ManifestEntry`, read/write |
| `src/services/document_ingestion/scraper.py` | Discovery, polite fetching, withdrawal detection |
| `src/services/document_ingestion/pipeline.py` | `IngestionPipeline` |
| `src/integrations/llm/embeddings.py` | `Embedder` protocol, `BgeM3Embedder` |
| `src/storage/document_store/raw_store.py` | Content-addressed raw file storage |
| `src/storage/document_store/repository.py` | Documents and versions |
| `src/storage/vector_index/repository.py` | Chunks and chunk links, candidate queries, passage fetch, link resolution |
| `src/services/retrieval/ranking.py` | Pure fusion/threshold/flags/conflicts/dedupe |
| `src/services/retrieval/service.py` | `RetrievalService` |
| `src/services/retrieval/evaluation.py` | Eval models + metrics |
| `config/rag/sources.yaml` | Source registry and classification rules |
| `config/rag/eval_questions.yaml` | Evaluation set |
| `scripts/rag/scrape.py`, `ingest.py`, `search.py`, `evaluate.py` | Thin CLIs |
| `tests/support/fake_embedder.py` | Deterministic `HashingEmbedder` |
| `tests/fixtures/rag/` | Synthetic HTML files and `pdf_builders.py` |
| `tests/unit/rag/`, `tests/integration/rag/` | Tests |
| `docs/runbooks/rag-local.md`, `docs/decisions/0001-local-rag-pgvector.md` | Runbook and decision record |

---

### Task 1: Local database, settings, errors and migrations

**Files:**
- Modify: `requirements.txt`, `.agents/BOARD.md`
- Create:
  - `pytest.ini`, `.env.example`
  - `infrastructure/local/docker-compose.yml`, `infrastructure/local/initdb/01-create-test-db.sql`
  - `src/core/settings.py`, `src/core/errors.py`
  - `src/storage/application_db/migrations/0001_knowledge.sql`, `src/storage/application_db/migrate.py`
- Test:
  - `tests/integration/rag/__init__.py`, `tests/integration/rag/conftest.py`, `tests/integration/rag/test_migrations.py`
  - `tests/unit/rag/__init__.py`, `tests/unit/rag/test_settings.py`

**Interfaces:**
- Produces:
  - `RagSettings` (pydantic `BaseModel`) with these fields:

    | Field | Default |
    |---|---|
    | `database_url` | `"postgresql://rag:rag@127.0.0.1:5433/rag"` |
    | `embedding_model` | `"BAAI/bge-m3"` |
    | `embedding_device` | `"cpu"` |
    | `raw_dir` | `Path("data/local/rag/raw")` |
    | `manifest_path` | `Path("data/local/rag/manifest.jsonl")` |
    | `sources_path` | `Path("config/rag/sources.yaml")` |
    | `candidate_k` | `30` |
    | `rrf_k` | `60` |
    | `dense_floor` | `0.55` |
    | `keyword_floor` | `0.10` |
    | `secondary_dense_floor` | `0.40` |
    | `authority_weights` | `{"high": 1.0, "medium": 0.9, "low": 0.75}` |

  - `load_rag_settings(env: Mapping[str, str] | None = None) -> RagSettings`: reads `.env` via python-dotenv, then the `RAG_*` uppercase env names (e.g. `RAG_DATABASE_URL`, `RAG_DENSE_FLOOR`).
  - `src/core/errors.py`:
    - `class RagError(Exception)`
    - `KnowledgeStoreUnavailable(RagError)`
    - `EmbeddingModelUnavailable(RagError)`
    - `IngestionError(RagError)`
    - `TemplateMismatch(RagError)`
  - `apply_migrations(conn: psycopg.Connection) -> list[str]`: applies `migrations/*.sql` in filename order, inside one transaction per file. Tracks them in `schema_migrations(filename text primary key, applied_at timestamptz)` and returns newly applied filenames.
  - Integration fixture `db_conn` (function-scoped `psycopg.Connection`):
    - connects to `RAG_TEST_DATABASE_URL` (default `postgresql://rag:rag@127.0.0.1:5433/rag_test`)
    - `pytest.skip` if unreachable
    - once per session: drop and recreate schema `public`, then apply migrations
    - per test: `TRUNCATE knowledge_chunk_links, knowledge_chunks, knowledge_document_versions, knowledge_documents, index_runs RESTART IDENTITY CASCADE`

- [ ] **Step 1: Claim the task and set up the environment**

Add a row to `.agents/BOARD.md`:

| Field | Value |
|---|---|
| Task ID | `RAG-01` |
| Files | `src/services/document_ingestion, src/services/retrieval, src/storage/{document_store,vector_index}, scripts/rag, config/rag` |
| Assigned to | `Claude` |
| Status | `IN_PROGRESS` |
| Started | `2026-10-28` |
| Notes | `Local RAG per docs/superpowers/specs/2026-10-28-rag-retrieval-design.md` |

Add to `requirements.txt`:

```text
# RAG (local retrieval)
psycopg[binary]>=3.2
pgvector>=0.3
sentence-transformers>=3.0
beautifulsoup4>=4.12
pymupdf>=1.24
httpx>=0.27
pyyaml>=6.0

# Testing
pytest>=8.0
```

Then run `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt`.
Expected: the install completes.

`pytest.ini`:

```ini
[pytest]
pythonpath = .
testpaths = tests
markers =
    integration: needs the local Docker Postgres (skipped if unreachable)
```

- [ ] **Step 2: Write `docker-compose.yml` and the init script, then start the database**

Compose service `rag-db`:
- image `pgvector/pgvector:pg16`
- `POSTGRES_USER=rag`, `POSTGRES_PASSWORD=rag`, `POSTGRES_DB=rag`
- ports `"127.0.0.1:5433:5432"`
- named volume `rag_pgdata:/var/lib/postgresql/data`
- `./initdb:/docker-entrypoint-initdb.d:ro`
- healthcheck `pg_isready -U rag`

The init script runs `CREATE DATABASE rag_test OWNER rag;`.

Run: `docker compose -f infrastructure/local/docker-compose.yml up -d && docker compose -f infrastructure/local/docker-compose.yml ps`
Expected: `rag-db` is `healthy`.

- [ ] **Step 3: Write failing tests**

`tests/unit/rag/test_settings.py`:

```python
def test_defaults_and_env_override():
    s = load_rag_settings(env={})
    assert s.database_url == "postgresql://rag:rag@127.0.0.1:5433/rag"
    assert s.rrf_k == 60 and s.candidate_k == 30
    s2 = load_rag_settings(env={"RAG_DENSE_FLOOR": "0.6", "RAG_DATABASE_URL": "postgresql://x/y"})
    assert s2.dense_floor == 0.6 and s2.database_url == "postgresql://x/y"
```

`tests/integration/rag/test_migrations.py` (marked `integration`):

```python
def test_schema_created(db_conn):
    exts = {r[0] for r in db_conn.execute("select extname from pg_extension")}
    assert {"vector", "unaccent"} <= exts
    tables = {r[0] for r in db_conn.execute(
        "select tablename from pg_tables where schemaname='public'")}
    assert {"knowledge_documents", "knowledge_document_versions",
            "knowledge_chunks", "knowledge_chunk_links", "index_runs", "schema_migrations"} <= tables

def test_unaccent_search_config_matches_without_diacritics(db_conn):
    row = db_conn.execute(
        "select to_tsvector('ro_unaccent', 'Dobânda fixă') @@ to_tsquery('ro_unaccent', 'dobanda')").fetchone()
    assert row[0] is True

def test_apply_migrations_is_idempotent(db_conn):
    assert apply_migrations(db_conn) == []
```

- [ ] **Step 4: Run them and confirm they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_settings.py tests/integration/rag/test_migrations.py -v`
Expected: FAIL, with ImportError on `load_rag_settings` / `apply_migrations`.

- [ ] **Step 5: Implement settings, errors, the migration runner and `0001_knowledge.sql`**

The migration implements spec §11, with these exact decisions:

- **Extensions:** `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS unaccent;`
- **Text search config `ro_unaccent`:** create it in a `DO` block.
  - If `pg_ts_config` has `romanian`, use `COPY = romanian` and `ALTER MAPPING FOR hword, hword_part, word WITH unaccent, romanian_stem`.
  - Otherwise use `COPY = simple` and `ALTER MAPPING ... WITH unaccent, simple`.
- **`knowledge_documents`:**
  - columns: `id bigserial pk`, `canonical_key text unique not null`, `source_url text not null`, `title text not null`, `doc_kind text not null`
  - `publisher text not null default 'Raiffeisen Bank Romania'`, `language text not null default 'ro'`
  - `status text not null default 'active' check (status in ('active','withdrawn'))`
  - `last_seen_at timestamptz`, `created_at timestamptz default now()`
- **`knowledge_document_versions`:**
  - columns: `id bigserial pk`, `document_id bigint not null references knowledge_documents on delete cascade`, `content_hash text not null`, `version_label text`
  - `effective_from date not null`, `effective_date_source text not null check (in 'document_text','filename','sitemap_lastmod','fetched_at')`
  - `fetched_at timestamptz not null`, `sitemap_lastmod date`, `raw_path text not null`, `campaign_valid_until date`
  - `ingested_at timestamptz not null default now()`, `parser_name text not null`, `parser_version text not null`
  - constraint: `unique(document_id, content_hash)`
- **`knowledge_chunks`:**
  - columns: `id bigserial pk`, `version_id bigint not null references knowledge_document_versions on delete cascade`, `ordinal int not null`, `kind text not null`, `topic text not null`
  - `products text[] not null`, `authority text not null`, `section_path text[] not null`, `page int`, `anchor text`
  - `header text not null`, `text text not null`, `token_count int not null`
  - `prev_chunk_id bigint`, `next_chunk_id bigint`, `parent_section_key text`
  - `embedding vector(1024) not null`
  - `tsv tsvector generated always as (to_tsvector('ro_unaccent', header || ' ' || text)) stored`
  - indexes: HNSW `(embedding vector_cosine_ops)`, GIN `(tsv)`, GIN `(products)`, btree `(topic)`, btree `(version_id)`
- **`knowledge_chunk_links`:**
  - columns: `chunk_id bigint not null references knowledge_chunks on delete cascade`, `target_canonical_key text not null`, `anchor_text text not null`, `link_kind text not null check (link_kind in ('card','teaser','inline'))`, `ordinal int not null`
  - constraint: `primary key (chunk_id, target_canonical_key)`
  - index: btree `(target_canonical_key)`
  - no FK to documents: targets are resolved at query time (spec §9a)
- **`index_runs`:**
  - columns: `id bigserial pk`, `started_at timestamptz not null default now()`, `finished_at timestamptz`
  - `embedding_model text not null`, `chunker_version text not null`
  - `status text not null check (in 'running','completed','failed')`
  - `documents_seen int default 0`, `versions_created int default 0`, `failures int default 0`

Create `tests/integration/rag/conftest.py` with the `db_conn` fixture as specified under Interfaces.

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_settings.py tests/integration/rag/test_migrations.py -v`
Expected: 4 passed. If the integration tests show as skipped, the database isn't running; fix that before continuing.

- [ ] **Step 7: Commit**

Run `git add requirements.txt pytest.ini .env.example infrastructure/local src/core src/storage/application_db tests .agents/BOARD.md`, then commit with the message `agent(rag): local pgvector database, settings and knowledge schema`.

---

### Task 2: Shared knowledge models and taxonomies

**Files:**
- Create: `src/models/knowledge.py`
- Test: `tests/unit/rag/test_models.py`

**Interfaces:**
- Produces (all in `src.models.knowledge`):
  - `DocKind(StrEnum)`: `product_page`, `category_hub`, `guide`, `faq_page`, `article`, `fee_list`, `general_terms`, `cost_sheet`, `pdf_generic`
  - `ChunkKind(StrEnum)`: `section`, `faq`, `worked_example`, `hub_card`, `hub_teasers`, `fee_table`, `clause`, `cost_facts`, `cost_examples`, `generic`
  - `Authority(StrEnum)`: `high`, `medium`, `low`
  - `AUTHORITY_BY_DOC_KIND: dict[DocKind, Authority]`:
    - high: product_page, fee_list, general_terms, cost_sheet, pdf_generic
    - medium: guide, faq_page
    - low: article, category_hub
  - `LinkKind(StrEnum)`: `card`, `teaser`, `inline`
  - `RelatedLink` fields: `title: str`, `url: str`, `canonical_key: str`, `link_kind: LinkKind`
  - `Product(StrEnum)`: `personal_loan`, `refinancing_unsecured`, `refinancing_mortgage`, `mortgage_casa_ta`, `mortgage_casa_ta_verde`, `mortgage_noua_casa`, `mortgage_residential_projects`, `overdraft`, `credit_card`, `general`
  - `Topic(StrEnum)` covers credit topics plus non-credit topics:
    - credit: `eligibility`, `costs_fees`, `worked_example`, `required_documents`, `early_repayment`, `refinancing`, `restructuring_difficulty`, `variable_rate_ircc`, `repayment_methods`, `credit_process`, `general_terms_credit`
    - non-credit: `accounts`, `payments`, `cards`, `data_protection`, `aml`, `other`
  - `CREDIT_TOPICS: frozenset[Topic]`: the 11 credit topics above.
  - `PassageFlag(StrEnum)`: `superseded`, `withdrawn`, `campaign_active`, `campaign_ended`, `low_authority`, `teaser_figure`
  - `SearchStatus(StrEnum)`: `ok`, `insufficient_evidence`
  - `SearchQuery` fields:
    - `text: str` (stripped, 1–1000 chars)
    - `products: list[Product] | None = None`
    - `topics: list[Topic] | None = None`: `None` means `CREDIT_TOPICS`, exposed as the property `effective_topics`
    - `doc_kinds: list[DocKind] | None = None`
    - `top_k: int = 6` (1–20)
    - `as_of: date = Field(default_factory=date.today)`
    - `include_superseded: bool = False`
    - `include_withdrawn: bool = False`
    - `expand_context: bool = False`
  - `Citation` fields: `publisher: str`, `title: str`, `url: str`, `page: int | None`, `anchor: str | None`, `section_path: list[str]`, `version_label: str | None`, `effective_date: date`, `fetched_at: datetime`, `campaign_valid_until: date | None`
  - `Scores` fields: `dense: float | None`, `keyword: float | None`, `fused: float`
  - `PassageContext` fields: `previous: str | None`, `next: str | None`
  - `Passage` fields: `chunk_id: int`, `document_id: int`, `doc_kind: DocKind`, `kind: ChunkKind`, `topic: Topic`, `products: list[Product]`, `authority: Authority`, `header: str`, `text: str`, `citation: Citation`, `scores: Scores`, `flags: list[PassageFlag] = []`, `warnings: list[str] = []`, `defer_to: int | None = None`, `context: PassageContext | None = None`, `related_links: list[RelatedLink] = []`
  - `Conflict` fields: `doc_kind: DocKind`, `topic: Topic`, `product: Product`, `chunk_ids: list[int]`, `effective_dates: list[date]`
  - `IndexInfo` fields: `embedding_model: str`, `chunker_version: str`, `last_ingest_at: datetime`
  - `SearchResult` fields: `status: SearchStatus`, `passages: list[Passage] = []`, `conflicts: list[Conflict] = []`, `index_info: IndexInfo | None = None`, `content_trust: Literal["untrusted_evidence"] = "untrusted_evidence"`

- [ ] **Step 1: Write failing tests**

```python
def test_query_text_validation():
    with pytest.raises(ValidationError): SearchQuery(text="   ")
    with pytest.raises(ValidationError): SearchQuery(text="a" * 1001)
    assert SearchQuery(text="  Ce este DAE?  ").text == "Ce este DAE?"

def test_default_topics_are_credit_topics():
    q = SearchQuery(text="dobanda")
    assert set(q.effective_topics) == CREDIT_TOPICS
    assert Topic.accounts not in CREDIT_TOPICS and len(CREDIT_TOPICS) == 11

def test_top_k_bounds():
    with pytest.raises(ValidationError): SearchQuery(text="x", top_k=21)

def test_result_marks_content_untrusted():
    assert SearchResult(status=SearchStatus.ok).content_trust == "untrusted_evidence"

def test_authority_map_complete():
    assert set(AUTHORITY_BY_DOC_KIND) == set(DocKind)
    assert AUTHORITY_BY_DOC_KIND[DocKind.article] is Authority.low
    assert AUTHORITY_BY_DOC_KIND[DocKind.category_hub] is Authority.low
```

- [ ] **Step 2: Run them and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_models.py -v`. Expected: ImportError.
- [ ] **Step 3: Implement `src/models/knowledge.py` as specified under Interfaces.**
- [ ] **Step 4: Run them and confirm they pass.** Expected: 5 passed.
- [ ] **Step 5: Commit.** Message: `agent(rag): shared knowledge search models and taxonomies`.

---

### Task 3: Normalization, source config and metadata extraction

**Files:**
- Create: `src/services/document_ingestion/normalize.py`, `sources.py`, `metadata.py`, `config/rag/sources.yaml`
- Test: `tests/unit/rag/test_normalize.py`, `test_metadata.py`, `test_sources.py`

**Interfaces:**
- Consumes: `DocKind`, `Product`, `Topic`, `ChunkKind` from Task 2.
- Produces:
  - `normalize_text(text: str) -> str`: applies NFC, maps `ş→ș ţ→ț Ş→Ș Ţ→Ț`, replaces NBSP with a space, collapses runs of spaces and tabs, and trims each line. It keeps single newlines and collapses 3+ newlines to 2.
  - `canonical_key(url: str) -> str`: lowercased URL path with no host or query. The PDF rules apply in this order:
    1. If the filename starts with 8 digits and `-`, the key is the parent directory path.
    2. Else, if it ends with `.sv.pdf`, strip `.sv.pdf`.
    3. Else, strip `.coredownload.pdf` / `.coredownload.inline.pdf`.
    4. HTML keeps its path.
  - `EffectiveDateSource = Literal["document_text", "filename", "sitemap_lastmod", "fetched_at"]`
  - `extract_effective_date(doc_kind: DocKind, text: str, url: str, sitemap_lastmod: date | None, fetched_at: datetime) -> tuple[date, EffectiveDateSource]`. The text is used only for PDF kinds (`fee_list`, `general_terms`, `cost_sheet`, `pdf_generic`), and only within the first 600 chars. It recognises three patterns:
    - `Ediția`/`Editia DD.MM.YYYY`
    - `<day> <Romanian month name, with or without diacritics> <YYYY>`
    - a line that is exactly `DD.MM.YYYY`

    The filename is read as `YYYYMMDD`; an invalid calendar date is rejected (e.g. `20262602`), which falls through to the next source.
  - `extract_campaign_window(text: str, reference: date) -> date | None` reads phrases matching `Perioada campaniei` / `campania (este valabilă|se desfășoară)`, followed by `DD.MM[.YYYY] - DD.MM.YYYY` or `DD.MM - DD.MM`. It returns the latest end date found. If the year is missing, it uses `reference.year`.
  - `SourceConfig` (pydantic), loaded with `load_source_config(path: Path) -> SourceConfig`. Its fields:
    - `sitemap_url: str`
    - `page_allow: list[str]` (regex)
    - `pdf_allow: list[str]` (regex)
    - `discovery_seeds: list[str]` (fetched for links, not indexed)
    - `extra_urls: list[str]`
    - `drop_headings: list[str]`
    - `category_hubs: list[str]` (exact URLs classified as `category_hub`)
    - `link_drop_patterns: list[str]` (regex; links matching any are never kept)
    - `doc_kind_rules: list[PatternRule[DocKind]]`
    - `product_rules: list[ProductRule]`, where `ProductRule = {pattern: str, products: list[Product]}`
    - `topic_keyword_rules: list[TopicRule]`, where `TopicRule = {pattern: str, topic: Topic}`, regex matched case- and accent-insensitively
    - `general_terms_sections: dict[str, Topic]` (number prefix → topic)
    - `fee_list_sections: dict[str, SectionClass]`, where `SectionClass = {topic: Topic, products: list[Product]}`
    - `default_topic_by_doc_kind: dict[DocKind, Topic]`
  - `products_for_url(url: str, cfg: SourceConfig) -> list[Product]`: first matching product rule, else `[Product.general]`.
  - `classify_document(url: str, cfg: SourceConfig) -> tuple[DocKind, list[Product]]`:
    - URLs listed in `category_hubs` (compared after stripping query and fragment) → `category_hub`
    - else the first matching doc_kind rule
    - else `pdf_generic` for `.pdf` and `product_page` otherwise

    Products come from `products_for_url`.
  - `is_allowed_url(url: str, cfg: SourceConfig) -> bool`: true when the URL (query and fragment stripped) matches any `page_allow` or `pdf_allow` pattern and no `link_drop_patterns` pattern.
  - `classify_topic(doc_kind: DocKind, chunk_kind: ChunkKind, section_path: list[str], text: str, cfg: SourceConfig) -> Topic`. It checks, in order:
    1. `chunk_kind == worked_example` → `worked_example`
    2. `cost_facts` → `costs_fees`
    3. general_terms / fee_list: longest number-prefix match of the section number at the start of `section_path[-1]` or `section_path[0]`
    4. first `topic_keyword_rules` match on `" ".join(section_path) + " " + text[:300]`
    5. `default_topic_by_doc_kind[doc_kind]`, else `other`
  - `fee_section_products(section_path: list[str], cfg) -> list[Product] | None`: longest-prefix lookup in `fee_list_sections`.

- [ ] **Step 1: Write `config/rag/sources.yaml` with these initial values** (the allowlist may be adjusted in Task 11):

```yaml
sitemap_url: https://www.raiffeisen.ro/ro/sitemap.xml
page_allow:
  - ^https://www\.raiffeisen\.ro/ro/persoane-fizice/produsele-noastre/credite/.*\.html$
  - ^https://www\.raiffeisen\.ro/ro/persoane-fizice/produsele-noastre/carduri/.*credit.*\.html$
  - ^https://www\.raiffeisen\.ro/ro/aplica/restructurare-credit\.html$
  - ^https://www\.raiffeisen\.ro/ro/persoane-fizice/in-sprijinul-tau/tine-ti-ratele-sub-control\.html$
  - ^https://www\.raiffeisen\.ro/ro/persoane-fizice/in-sprijinul-tau/informatii-utile/.*\.html$
  - ^https://www\.raiffeisen\.ro/ro/.*despre-bani-1-la-1/.*(credit|rata|rate|dobanda|refinant|ipotec|imobiliar|dae|ircc|imprumut).*\.html$
pdf_allow:
  - ^https://www\.raiffeisen\.ro/content/dam/rbi/retail/eu/ro/documents/(costuri|pf/credite|pf/tarife-comisioane-standard-pf|conditii-general-bancare-pf)/.*
  - ^https://www\.raiffeisen\.ro/content/dam/rbi/retail/eu/ro/documents/pf/tarife-comisioane-standard-pf\.sv\.pdf$
discovery_seeds:
  - https://www.raiffeisen.ro/ro/persoane-fizice/in-sprijinul-tau/documente.html
extra_urls: []
drop_headings: ["Când și de ce", "Cum obții", "Calculează rata", "Ce spun clienții", "gândit pentru tine",
                "Articole utile", "Descoperă mai multe", "Motive în plus", "Lasă-ne datele"]
category_hubs:
  - https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credite.html
  - https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale.html
  - https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credite-imobiliare.html
  - https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credite-de-refinantare.html
link_drop_patterns:
  - "adjust\\.com|\\.adj\\.st|go\\.link"
  - "/agentii|harta-agentiilor|locator|programare-online|rezerva"
doc_kind_rules:
  - {pattern: "/costuri/", value: cost_sheet}
  - {pattern: "tarife-comisioane", value: fee_list}
  - {pattern: "conditii-general-bancare", value: general_terms}
  - {pattern: "\\.pdf", value: pdf_generic}
  - {pattern: "intrebari-frecvente", value: faq_page}
  - {pattern: "despre-bani-1-la-1/", value: article}
  - {pattern: "/credite/credite-(de-nevoi-personale|imobiliare)/.+\\.html$", value: guide}
product_rules:
  - {pattern: "refinantare-garantat-cu-ipoteca|flexi-integral", products: [refinancing_mortgage]}
  - {pattern: "refinantare", products: [refinancing_unsecured]}
  - {pattern: "casa-ta-verde", products: [mortgage_casa_ta_verde]}
  - {pattern: "casa-ta", products: [mortgage_casa_ta]}
  - {pattern: "noua-casa", products: [mortgage_noua_casa]}
  - {pattern: "proiecte-rezidentiale", products: [mortgage_residential_projects]}
  - {pattern: "overdraft", products: [overdraft]}
  - {pattern: "card", products: [credit_card]}
  - {pattern: "nevoi-personale|flexicredit", products: [personal_loan]}
  - {pattern: "credite-imobiliare|/ipotecare/", products: [mortgage_casa_ta, mortgage_casa_ta_verde, mortgage_noua_casa, mortgage_residential_projects]}
topic_keyword_rules:
  - {pattern: "rambursa\\w* anticipat|plata anticipat", topic: early_repayment}
  - {pattern: "refinant", topic: refinancing}
  - {pattern: "restructur|dificult|amanare|amânare|suspendare|darea in plata", topic: restructuring_difficulty}
  - {pattern: "ircc|robor|dobanda variabil|marja", topic: variable_rate_ircc}
  - {pattern: "rate (egale|descrescatoare)|modalitat\\w* de rambursare", topic: repayment_methods}
  - {pattern: "acte|documente necesare|documente solicitate|adeverint", topic: required_documents}
  - {pattern: "conditii|eligibil|varsta|venit minim|vechime", topic: eligibility}
  - {pattern: "dae|dobanda|comision|costuri|tarif", topic: costs_fees}
general_terms_sections: {"1": other, "1.6": aml, "2.1": data_protection, "2.2": data_protection,
                         "2.3": general_terms_credit, "3": accounts, "3.4": general_terms_credit,
                         "3.5": general_terms_credit, "4": payments, "5": cards, "6": other,
                         "7": payments, "8": general_terms_credit}
fee_list_sections:
  "1": {topic: accounts, products: [general]}
  "2": {topic: payments, products: [general]}
  "3": {topic: payments, products: [general]}
  "4": {topic: other, products: [general]}
  "5": {topic: payments, products: [general]}
  "6": {topic: cards, products: [general]}
  "7": {topic: costs_fees, products: [credit_card]}
default_topic_by_doc_kind: {product_page: credit_process, category_hub: credit_process, guide: credit_process, faq_page: credit_process,
                            article: credit_process, cost_sheet: costs_fees, pdf_generic: credit_process,
                            fee_list: other, general_terms: other}
```

- [ ] **Step 2: Write failing tests** (the URLs are the real ones from the survey, which are fine to commit):

```python
D = "https://www.raiffeisen.ro/content/dam/rbi/retail/eu/ro/documents/"

def test_normalize_text():
    assert normalize_text("Dobânda  fixă la\tşi ţară") == "Dobânda fixă la și țară"

def test_canonical_key_alias_and_dated_file_match():
    a = canonical_key(D + "pf/tarife-comisioane-standard-pf.sv.pdf")
    b = canonical_key(D + "pf/tarife-comisioane-standard-pf/20260901-Tarife-si-comisioane-standard-persoane-fizice.pdf.coredownload.pdf")
    assert a == b == "/content/dam/rbi/retail/eu/ro/documents/pf/tarife-comisioane-standard-pf"

def test_canonical_key_uses_folder_for_misnamed_cost_sheet():
    k = canonical_key(D + "costuri/garantate/costuri-casa-ta-dobanda-fixa-5-ani/20261022-Costuri-casa-ta-dobanda-fixa-3-ani.pdf.coredownload.pdf")
    assert k.endswith("costuri-casa-ta-dobanda-fixa-5-ani")

def test_canonical_key_html():
    assert canonical_key("https://www.raiffeisen.ro/ro/a/b.html?x=1") == "/ro/a/b.html"

FETCHED = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)

def test_effective_date_precedence():
    assert extract_effective_date(DocKind.fee_list, "Tarife\n1 septembrie 2026\n", D + "x.pdf", None, FETCHED) == (date(2026, 9, 1), "document_text")
    assert extract_effective_date(DocKind.general_terms, "Conditiile ... Editia 26.02.2026", D + "20262602-C.pdf", None, FETCHED) == (date(2026, 2, 26), "document_text")
    assert extract_effective_date(DocKind.cost_sheet, "15.10.2026\nFlexi", D + "y.pdf", None, FETCHED) == (date(2026, 10, 15), "document_text")
    assert extract_effective_date(DocKind.pdf_generic, "fara data", D + "c/20240129-x.pdf", None, FETCHED) == (date(2024, 1, 29), "filename")
    assert extract_effective_date(DocKind.pdf_generic, "fara data", D + "c/20262602-x.pdf", date(2026, 3, 1), FETCHED) == (date(2026, 3, 1), "sitemap_lastmod")
    assert extract_effective_date(DocKind.product_page, "Perioada campaniei: 15.10 - 26.11.2026", "https://x/ro/p.html", None, FETCHED) == (date(2026, 10, 28), "fetched_at")

def test_campaign_window():
    assert extract_campaign_window("Perioada campaniei: 15.10 - 26.11.2026.", date(2026, 10, 28)) == date(2026, 11, 26)
    assert extract_campaign_window("Perioada campaniei: 01.03 - 31.03", date(2026, 10, 28)) == date(2026, 3, 31)
    assert extract_campaign_window("Fără campanie", date(2026, 10, 28)) is None

def test_classify_document_and_topic():
    cfg = load_source_config(Path("config/rag/sources.yaml"))
    assert classify_document(D + "costuri/costuri-complete-flexicredit-standard/20261015-x.pdf", cfg) == (DocKind.cost_sheet, [Product.personal_loan])
    assert classify_document("https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale/intrebari-frecvente-credit-nevoi-personale.html", cfg)[0] is DocKind.faq_page
    assert classify_topic(DocKind.general_terms, ChunkKind.clause, ["3. Conditii", "3.4 Descoperit de cont"], "", cfg) is Topic.general_terms_credit
    assert classify_topic(DocKind.general_terms, ChunkKind.clause, ["5. Card", "5.1 Emiterea"], "", cfg) is Topic.cards
    assert classify_topic(DocKind.product_page, ChunkKind.section, ["Flexicredit", "Ce acte îți trebuie"], "act de identitate", cfg) is Topic.required_documents
    assert classify_topic(DocKind.cost_sheet, ChunkKind.cost_facts, [], "", cfg) is Topic.costs_fees

def test_hubs_and_link_allowlist():
    cfg = load_source_config(Path("config/rag/sources.yaml"))
    C = "https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/"
    assert classify_document(C + "credite-de-nevoi-personale.html", cfg)[0] is DocKind.category_hub
    assert classify_document(C + "credite-de-nevoi-personale/conditii-credit-nevoi-personale.html", cfg)[0] is DocKind.guide
    assert products_for_url(C + "overdraft.html", cfg) == [Product.overdraft]
    assert is_allowed_url(C + "overdraft.html#x", cfg)
    assert not is_allowed_url("https://raiffeisen.go.link/abc", cfg)
    assert not is_allowed_url("https://www.raiffeisen.ro/ro/contact/agentii.html", cfg)
```

- [ ] **Step 3: Run them and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_normalize.py tests/unit/rag/test_metadata.py tests/unit/rag/test_sources.py -v`. Expected: ImportError.
- [ ] **Step 4: Implement `normalize.py`, `metadata.py` and `sources.py`.** Accent-insensitive matching means comparing `unicodedata.normalize("NFKD")` with combining marks removed, lowercased, on both sides.
- [ ] **Step 5: Run them and confirm they pass.** Expected: all pass.
- [ ] **Step 6: Commit.** Message: `agent(rag): normalization, source registry and metadata extraction`.

---

### Task 4: Chunk primitives, HTML parsers and "read more" links

**Files:**
- Create:
  - `src/services/document_ingestion/chunking.py`
  - `src/services/document_ingestion/parsers/__init__.py`
  - `src/services/document_ingestion/parsers/links.py`
  - `src/services/document_ingestion/parsers/html_page.py`
  - `src/services/document_ingestion/parsers/category_hub.py`
  - `tests/fixtures/rag/product_page.html`, `tests/fixtures/rag/faq_page.html`, `tests/fixtures/rag/category_hub.html`
- Test: `tests/unit/rag/test_chunking.py`, `tests/unit/rag/test_html_parser.py`, `tests/unit/rag/test_links.py`, `tests/unit/rag/test_category_hub_parser.py`

**Interfaces:**
- Consumes: `ChunkKind`, `DocKind`, `LinkKind`, `Product`, `SourceConfig`, `normalize_text`, `canonical_key`, `products_for_url`, `is_allowed_url`.
- Produces:
  - `CHUNKER_VERSION = "1"`, `MAX_TOKENS = 500`
  - `estimate_tokens(text: str) -> int` (= `max(1, len(text) // 4)`)
  - `@dataclass ExtractedLink` (in `parsers/links.py`) fields: `target_url: str` (absolute, no query or fragment), `anchor_text: str`, `link_kind: LinkKind`
  - `@dataclass ChunkDraft` fields: `kind: ChunkKind`, `section_path: list[str]`, `text: str`, `page: int | None = None`, `anchor: str | None = None`, `products_override: list[Product] | None = None`, `links: list[ExtractedLink] = field(default_factory=list)`
  - `@dataclass ParsedDocument` fields: `title: str`, `chunks: list[ChunkDraft]`, `metadata_text: str` (cleaned full text for date/campaign detection), `parser_name: str`, `parser_version: str = CHUNKER_VERSION`, `warnings: list[str] = field(default_factory=list)`
  - `pack_lines(lines: list[str], max_tokens: int = MAX_TOKENS, repeat_header: str | None = None) -> list[str]`: greedy packing on line boundaries. A single line over the limit becomes its own piece and is not split. `repeat_header` is prepended to every piece after the first.
  - `build_header(title: str, section_path: list[str], effective_date: date) -> str`, for example `"Raiffeisen Bank › {title} › {p1} › {p2} · {YYYY-MM-DD}"`. Empty path parts are skipped. With no path, the format is `"Raiffeisen Bank › {title} · {date}"`.
  - `links.py`:
    - `absolutize(href: str, page_url: str) -> str | None`: joins the href with `page_url`, strips query and fragment, and returns `None` for `mailto:`, `tel:`, `javascript:`, empty and fragment-only hrefs. A raiffeisen.ro host with or without `www`, over http or https, normalizes to `https://www.raiffeisen.ro`.
    - `filter_chunk_links(chunks: list[ChunkDraft], page_url: str, cfg: SourceConfig, chip_targets: frozenset[str] = frozenset()) -> None`. Mutates each chunk's `links`, keeping only links that pass all of these:
      - `is_allowed_url`
      - target not a self-link (`canonical_key(target) == canonical_key(page_url)`)
      - target not in `chip_targets`
      - first occurrence of that `canonical_key` within the chunk
  - `html_page.py`:
    - `clean_html(data: bytes) -> BeautifulSoup`: removes `script, style, form, noscript`, and removes `header, footer, nav` **only when they are not inside a `.cmp-teaser`**. Content-component headers and footers keep their links.
    - `content_root(soup) -> Tag` (`<main>`, else `<body>`)
    - `accordion_chunk(item: Tag, path_prefix: list[str], page_url: str) -> ChunkDraft`: shared by both HTML parsers
    - `parse_html_page(data: bytes, page_url: str, cfg: SourceConfig) -> ParsedDocument` with `parser_name="html_page"`; it uses `cfg.drop_headings` and calls `filter_chunk_links` before returning
  - `category_hub.py`: `parse_category_hub(data: bytes, page_url: str, cfg: SourceConfig) -> ParsedDocument` with `parser_name="category_hub"`
  - `parse_document(doc_kind: DocKind, data: bytes, url: str, cfg: SourceConfig) -> ParsedDocument` dispatches as follows:
    - `category_hub` → `parse_category_hub`
    - other HTML kinds → `parse_html_page`
    - PDF kinds → the parsers of Tasks 5–6, which ignore `url` and `cfg`
- HTML page rules (spec §9, as validated by the spike):
  - **Cleanup:** via `clean_html`. **Root:** `content_root`.
  - **Title:** h1 text, else `<title>` before `|`.
  - **Walk:** walk `h1,h2,h3,p,li,table,div.cmp-accordion__item` in document order.
  - **Accordions:** each `.cmp-accordion__item` produces one `faq` chunk, `"Întrebare: {q}\nRăspuns: {a}"`. `q` comes from `.cmp-accordion__title`; `a` comes from the `p, li` inside `.cmp-accordion__panel`. Its section path is `[h1, h2 or h3 group heading, q]`. Elements inside an accordion item are not walked separately.
  - **Section headings:** a non-accordion h1/h2/h3 flushes the buffer and sets the path. A heading whose text matches a `drop_headings` entry (substring) drops everything until the next heading of the same or higher level.
  - **Heading-only content:** if an h3 is followed by another heading with no body text in between, the h3 text is added to the parent h2 section buffer as a `- {text}` line.
  - **Worked examples:** a `p` whose text starts with `Exemplu de calcul` flushes the buffer and starts a `worked_example` chunk. The chunk ends at the next heading or the next `Exemplu de calcul` paragraph. The next non-example paragraph after the example's body also ends it: an example body is the heading paragraph plus the paragraphs up to the first one that does not begin with `Pentru un credit`.
  - **Text cleanup:** `p`/`li` nested in `li`/`table` are skipped. `li` text gets a `- ` prefix. Tables become ` | `-joined rows. Exact duplicate text blocks are dropped. Whitespace before punctuation is removed (`re.sub(r"\s+([.,;:!?])", r"\1", ...)`).
  - **Inline links:** every `<a href>` inside a walked `p`, `li`, table cell or accordion panel becomes an `inline` link on the chunk that element's text ends up in. When a section is split by `pack_lines`, each link goes with the piece that contains its line.
  - **Splitting:** section buffers become `section` chunks, split via `pack_lines`.
- Category hub rules (spec §9 `category_hub`, matching the real markup verified on 2026-10-28):
  - **Cleanup:** via `clean_html`. The h1 and the paragraphs before the first h2 are dropped (marketing intro).
  - **Teasers:** each `.cmp-teaser`:
    - Title: the first `h3` inside it.
    - Description: its `p` text, punctuation-fixed, so `"Dobândă de la <b>5,55%</b>."` becomes `"Dobândă de la 5,55%."`.
    - Button link: the `<a>` inside `.cmp-buttonbar`. Image link: the `<a class="cmp-image__link">`.
    - Primary target: the button link, else the image link.
  - **Card vs article teaser:** a teaser whose button text starts with `Citește` is an **article teaser**; any other teaser is a **product card**.
  - **Product cards:** each card becomes one `hub_card` chunk:
    - text `"{title}\n{description}"`
    - `section_path=[enclosing h2 text, title]`
    - `products_override=products_for_url(primary_target, cfg)`
    - links: the primary target as `card`
  - **Article teasers:** all article teasers under the same h2 become one `hub_teasers` chunk:
    - text `"{h2}\n- {title1}\n- {title2}…"`
    - `section_path=[h2]`
    - links: each teaser's button target as `teaser`, with the title as anchor text
  - **Chip rule** (the design's "repeated identically in every teaser" rule, made precise): a target that appears in ≥ 2 teasers on the page and is never any teaser's button target goes into `chip_targets`. The real case is the credit-card article image link on every article teaser. Pass `chip_targets` to `filter_chunk_links`. A card's own image link is never a chip, because it equals that card's button target.
  - **FAQ:** accordion items become `faq` chunks via `accordion_chunk`, with `section_path=[h2, q]`.
  - **Title:** the `<title>` text before `|`.

- [ ] **Step 1: Write the synthetic fixtures** (invented product names; only the link URLs are real raiffeisen.ro paths)

`product_page.html` is a synthetic AEM-like page for an invented product "Credit Demo". It contains:
- a site-level `<header>` with a nav link and a `<footer>`, both outside `<main>`
- an h1
- an h2 `Ce condiții trebuie să îndeplinești?` followed by three h3 conditions with no body (`Vârstă între 20 și 60 de ani`, `Venit minim 2.500 lei`, `Minimum 6 luni la locul de muncă`)
- an h2 `Ce acte îți trebuie` with one `p` that contains the inline link `<a href="/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale/conditii-credit-nevoi-personale.html">articolul despre condiții</a>`, plus a second link to `https://raiffeisen.go.link/x`
- an h2 `Exemple de calcul` with:
  - an intro `p`
  - two `Exemplu de calcul …` paragraphs, each followed by a `Pentru un credit …` paragraph
  - a trailing `p` `Ofertele sunt supuse unor termeni.`
- an h2 `Articole utile` with an h3 and a `p` (to be dropped)
- one accordion item `Pot rambursa anticipat?`
- the same `p` text duplicated once
- a link to the page itself

`faq_page.html` has two h3 group headings, each followed by two accordion items.

`category_hub.html` mirrors the real hub structure:
- a site `<header>`, an h1 and an intro `p`
- an h2 `Credite demo în detaliu` with two product cards (`article.cmp-teaser`, each with `header.cmp-teaser__header` > image link and `.cmp-buttonbar` > button `Află mai multe`):
  - `Credit Demo fără ipotecă`: description `Aplici ușor. Dobândă de la <b>6,10%</b>.`, target `/ro/persoane-fizice/produsele-noastre/credite/credit-de-nevoi-personale-fara-ipoteca.html` on both links
  - `Overdraft Demo`: button only, target `/ro/persoane-fizice/produsele-noastre/credite/overdraft.html`
- an h2 `Vrei să știi mai multe?` with three article teasers (button `Citește articolul`). Each has its own button target under `/credite/credite-de-nevoi-personale/…`, and every one has the same image link `/ro/persoane-fizice/produsele-noastre/carduri/carduri-de-cumparaturi/de-ce-sa-folosesti-cardul-de-credit-pentru-cumparaturi-pro-si-contra.html`.
- an h2 `FAQ Întrebări frecvente` with two accordion items

- [ ] **Step 2: Write failing tests**

```python
CFG = load_source_config(Path("config/rag/sources.yaml"))
BASE = "https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/"
PAGE_URL = BASE + "credit-de-nevoi-personale-fara-ipoteca.html"
HUB_URL = BASE + "credite-de-nevoi-personale.html"

def test_pack_lines_respects_limit_and_repeats_header():
    lines = ["x" * 800] * 5                     # 200 tokens each
    parts = pack_lines(lines, max_tokens=500, repeat_header="H")
    assert len(parts) == 3 and parts[1].startswith("H\n")

def test_build_header():
    assert build_header("Credit Demo", ["Costuri", ""], date(2026, 10, 15)) == "Raiffeisen Bank › Credit Demo › Costuri · 2026-10-15"

def _page():
    return parse_html_page(Path("tests/fixtures/rag/product_page.html").read_bytes(), PAGE_URL, CFG)

def test_heading_only_conditions_are_kept():
    elig = [c for c in _page().chunks if "Ce condiții" in " ".join(c.section_path)]
    assert len(elig) == 1 and "- Vârstă între 20 și 60 de ani" in elig[0].text and "- Venit minim 2.500 lei" in elig[0].text

def test_worked_examples_are_atomic_and_exclude_trailing_text():
    ex = [c for c in _page().chunks if c.kind is ChunkKind.worked_example]
    assert len(ex) == 2 and all(c.text.startswith("Exemplu de calcul") for c in ex)
    assert all("Ofertele sunt supuse" not in c.text for c in ex)

def test_faq_items_become_qa_chunks():
    faq = [c for c in parse_html_page(Path("tests/fixtures/rag/faq_page.html").read_bytes(), BASE + "x/intrebari-frecvente-demo.html", CFG).chunks if c.kind is ChunkKind.faq]
    assert len(faq) == 4 and faq[0].text.startswith("Întrebare: ") and "\nRăspuns: " in faq[0].text
    assert len(faq[0].section_path) == 3

def test_dropped_sections_duplicates_and_site_chrome():
    doc = _page()
    assert not any("Articole utile" in " ".join(c.section_path) for c in doc.chunks)
    joined = "\n".join(c.text for c in doc.chunks)
    assert joined.count("<the duplicated paragraph text from the fixture>") == 1
    assert "<site header nav text from the fixture>" not in joined
    assert doc.title and doc.parser_name == "html_page"

def test_inline_links_kept_filtered_and_attached():          # in test_links.py
    acte = next(c for c in _page().chunks if "Ce acte" in " ".join(c.section_path))
    assert [(l.target_url, l.link_kind) for l in acte.links] == [
        (BASE + "credite-de-nevoi-personale/conditii-credit-nevoi-personale.html", LinkKind.inline)]
    assert all(l.target_url != PAGE_URL for c in _page().chunks for l in c.links)   # self-link dropped

def test_absolutize_odd_hrefs():                             # in test_links.py
    page = PAGE_URL
    for junk in ["", "#", "#top", "javascript:void(0)", "tel:*2000", "mailto:a@b.ro"]:
        assert absolutize(junk, page) is None
    assert absolutize("overdraft.html?utm=x#faq", page) == BASE + "overdraft.html"
    assert canonical_key(absolutize("http://raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/overdraft.html", page)) == canonical_key(BASE + "overdraft.html")

def test_clean_html_keeps_teaser_header_links():             # in test_links.py
    soup = clean_html(Path("tests/fixtures/rag/category_hub.html").read_bytes())
    assert soup.select("article.cmp-teaser header.cmp-teaser__header a.cmp-image__link")
    assert not soup.select("body > header")

def _hub():
    return parse_category_hub(Path("tests/fixtures/rag/category_hub.html").read_bytes(), HUB_URL, CFG)

def test_hub_cards_one_chunk_each_with_product_from_link_target():
    cards = [c for c in _hub().chunks if c.kind is ChunkKind.hub_card]
    assert [c.section_path[-1] for c in cards] == ["Credit Demo fără ipotecă", "Overdraft Demo"]
    assert cards[0].text == "Credit Demo fără ipotecă\nAplici ușor. Dobândă de la 6,10%."
    assert cards[0].products_override == [Product.personal_loan] and cards[1].products_override == [Product.overdraft]
    assert [l.link_kind for l in cards[0].links] == [LinkKind.card]

def test_hub_article_teasers_one_block_without_chip_link():
    block = [c for c in _hub().chunks if c.kind is ChunkKind.hub_teasers]
    assert len(block) == 1 and block[0].text.count("\n- ") == 3
    targets = [l.target_url for l in block[0].links]
    assert len(targets) == 3 and all("/carduri/" not in t for t in targets)
    assert all(l.link_kind is LinkKind.teaser for l in block[0].links)

def test_hub_faq_and_intro_dropped():
    doc = _hub()
    assert sum(c.kind is ChunkKind.faq for c in doc.chunks) == 2
    assert not any("<hub h1 text from the fixture>" in c.text for c in doc.chunks)
    assert doc.parser_name == "category_hub"
```

The implementer replaces the `<…>` placeholders with the actual strings from their fixtures.

- [ ] **Step 3: Run them and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_chunking.py tests/unit/rag/test_html_parser.py tests/unit/rag/test_links.py tests/unit/rag/test_category_hub_parser.py -v`.
- [ ] **Step 4: Implement `chunking.py`, `parsers/links.py`, `parsers/html_page.py`, `parsers/category_hub.py` and `parsers/__init__.py`.** PDF kinds raise `NotImplementedError` until Tasks 5–6.
- [ ] **Step 5: Run them and confirm they pass.**
- [ ] **Step 6: Smoke-check on the real hub** (`~/rag-spike/input/hub-nevoi.html`, not committed). Parse it with `parse_category_hub` against its real URL `https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale.html` and print each chunk's kind, products and links. Expected:
  - two `hub_card` chunks: the Flexicredit card (`personal_loan`, text containing `Dobândă de la 5,55%`) and the Overdraft card (`overdraft`)
  - one `hub_teasers` chunk with 5 article links and no `/carduri/` link
  - 3 `faq` chunks
- [ ] **Step 7: Commit.** Message: `agent(rag): chunk primitives, HTML and category hub parsers with read-more links`.

---

### Task 5: PDF row rebuilding, fee list and general terms parsers

**Files:**
- Create:
  - `src/services/document_ingestion/parsers/pdf_rows.py`
  - `src/services/document_ingestion/parsers/fee_list.py`
  - `src/services/document_ingestion/parsers/general_terms.py`
  - `tests/fixtures/rag/__init__.py`, `tests/fixtures/rag/pdf_builders.py`
- Test: `tests/unit/rag/test_pdf_rows.py`, `test_fee_list_parser.py`, `test_general_terms_parser.py`

**Interfaces:**
- Consumes: `ChunkDraft`, `ParsedDocument`, `pack_lines`, `estimate_tokens`, `normalize_text`.
- Produces:
  - `make_pdf(pages: list[list[tuple[float, float, str]]], fontsize: float = 9) -> bytes` (test helper): one `(x, y, text)` per `page.insert_text` call. It uses a font that supports Romanian diacritics (PyMuPDF's built-in `"notos"`/`fitz.Font("notos")`, or `helv` if diacritics are avoided in the PDF fixtures).
  - `@dataclass Word` fields: `x0, y0, x1, y1: float`, `text: str`
  - `page_words(page: fitz.Page) -> list[Word]`
  - `rebuild_rows(words: list[Word], y_tolerance: float = 3.0, column_gap: float = 12.0) -> list[str]`: groups words by vertical centre within the tolerance, sorts each row by x, and joins with `" | "` where the gap exceeds `column_gap`, else with `" "`.
  - `pdf_lines(data: bytes, skip_first_page: bool = False) -> list[tuple[int, str]]`: returns `(page_number, line)` pairs, normalized. It drops lines equal to `Banking 1:1` and lines repeated on ≥ 50% of pages (page furniture).
  - `parse_fee_list(data: bytes) -> ParsedDocument` with `parser_name="fee_list"`. It skips the cover page. A section heading line must meet all of these:
    - matches `^\d+(\.\d+)*\.?\s+\S`
    - contains no `|`
    - is shorter than 120 chars
    - is **not** a value line: the remainder doesn't start with a number followed by `lei|euro|eur|usd|%|leu|intrări`, and the whole line doesn't match `^\d[\d.,]*\s*(lei|euro|eur|usd|%)`

    Depth 1 sets `section_path=[h]` and depth ≥ 2 sets `[h1, h]`. The first `|`-containing row after a heading whose last cell has no digit is the column header row, repeated on split pieces. Chunks are `fee_table`, with `page` set to the page the section starts on. Title: the first cover line containing `Tarife`.
  - `parse_general_terms(data: bytes) -> ParsedDocument` with `parser_name="general_terms"`. The algorithm follows spec §9 and the spike:
    - **Chapters:** `^(\d+)\.\s+([A-ZĂÂÎȘȚ][A-ZĂÂÎȘȚ ,\-]{5,})$`
    - **Sections:** `^(N\.\d+)\.?\s+(.*)$` within a chapter
    - **Section title:** text up to the first sub-clause number, capped at 90 chars
    - **Short sections:** a section of ≤ `MAX_TOKENS` is one `clause` chunk.
    - **Long sections:**
      - split at sub-clause numbers `(?<!\S)N\.M\.\d+\.?\s`, even mid-line
      - pack the sub-clauses up to `MAX_TOKENS`
      - window a single over-long clause by sentences (`(?<=[.;])\s+`) with a one-sentence overlap
    - **Section path:** `[f"{n}. {Chapter Title}", f"{n.m} {section title}"]`, where the chapter title is title-cased.
    - **Document title:** the first line of the PDF.

- [ ] **Step 1: Write failing tests**

All PDFs are built with `make_pdf` and synthetic text.

```python
def test_rebuild_rows_joins_columns():
    words = [Word(10, 100, 60, 108, "Comision"), Word(62, 100, 90, 108, "analiză"), Word(300, 101, 330, 109, "200"), Word(332, 101, 350, 109, "lei")]
    assert rebuild_rows(words) == ["Comision analiză | 200 lei"]

def test_fee_list_sections_and_value_lines():
    pdf = make_pdf([[(50, 80, "Tarife și comisioane Demo")],
                    [(50, 60, "1. Conturi demo"), (50, 80, "1.1. Cont curent demo"),
                     (50, 100, "Tip"), (300, 100, "Comision"),
                     (50, 120, "Deschidere cont"), (300, 120, "0 lei"),
                     (50, 140, "100 lei"),
                     (50, 160, "2. Plăți demo"), (50, 180, "Transfer"), (300, 180, "3 lei")]])
    doc = parse_fee_list(pdf)
    paths = [c.section_path for c in doc.chunks]
    assert paths == [["1. Conturi demo", "1.1. Cont curent demo"], ["2. Plăți demo"]]
    assert "Deschidere cont | 0 lei" in doc.chunks[0].text and "100 lei" in doc.chunks[0].text
    assert doc.chunks[0].kind is ChunkKind.fee_table and doc.chunks[0].page == 2

def test_fee_list_repeats_column_header_when_split():
    rows = [(50, 100, "Tip"), (300, 100, "Comision")] + [(50, 120 + i * 12, f"Operațiune demo numărul {i} cu descriere lungă") for i in range(50)]
    # add a value cell per row at x=300 ...
    doc = parse_fee_list(make_pdf([[(50, 80, "Tarife Demo")], [(50, 80, "1. Secțiune demo")] + rows]))
    assert len(doc.chunks) >= 2 and doc.chunks[1].text.startswith("Tip | Comision")

def test_general_terms_splits_by_numbering_including_flattened_subclauses():
    long = " ".join(f"5.1.{i} Clauza demo {i} " + "text demonstrativ. " * 40 for i in range(1, 6))
    text_lines = ["Conditii Generale Demo Editia 01.01.2026", "5. PREVEDERI DEMO CARDURI",
                  "5.1 Emiterea demo " + long, "5.2 Utilizatori demo Text scurt."]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))   # helper wraps lines onto pages
    s51 = [c for c in doc.chunks if c.section_path[1].startswith("5.1 ")]
    assert len(s51) >= 2 and all(c.kind is ChunkKind.clause for c in s51)
    assert doc.chunks[-1].section_path == ["5. Prevederi Demo Carduri", "5.2 Utilizatori demo Text scurt."]
    assert all(estimate_tokens(c.text) <= 600 for c in doc.chunks)
```

`make_pdf_from_lines(lines, per_page=40)` is a second helper in `pdf_builders.py`; it writes each line with text wrapping via `page.insert_textbox`. The implementer fills in the value cells in the split test.

- [ ] **Step 2: Run them and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_pdf_rows.py tests/unit/rag/test_fee_list_parser.py tests/unit/rag/test_general_terms_parser.py -v`.
- [ ] **Step 3: Implement `pdf_rows.py`, `fee_list.py` and `general_terms.py`, and register the two parsers in `parse_document`.**
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Smoke-check against the spike's real files (not committed).** Run:

```bash
.venv/Scripts/python -I -c "import sys;sys.path.insert(0,'.');from pathlib import Path;from src.services.document_ingestion.parsers.fee_list import parse_fee_list as f;d=f(Path.home().joinpath('rag-spike/input/fee-list.pdf').read_bytes());print(len(d.chunks),[c.section_path for c in d.chunks][:8])"
```

Expected: no section paths that look like values (`100 lei`, `30 EUR/intrare…`), and the first path is `['1. Conturi curente, de economii și alte operațiuni bancare', '1.1. Conturi curente']`. Do the same for `cgb.pdf` with `parse_general_terms`. Expected: about 250–280 chunks, every path starting with a chapter number.

- [ ] **Step 6: Commit.** Message: `agent(rag): PDF row rebuilding, fee list and general terms parsers`.

---

### Task 6: Cost sheet template parser and generic PDF parser

**Files:**
- Create: `src/services/document_ingestion/parsers/cost_sheet.py`, `src/services/document_ingestion/parsers/pdf_generic.py`
- Test: `tests/unit/rag/test_cost_sheet_parser.py`, `tests/unit/rag/test_pdf_generic_parser.py`

**Interfaces:**
- Consumes: `page_words`, `rebuild_rows`, `pdf_lines`, `Word`, `TemplateMismatch`, `make_pdf`.
- Produces:
  - `parse_cost_sheet(data: bytes) -> ParsedDocument` with `parser_name="cost_sheet"` (or `"cost_sheet_fallback"` with a warning). Output:
    - `cost_facts` chunk with `section_path=["Costuri complete", "Condiții și costuri"]`, containing:
      - the fact lines (`Tip credit:`, `Valuta:`, `Valoare:`, `Perioada maxima:`)
      - the benefits bullets
      - `Costuri credit:` followed by one line per variant: `Variantă: {tip produs} | Monedă/tip dobândă: {..} | Sumă credit: {..} | Rată dobândă: {..} | Comision analiză dosar: {..} | Comision administrare lunar: {..} | DAE: {..}`
      - footnotes
      - the line `Comision de plată anticipată: {value}`
    - `cost_examples` chunk with `section_path=["Costuri complete", "Exemple de calcul"]`, holding all text from the first `Exemplu de calcul` line onward. Rebuild it with `rebuild_rows`, then keep only the prose lines that start a sentence (`Pentru un credit` …) and the example titles.
    - Title: the first non-date line.
  - Variant-table algorithm (the tests don't fully pin this down):
    1. **Find the header band:** it runs from the word `Tip` (of `Tip produs`) down to the line before the first word that starts with the title's first word (e.g. `Flexicredit`) in the leftmost column.
    2. **Define columns:** cluster the header words by x-centre into ≥ 6 columns, using gaps > 15pt as boundaries. Column labels are the joined words in each cluster, top to bottom.
    3. **Assign words:** each body word (between the header band and the first footnote line, i.e. a line starting with a digit immediately followed by a letter, or with `*`) goes to the column whose x-range contains its centre, or else the nearest column.
    4. **Split variant rows:** a new row begins at each y where the leftmost column has a word equal to the title's first word. Each cell's words are joined in (y, x) order.
    5. **Validate:** ≥ 6 columns, ≥ 1 row, and every row's last column contains `%`. If any check fails, raise `TemplateMismatch`. `parse_cost_sheet` catches it and returns the fallback: one `generic` chunk of `rebuild_rows` text plus the warning `"cost sheet template mismatch: <reason>"`.
  - `Comision de plată anticipată`: find the line containing `plata anticipata` or `plată anticipată` (accent-insensitive). The value is the text in the same row band (±12pt) to the right of the label, joined across the band's lines.
  - `parse_pdf_generic(data: bytes) -> ParsedDocument` with `parser_name="pdf_generic"`:
    - Short documents: if the whole text is < 600 estimated tokens, the output is one `generic` chunk with `section_path=[]`.
    - Longer documents split on heading lines: lines matching `^\d+\.\s+\S` (< 120 chars), or spans whose font flags include bold (`flags & 16`) with line length < 100.
    - Each section is packed with `pack_lines`.
    - Title: the first line.

- [ ] **Step 1: Write failing tests**

The synthetic cost sheet is built with `make_pdf`. It mirrors the real layout:
- a date line, a title (`Demoflex Fara Asigurare`), facts, and benefits
- header words spread over 3 lines across 7 x-columns
- two variant rows whose cells span 2–3 lines and whose analysis and admin fees sit vertically centred
- footnotes
- the early-repayment label on the left, with its value split over two lines on the right
- one worked example

```python
def test_cost_sheet_variants_are_clean_rows():
    doc = parse_cost_sheet(build_demo_cost_sheet())
    facts = doc.chunks[0]
    assert facts.kind is ChunkKind.cost_facts and doc.parser_name == "cost_sheet"
    rows = [l for l in facts.text.splitlines() if l.startswith("Variantă:")]
    assert rows == [
        "Variantă: Demoflex Fara Asigurare, client standard | Monedă/tip dobândă: Lei Fixa | Sumă credit: Indiferent de suma | Rată dobândă: de la 6.10% la 15.20% | Comision analiză dosar: 150 lei | Comision administrare lunar: 4 lei | DAE: de la 9.80% la 21.40%",
        "Variantă: Demoflex Fara Asigurare, client premium | Monedă/tip dobândă: Lei Fixa | Sumă credit: Indiferent de suma | Rată dobândă: de la 5.90% la 15.00% | Comision analiză dosar: 150 lei | Comision administrare lunar: 4 lei | DAE: de la 9.50% la 21.10%",
    ]
    assert "Comision de plată anticipată: 0,50 % in ultimul an de contract / 1,00% inainte de inceperea ultimului an de contract" in facts.text

def test_cost_sheet_examples_chunk():
    ex = parse_cost_sheet(build_demo_cost_sheet()).chunks[1]
    assert ex.kind is ChunkKind.cost_examples and ex.text.startswith("Exemplu de calcul")

def test_cost_sheet_fallback_on_unknown_layout():
    doc = parse_cost_sheet(make_pdf([[(50, 60, "01.01.2026"), (50, 80, "Altceva complet diferit")]]))
    assert doc.parser_name == "cost_sheet_fallback" and doc.warnings and doc.chunks[0].kind is ChunkKind.generic

def test_pdf_generic_short_and_sectioned():
    short = parse_pdf_generic(make_pdf([[(50, 60, "Informare demo"), (50, 80, "Text scurt.")]]))
    assert len(short.chunks) == 1 and short.chunks[0].section_path == []
    long = parse_pdf_generic(make_pdf_from_lines(["Ghid demo"] + [f"{i}. Capitol demo {i}" if j == 0 else "text demonstrativ " * 30 for i in range(1, 5) for j in range(4)]))
    assert [c.section_path[0] for c in long.chunks][:2] == ["1. Capitol demo 1", "2. Capitol demo 2"]
```

`build_demo_cost_sheet()` goes in `tests/fixtures/rag/pdf_builders.py`, with the coordinates chosen by the implementer to reproduce the layout described above.

- [ ] **Step 2: Run them and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_cost_sheet_parser.py tests/unit/rag/test_pdf_generic_parser.py -v`.
- [ ] **Step 3: Implement both parsers and register them in `parse_document`.**
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Smoke-check on the real file** `~/rag-spike/input/cost-flexicredit.pdf` (same pattern as Task 5, Step 5). Expected:
  - `parser_name == "cost_sheet"`
  - two `Variantă:` lines containing `de la 5.55% la 14.95%` and `de la 5.35% la 14.75%`
  - the early repayment line present

  If it falls back, fix the column clustering before moving on.
- [ ] **Step 6: Commit.** Message: `agent(rag): cost sheet template parser and generic PDF parser`.

---

### Task 7: Embedding adapter and fake embedder

**Files:**
- Create: `src/integrations/llm/embeddings.py`, `tests/support/__init__.py`, `tests/support/fake_embedder.py`
- Test: `tests/unit/rag/test_embeddings.py`

**Interfaces:**
- Produces:
  - `class Embedder(Protocol)` members: `model_name: str`, `dimension: int`, `def embed_documents(self, texts: list[str]) -> list[list[float]]`, `def embed_query(self, text: str) -> list[float]`
  - `BgeM3Embedder(model_name: str = "BAAI/bge-m3", device: str = "cpu", batch_size: int = 16)`:
    - uses `dimension = 1024`
    - loads the `SentenceTransformer` lazily on first use, with `local_files_only=True` unless the env var `RAG_ALLOW_MODEL_DOWNLOAD=1` is set
    - encodes with `normalize_embeddings=True`
    - wraps any load failure as `EmbeddingModelUnavailable(f"embedding model {model_name} unavailable: {exc}")`
  - `HashingEmbedder(dimension: int = 1024)` (tests only):
    - tokens are accent-stripped lowercase `\w+`
    - each token adds 1.0 at `crc32(token) % dimension`
    - the vector is L2-normalized; an all-zero vector becomes `[1.0, 0, …]`
    - `model_name = "hashing-test"`

- [ ] **Step 1: Write failing tests**

```python
def test_hashing_embedder_is_deterministic_and_lexical():
    e = HashingEmbedder()
    a, b, c = e.embed_query("dobânda fixă"), e.embed_query("dobanda fixa"), e.embed_query("card de debit")
    cos = lambda x, y: sum(i * j for i, j in zip(x, y))
    assert len(a) == 1024 and cos(a, b) == pytest.approx(1.0) and cos(a, c) < 0.5

def test_bge_unavailable_raises_typed_error(monkeypatch):
    monkeypatch.delenv("RAG_ALLOW_MODEL_DOWNLOAD", raising=False)
    with pytest.raises(EmbeddingModelUnavailable):
        BgeM3Embedder(model_name="definitely/not-a-model").embed_query("x")
```

- [ ] **Step 2: Run them and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_embeddings.py -v`.
- [ ] **Step 3: Implement `embeddings.py` and `fake_embedder.py`.**
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Download the real model once (manual, ~2.3 GB).** Run:

```bash
RAG_ALLOW_MODEL_DOWNLOAD=1 .venv/Scripts/python -c "import sys;sys.path.insert(0,'.');from src.integrations.llm.embeddings import BgeM3Embedder as B;print(len(B().embed_query('Ce este DAE?')))"
```

Expected: `1024`.
- [ ] **Step 6: Commit.** Message: `agent(rag): local BGE-M3 embedding adapter`.

---

### Task 8: Document store, vector index repository and ingestion pipeline

**Files:**
- Create:
  - `src/services/document_ingestion/manifest.py`, `src/services/document_ingestion/pipeline.py`
  - `src/storage/document_store/raw_store.py`, `src/storage/document_store/repository.py`
  - `src/storage/vector_index/repository.py`
- Test: `tests/unit/rag/test_manifest.py`, `tests/integration/rag/test_pipeline.py`

**Interfaces:**
- Consumes:
  - `parse_document`, `classify_document`, `classify_topic`, `fee_section_products`
  - `canonical_key`, `extract_effective_date`, `extract_campaign_window`
  - `build_header`, `estimate_tokens`, `CHUNKER_VERSION`
  - `AUTHORITY_BY_DOC_KIND`, `Embedder`, `db_conn`, `HashingEmbedder`
  - `ChunkDraft.products_override` / `ChunkDraft.links` (Task 4)
- Produces:
  - `ManifestEntry` (pydantic) fields: `url: str`, `final_url: str`, `fetched_at: datetime`, `status_code: int | None`, `content_type: str | None`, `sitemap_lastmod: date | None`, `sha256: str | None`, `raw_path: str | None`, `error: str | None = None`, `index: bool = True`, `withdrawn: bool = False`
  - `read_manifest(path: Path) -> list[ManifestEntry]` and `write_manifest(path: Path, entries: list[ManifestEntry]) -> None` (JSON lines, whole-file rewrite)
  - `save_raw(raw_dir: Path, data: bytes, suffix: str) -> tuple[str, Path]`, which returns `(sha256, path)` with the file named `{sha256}{suffix}`, and `read_raw(path: Path) -> bytes`
  - `DocumentRepository(conn)` methods:
    - `upsert_document(canonical_key, source_url, title, doc_kind) -> int`: also sets `status='active'` and `last_seen_at=now()`
    - `find_version_by_hash(document_id, content_hash) -> int | None`
    - `create_version(document_id, NewVersion) -> int`
    - `mark_withdrawn(canonical_keys: Sequence[str]) -> int`
  - `NewVersion` (dataclass) fields: `content_hash`, `version_label: str | None`, `effective_from: date`, `effective_date_source: str`, `fetched_at: datetime`, `sitemap_lastmod: date | None`, `raw_path: str`, `campaign_valid_until: date | None`, `parser_name: str`, `parser_version: str`
  - `ChunkRecord` (dataclass) fields: `ordinal, kind, topic, products, authority, section_path, page, anchor, header, text, token_count, parent_section_key, embedding`
  - `insert_chunks(conn, version_id: int, records: list[ChunkRecord]) -> list[int]`: inserts in ordinal order, then sets `prev_chunk_id`/`next_chunk_id`.
  - `ChunkLinkRecord` (dataclass) fields: `target_canonical_key: str`, `anchor_text: str`, `link_kind: LinkKind`, `ordinal: int`
  - `insert_chunk_links(conn, chunk_id: int, links: list[ChunkLinkRecord]) -> None`: uses `ON CONFLICT (chunk_id, target_canonical_key) DO NOTHING`.
  - `IngestOutcome(StrEnum)`: `created`, `unchanged`, `failed`, `withdrawn`, `skipped`
  - `IngestReport` (pydantic) fields: `run_id: int`, `outcomes: dict[str, IngestOutcome]` (by URL), `errors: dict[str, str]`, `warnings: dict[str, list[str]]`
  - `IngestionPipeline(conn, embedder: Embedder, cfg: SourceConfig)` methods:
    - `ingest_entries(entries: list[ManifestEntry], raw_dir: Path) -> IngestReport`
    - `ingest_one(entry: ManifestEntry, data: bytes) -> tuple[IngestOutcome, list[str]]`
    - `rebuild(entries, raw_dir) -> IngestReport`: truncates the knowledge tables first; used when the chunker changes
- Pipeline rules:
  - `ingest_entries` inserts an `index_runs` row (`running`) and updates it at the end (`completed`, or `failed` if an exception escapes), with counts.
  - Entry handling:
    - `withdrawn=True` → `mark_withdrawn([canonical_key(url)])` → `withdrawn`
    - `index=False`, or no `raw_path`, or status ≠ 200 → `skipped`
  - `ingest_one` does the following:
    - classifies and parses (`parse_document(doc_kind, data, entry.final_url, cfg)`)
    - **no chunks → `failed` with "no extractable content", and nothing is written**
    - derives metadata
    - runs inside `with conn.transaction():`
      - upsert document
      - same hash → `unchanged`
      - else create version
      - build records:
        - topic via `classify_topic`
        - products: `chunk.products_override`, else (fee list) `fee_section_products`, else the document's products
        - `parent_section_key=" › ".join(section_path[:2])`
      - embed `header + "\n" + text` in one `embed_documents` call
      - insert chunks, then each chunk's links via `insert_chunk_links`, with `target_canonical_key=canonical_key(link.target_url)` and ordinals in extraction order
    - any exception → rollback → `failed` with `str(exc)`
  - `version_label`: the effective date as ISO, plus the source (e.g. `"2026-09-01 (document_text)"`).

- [ ] **Step 1: Write failing tests**

These use `db_conn`, `HashingEmbedder` and synthetic fixture bytes from Tasks 4–6.

```python
def entry(url, sha="h1", **kw):  # helper building a 200 ManifestEntry with raw_path
    ...

def test_ingest_creates_document_version_and_chunks(db_conn, tmp_path):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    out, _ = p.ingest_one(entry(PRODUCT_URL), PRODUCT_HTML)
    assert out is IngestOutcome.created
    n, = db_conn.execute("select count(*) from knowledge_chunks").fetchone()
    hdr, = db_conn.execute("select header from knowledge_chunks order by ordinal limit 1").fetchone()
    assert n > 3 and hdr.startswith("Raiffeisen Bank › ")
    prev_null, = db_conn.execute("select count(*) from knowledge_chunks where prev_chunk_id is null").fetchone()
    assert prev_null == 1

def test_reingest_same_content_is_unchanged(db_conn): ...  # second ingest_one -> unchanged, still 1 version

def test_alias_and_dated_pdf_share_one_version(db_conn):
    # same bytes under ".../tarife-demo.sv.pdf" and ".../tarife-demo/20260901-x.pdf.coredownload.pdf"
    assert outcomes == [IngestOutcome.created, IngestOutcome.unchanged]
    assert db_conn.execute("select count(*) from knowledge_document_versions").fetchone()[0] == 1

def test_changed_content_adds_version_with_effective_dates(db_conn):
    # fee-list fixture dated "1 septembrie 2026", then a variant dated "1 noiembrie 2026"
    rows = db_conn.execute("select effective_from from knowledge_document_versions order by effective_from").fetchall()
    assert [r[0] for r in rows] == [date(2026, 9, 1), date(2026, 11, 1)]

def test_document_without_chunks_writes_nothing(db_conn):
    out, msgs = p.ingest_one(entry(PDF_URL), make_pdf([[]]))
    assert out is IngestOutcome.failed and "no extractable content" in msgs[0]
    assert db_conn.execute("select count(*) from knowledge_documents").fetchone()[0] == 0

def test_failed_ingest_rolls_back(db_conn):
    class Boom(HashingEmbedder):
        def embed_documents(self, texts): raise RuntimeError("boom")
    # ingest good v1 with HashingEmbedder, then changed v2 with Boom
    assert out is IngestOutcome.failed
    assert db_conn.execute("select count(*) from knowledge_document_versions").fetchone()[0] == 1

def test_withdrawn_entry_marks_document(db_conn): ...  # status becomes 'withdrawn'

def test_hub_cards_and_links_stored(db_conn):
    p.ingest_one(entry(HUB_URL), HUB_HTML)        # category_hub.html fixture from Task 4
    rows = db_conn.execute("select c.kind, c.products, c.authority from knowledge_chunks c where c.kind = 'hub_card' order by c.ordinal").fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [("hub_card", ["personal_loan"], "low"), ("hub_card", ["overdraft"], "low")]
    keys = [r[0] for r in db_conn.execute("select target_canonical_key from knowledge_chunk_links order by chunk_id, ordinal")]
    assert "/ro/persoane-fizice/produsele-noastre/credite/overdraft.html" in keys
    assert not any("/carduri/" in k for k in keys)

def test_ingest_entries_records_index_run(db_conn, tmp_path):
    rep = p.ingest_entries([...], tmp_path)
    status, model, chunker = db_conn.execute("select status, embedding_model, chunker_version from index_runs where id=%s", (rep.run_id,)).fetchone()
    assert (status, model, chunker) == ("completed", "hashing-test", CHUNKER_VERSION)

def test_campaign_window_stored_on_version(db_conn):
    # product fixture containing "Perioada campaniei: 15.10 - 26.11.2026"
    assert db_conn.execute("select campaign_valid_until from knowledge_document_versions").fetchone()[0] == date(2026, 11, 26)
```

`tests/unit/rag/test_manifest.py` checks the write→read round trip with defaults (`index=True`, `withdrawn=False`). Add a `Perioada campaniei: 15.10 - 26.11.2026.` paragraph to `product_page.html` for the campaign test.

- [ ] **Step 2: Run them and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_manifest.py tests/integration/rag/test_pipeline.py -v`.
- [ ] **Step 3: Implement `manifest.py`, `raw_store.py`, `document_store/repository.py`, `vector_index/repository.py` (insert part) and `pipeline.py`.** Register the pgvector adapter with `pgvector.psycopg.register_vector(conn)`.
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Commit.** Message: `agent(rag): versioned ingestion pipeline with document store and vector index`.

---

### Task 9: Retrieval service

**Files:**
- Create: `src/services/retrieval/ranking.py`, `src/services/retrieval/service.py`
- Modify: `src/storage/vector_index/repository.py` (add query functions)
- Test: `tests/unit/rag/test_ranking.py`, `tests/integration/rag/test_retrieval.py`

**Interfaces:**
- Consumes: all of Task 2's models, `RagSettings`, `Embedder`, `IngestionPipeline` (test setup), and the errors.
- Produces:
  - Vector index query functions, all filtered by `CandidateFilters`:
    - `@dataclass CandidateFilters` fields: `as_of: date`, `topics: list[Topic]`, `products: list[Product] | None`, `doc_kinds: list[DocKind] | None`, `include_superseded: bool`, `include_withdrawn: bool`
    - `@dataclass Candidate` fields: `chunk_id: int`, `score: float`
    - `dense_candidates(conn, embedding: list[float], f: CandidateFilters, limit: int) -> list[Candidate]` (score = `1 - (embedding <=> q)`)
    - `keyword_candidates(conn, terms: list[str], f, limit) -> list[Candidate]`: score = `ts_rank_cd(tsv, q, 32)`, where `q = to_tsquery('ro_unaccent', ' | '.join(terms))`; terms are passed as a bound parameter and returns `[]` if `terms` is empty
    - `dense_scores_for(conn, embedding, chunk_ids: list[int]) -> dict[int, float]`
    - `fetch_passage_rows(conn, chunk_ids, as_of: date) -> dict[int, PassageRow]`
    - `fetch_neighbor_texts(conn, chunk_ids) -> dict[int, tuple[str | None, str | None]]`
    - `latest_index_info(conn) -> IndexInfo | None`
    - `fetch_related_links(conn, chunk_ids: list[int], as_of: date) -> dict[int, list[RelatedLink]]`: joins `knowledge_chunk_links` to `knowledge_documents` on `canonical_key`. Spec §9a: it keeps only targets with `status = 'active'` that have a version with `effective_from <= as_of`. `title` is the document title, falling back to `anchor_text` if the title is empty. `url` is the document's `source_url`. Ordered by link `ordinal`.
  - "In force" SQL. Use this exact semantics as a CTE `in_force`: per document, the version with the greatest `(effective_from, ingested_at)` among versions with `effective_from <= %(as_of)s`. Filters behave as follows:
    - Without `include_superseded`, only `in_force` versions are searched. With it, every version with `effective_from <= as_of` is searched, so future-dated versions stay excluded either way.
    - Without `include_withdrawn`, `d.status = 'active'` is required.
    - `topic = ANY`, `products && %(products)s` when given, and `doc_kind = ANY` when given.
  - `PassageRow` (dataclass): every `Passage`/`Citation` field source (including the chunk `kind`), plus `in_force: bool`, `withdrawn: bool`, `campaign_valid_until`.
  - Pure functions in `ranking.py`:
    - `query_terms(text: str) -> list[str]`: accent-stripped lowercase `\w{2,}` tokens minus `RO_STOPWORDS`, deduplicated, in order. `RO_STOPWORDS` = `și si sau de la în in pe cu un o ce care este sunt pentru din mi îmi imi pot am ai a al ale lui să sa nu da cum cât cat dacă daca mai există exista trebuie fi se eu tu meu mea vreau vrea`.
    - `rrf_fuse(dense: list[Candidate], keyword: list[Candidate], k: int) -> dict[int, float]` (sum of `1/(k + rank)`, rank starting at 1)
    - `apply_authority(fused: dict[int, float], authority: dict[int, Authority], weights: Mapping[str, float]) -> dict[int, float]`
    - `passes_evidence_threshold(best_dense: float | None, best_keyword: float | None, keyword_top_dense: float | None, s: RagSettings) -> bool` is true if either holds:
      - `best_dense >= s.dense_floor`
      - `best_keyword >= s.keyword_floor` and `keyword_top_dense >= s.secondary_dense_floor`
    - `dedupe_passages(passages: list[Passage]) -> list[Passage]`: compares accent-stripped, lowercase, whitespace-collapsed text and keeps the first occurrence (the highest fused score).
    - `passage_flags(row: PassageRow, as_of: date) -> tuple[list[PassageFlag], list[str]]`. Flags and warnings, with exact warning strings:
      - `superseded` if not `in_force`
      - `withdrawn`
      - `low_authority` if authority is low
      - `teaser_figure` if the chunk kind is `hub_card`
      - `campaign_active` if `campaign_valid_until >= as_of`, with warning `f"This page advertises a time-limited campaign running until {d:%Y-%m-%d}."`
      - `campaign_ended` if `campaign_valid_until < as_of`, with warning `f"This page advertised a campaign that ended on {d:%Y-%m-%d}; its figures may be out of date until the page is re-fetched."`
    - `apply_hub_deferral(passages: list[Passage]) -> None`: for each passage flagged `teaser_figure`, find the highest-ranked passage in the same list that has `doc_kind == cost_sheet`, is not `superseded`, and shares a product other than `general`. If found, set `defer_to` to its `chunk_id` and append the warning `f"Teaser figure; the cost sheet passage {chunk_id} holds the authoritative rates and fees."` Hub/cost-sheet pairs never produce conflicts, because `detect_conflicts` groups by `doc_kind`.
    - `detect_conflicts(passages: list[Passage]) -> list[Conflict]`: only considers passages without `superseded`. Groups by `(doc_kind, topic, product)` for each product except `general`. Emits one `Conflict` per group with ≥ 2 distinct `document_id`s, listing chunk ids and each passage's `citation.effective_date`.
  - `RetrievalService(connect: Callable[[], psycopg.Connection], embedder: Embedder, settings: RagSettings)`, with `search(query: SearchQuery) -> SearchResult`. Its steps:
    1. embed the query; any exception becomes `EmbeddingModelUnavailable`
    2. open the connection and run the queries; `psycopg.OperationalError` becomes `KnowledgeStoreUnavailable`
    3. get `dense` and `keyword` candidates (`settings.candidate_k` each)
    4. run the threshold check; on failure return `SearchResult(status=insufficient_evidence, index_info=...)`
    5. fuse, apply authority, sort
    6. fetch rows for the top `3 * top_k`, build passages, dedupe, take `top_k`
    7. set flags and warnings, then `apply_hub_deferral`
    8. detect conflicts
    9. expand context if requested
    10. attach `related_links` via `fetch_related_links` (these never affect ranking or the threshold)
    11. return `ok` with `index_info`

- [ ] **Step 1: Write failing unit tests** in `test_ranking.py`:

```python
def test_query_terms_strip_stopwords_and_accents():
    assert query_terms("Există comision de rambursare anticipată?") == ["comision", "rambursare", "anticipata"]
    assert query_terms("& | ! : * ( ) '") == []

def test_rrf_fuse():
    f = rrf_fuse([Candidate(1, .9), Candidate(2, .8)], [Candidate(2, .5), Candidate(3, .4)], k=60)
    assert f[2] == pytest.approx(1/62 + 1/61) and max(f, key=f.get) == 2

def test_threshold():
    s = RagSettings()
    assert passes_evidence_threshold(0.60, None, None, s)
    assert not passes_evidence_threshold(0.30, 0.50, 0.20, s)       # generic keyword hit only
    assert passes_evidence_threshold(0.45, 0.20, 0.45, s)
    assert not passes_evidence_threshold(None, None, None, s)

def test_campaign_flags():
    flags, warns = passage_flags(row(campaign_valid_until=date(2026, 11, 26)), date(2026, 12, 1))
    assert PassageFlag.campaign_ended in flags
    assert warns == ["This page advertised a campaign that ended on 2026-11-26; its figures may be out of date until the page is re-fetched."]

def test_conflicts_only_same_kind_topic_specific_product():
    a = passage(doc=1, kind=DocKind.cost_sheet, topic=Topic.costs_fees, products=[Product.personal_loan])
    b = passage(doc=2, kind=DocKind.cost_sheet, topic=Topic.costs_fees, products=[Product.personal_loan])
    c = passage(doc=3, kind=DocKind.product_page, topic=Topic.costs_fees, products=[Product.personal_loan])
    g = passage(doc=4, kind=DocKind.cost_sheet, topic=Topic.costs_fees, products=[Product.general])
    cs = detect_conflicts([a, b, c, g])
    assert len(cs) == 1 and cs[0].product is Product.personal_loan and sorted(cs[0].chunk_ids) == [a.chunk_id, b.chunk_id]

def test_teaser_flag_and_hub_deferral():
    card = passage(1, doc=1, kind=DocKind.category_hub, chunk_kind=ChunkKind.hub_card, products=[Product.personal_loan])
    card.flags, card.warnings = passage_flags(row(kind=ChunkKind.hub_card, authority=Authority.low), date(2026, 10, 28))
    sheet = passage(7, doc=2, kind=DocKind.cost_sheet, chunk_kind=ChunkKind.cost_facts, products=[Product.personal_loan])
    other = passage(8, doc=3, kind=DocKind.cost_sheet, chunk_kind=ChunkKind.cost_facts, products=[Product.overdraft])
    apply_hub_deferral([card, other, sheet])
    assert PassageFlag.teaser_figure in card.flags and PassageFlag.low_authority in card.flags
    assert card.defer_to == 7
    assert card.warnings[-1] == "Teaser figure; the cost sheet passage 7 holds the authoritative rates and fees."
    assert detect_conflicts([card, sheet]) == []

def test_dedupe_keeps_first():
    assert [p.chunk_id for p in dedupe_passages([passage(1, text="Dobânda fixă"), passage(2, text="dobanda  fixa")])] == [1]
```

The `row()`/`passage()` builders are test helpers with sensible defaults. The `passage()` signature is `passage(chunk_id: int | None = None, *, doc: int = 1, kind: DocKind = DocKind.product_page, chunk_kind: ChunkKind = ChunkKind.section, topic: Topic = Topic.costs_fees, products: list[Product] = [Product.personal_loan], text: str = "t")`, with auto-incrementing ids when `chunk_id` is `None`. `row()` takes `PassageRow` field overrides.

- [ ] **Step 2: Write failing integration tests** in `test_retrieval.py`. Ingest these synthetic fixtures with `HashingEmbedder`:
- the product page at `PAGE_URL` (Task 4)
- the FAQ page
- the category hub at `HUB_URL`
- the demo cost sheet at a `/costuri/costuri-complete-flexicredit-demo/20261015-x.pdf` URL, so its product is `personal_loan`
- fee list v1 (`1 septembrie 2026`) and v2 (`1 noiembrie 2026`, a different fee value)

`overdraft.html` is deliberately not ingested.

```python
def test_search_returns_cited_passages(service):
    r = service.search(SearchQuery(text="comision analiză dosar Demoflex", as_of=date(2026, 10, 28)))
    assert r.status is SearchStatus.ok and r.passages
    top = r.passages[0]
    assert top.citation.publisher == "Raiffeisen Bank Romania" and top.citation.url.startswith("https://")
    assert top.header.startswith("Raiffeisen Bank › ") and r.content_trust == "untrusted_evidence"

def test_unaccented_query_matches(service):
    assert service.search(SearchQuery(text="dobanda fixa Demoflex", as_of=D)).status is SearchStatus.ok

def test_version_in_force_by_effective_date(service):
    before = service.search(SearchQuery(text="<v1-only fee phrase>", topics=list(Topic), as_of=date(2026, 10, 1)))
    after = service.search(SearchQuery(text="<v2-only fee phrase>", topics=list(Topic), as_of=date(2026, 11, 15)))
    # before: only v1 texts appear; after: only v2 texts appear; include_superseded on the later date returns v1 flagged superseded
    ...

def test_future_dated_version_excluded(service): ...   # as_of 2026-10-01 never returns v2 even with include_superseded

def test_default_scope_excludes_non_credit_topics(service):
    r = service.search(SearchQuery(text="deschidere cont curent demo", as_of=D))
    assert all(p.topic in CREDIT_TOPICS for p in r.passages)

def test_unrelated_query_is_insufficient_evidence(service):
    assert service.search(SearchQuery(text="rețetă de clătite cu ciocolată", as_of=D)).status is SearchStatus.insufficient_evidence

def test_query_with_tsquery_operators_is_safe(service):
    service.search(SearchQuery(text="DAE & (comision | 'dobândă') :* !", as_of=D))   # no exception

def test_campaign_flag_after_end(service):
    r = service.search(SearchQuery(text="<product page phrase>", as_of=date(2026, 12, 1)))
    assert any(PassageFlag.campaign_ended in p.flags for p in r.passages)

def test_withdrawn_excluded_by_default(service, db_conn): ...

def test_related_links_resolve_only_to_indexed_active_targets(service, db_conn):
    r = service.search(SearchQuery(text="Credit Demo fără ipotecă Aplici ușor", doc_kinds=[DocKind.category_hub], as_of=D))
    cards = {p.text.splitlines()[0]: p for p in r.passages if p.kind is ChunkKind.hub_card}
    assert [l.url for l in cards["Credit Demo fără ipotecă"].related_links] == [PAGE_URL]
    assert cards["Credit Demo fără ipotecă"].related_links[0].link_kind is LinkKind.card
    assert cards.get("Overdraft Demo") is None or cards["Overdraft Demo"].related_links == []   # target not indexed
    DocumentRepository(db_conn).mark_withdrawn([canonical_key(PAGE_URL)]); db_conn.commit()
    r2 = service.search(SearchQuery(text="Credit Demo fără ipotecă Aplici ușor", doc_kinds=[DocKind.category_hub], as_of=D))
    assert all(not p.related_links for p in r2.passages if p.kind is ChunkKind.hub_card)

def test_hub_card_defers_to_cost_sheet(service):
    r = service.search(SearchQuery(text="Dobândă de la 6,10% Demoflex comision analiză", products=[Product.personal_loan], top_k=10, as_of=D))
    card = next(p for p in r.passages if p.kind is ChunkKind.hub_card)
    sheet = next(p for p in r.passages if p.doc_kind is DocKind.cost_sheet)
    assert PassageFlag.teaser_figure in card.flags and card.defer_to == sheet.chunk_id
    assert not any(c.doc_kind is DocKind.category_hub for c in r.conflicts)

def test_expand_context(service):
    r = service.search(SearchQuery(text="<phrase in a middle chunk>", as_of=D, expand_context=True))
    assert r.passages[0].context and (r.passages[0].context.previous or r.passages[0].context.next)

def test_search_raises_typed_errors(settings):
    class Broken(HashingEmbedder):
        def embed_query(self, t): raise RuntimeError("x")
    with pytest.raises(EmbeddingModelUnavailable):
        RetrievalService(lambda: psycopg.connect(TEST_URL), Broken(), settings).search(SearchQuery(text="dae"))
    with pytest.raises(KnowledgeStoreUnavailable):
        RetrievalService(lambda: psycopg.connect("postgresql://rag:rag@127.0.0.1:1/none", connect_timeout=2), HashingEmbedder(), settings).search(SearchQuery(text="dae"))
```

The integration `settings` fixture lowers the floors to suit `HashingEmbedder`: `dense_floor=0.35`, `secondary_dense_floor=0.2`, `keyword_floor=0.05`. The real floors are calibrated in Task 11. Placeholders `<…>` are phrases the implementer picks from their own fixtures.

- [ ] **Step 3: Run them and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_ranking.py tests/integration/rag/test_retrieval.py -v`.
- [ ] **Step 4: Implement the repository query functions, `ranking.py` and `service.py`.**
- [ ] **Step 5: Run the full suite and confirm it passes.** Run: `.venv/Scripts/python -m pytest -v`.
- [ ] **Step 6: Commit.** Message: `agent(rag): hybrid retrieval service with citations, versions, hub deferral and read-more links`.

---

### Task 10: Scraper

**Files:**
- Create: `src/services/document_ingestion/scraper.py`
- Test: `tests/unit/rag/test_scraper.py`

**Interfaces:**
- Consumes: `SourceConfig`, `ManifestEntry`, `save_raw`.
- Produces:
  - `ScrapeReport` (pydantic) fields: `entries: list[ManifestEntry]`, `new: list[str]`, `changed: list[str]`, `unchanged: list[str]`, `failed: dict[str, str]`, `withdrawn: list[str]`, `completed: bool`
  - `Scraper(client: httpx.Client, cfg: SourceConfig, raw_dir: Path, min_interval_s: float = 2.0, max_retries: int = 3, sleep: Callable[[float], None] = time.sleep, now: Callable[[], float] = time.monotonic)`, with `run(previous: list[ManifestEntry]) -> ScrapeReport`. The client is created by the caller with `timeout=30` and the User-Agent from Global Constraints.
- Behaviour:
  1. **Robots:** fetch `https://www.raiffeisen.ro/robots.txt` and parse it with `urllib.robotparser`. Disallowed URLs are never fetched.
  2. **Discovery:**
     - From the sitemap (`<url><loc>`, `<lastmod>` as a date), keep the URLs matching `page_allow`.
     - Add `extra_urls` and `discovery_seeds` (the latter with `index=False`).
     - From every fetched HTML page, collect `<a href>` links whose absolute URL contains `.pdf` and matches `pdf_allow`.
     - Each URL is fetched at most once per run.
  3. **Politeness:** wait so consecutive requests start ≥ `min_interval_s` apart (use the injected `now`/`sleep`).
  4. **Fetching and retries:** retry `httpx.TimeoutException`, `httpx.TransportError` and 5xx, up to `max_retries` times, with backoff `sleep(2 ** attempt)` (attempt starts at 1).
     - A 200 saves the raw file with suffix `.pdf` if the content type or URL indicates PDF, else `.html`.
     - A 404/410 is recorded without retrying.
     - Anything else, including exhausted retries, goes into `failed`.
  5. **Classification:** compare against `previous` by URL; the same `sha256` is `unchanged`.
  6. **Withdrawal:** for each previous URL with `index=True` that wasn't discovered this run, fetch it. A 404/410 makes it a withdrawal candidate.
     - `completed = len(failed) / max(1, attempted) < 0.10`.
     - Only if `completed` do the candidates get `withdrawn=True` entries and appear in `withdrawn`. Otherwise their previous entries are carried over unchanged.

- [ ] **Step 1: Write failing tests** using `httpx.MockTransport` with routes for robots, the sitemap (3 URLs, 1 disallowed by robots, 1 not allowlisted), a page linking 2 PDFs (1 allowlisted), and the PDF.

```python
def test_discovers_pages_and_allowlisted_pdfs(tmp_path): ...     # entries == {page, pdf}; disallowed never requested
def test_rate_limit_spacing(tmp_path): ...                       # recorded sleep calls keep starts >= 2.0 s apart (fake clock)
def test_retries_then_succeeds_on_timeout(tmp_path): ...         # route raises TimeoutException twice then 200 -> new; sleeps include 2 and 4
def test_unchanged_by_hash(tmp_path): ...                        # second run with previous -> unchanged
def test_withdrawn_only_when_run_completed(tmp_path):
    # previous has old.pdf; not discovered; returns 404 -> withdrawn
    # variant: 2 of 5 URLs time out repeatedly -> completed False, withdrawn == [], old entry carried over
    ...
def test_404_not_retried(tmp_path): ...
```

- [ ] **Step 2: Run them and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/unit/rag/test_scraper.py -v`.
- [ ] **Step 3: Implement `scraper.py`.**
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Commit.** Message: `agent(rag): polite incremental scraper with withdrawal detection`.

---

### Task 11: CLIs, evaluation, real-corpus run and documentation

**Files:**
- Create:
  - `scripts/rag/__init__.py`, `scripts/rag/scrape.py`, `scripts/rag/ingest.py`, `scripts/rag/search.py`, `scripts/rag/evaluate.py`
  - `src/services/retrieval/evaluation.py`, `config/rag/eval_questions.yaml`
  - `docs/runbooks/rag-local.md`, `docs/decisions/0001-local-rag-pgvector.md`
  - `.agents/messages/20261028-HHMM-rag-to-orchestrator.md`
- Modify: `config/rag/sources.yaml` (allowlist fixes found during the real run), `.env.example` (calibrated floors), `.agents/BOARD.md`, `.agents/log.md`, `README.md` (one "Local knowledge base" pointer to the runbook)
- Test: `tests/unit/rag/test_evaluation.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `ExpectedSource` (pydantic) fields: `canonical_key: str`, `section_prefix: str | None = None`
  - `EvalQuestion` (pydantic) fields: `id: str`, `question: str`, `answerable: bool = True`, `expected: list[ExpectedSource] = []`, `products: list[Product] | None = None`
  - `EvalReport` (pydantic) fields: `recall_at_k: float`, `mrr: float`, `refusals_correct: int`, `refusals_total: int`, `per_question: list[dict]`
  - `evaluate(search: Callable[[SearchQuery], SearchResult], questions: list[EvalQuestion], k: int = 5, as_of: date | None = None) -> EvalReport`:
    - Answerable questions: a hit is the first passage among the top k whose `canonical_key(citation.url)` equals an expected key and whose `" › ".join(section_path)` starts with `section_prefix` when one is given.
    - `recall_at_k` is the share of answerable questions with a hit.
    - `mrr` is the mean of `1/rank`, with 0 for misses.
    - Unanswerable questions are correct when `status == insufficient_evidence`.
  - CLIs (argparse; each loads `RagSettings`):
    - `scrape.py [--manifest PATH]`: runs `Scraper`, writes the manifest, and prints the report counts.
    - `ingest.py [--rebuild]`: reads the manifest, runs the pipeline, and prints outcome counts, warnings and errors.
    - `search.py "question" [--top-k N] [--as-of YYYY-MM-DD] [--all-topics]`: prints each passage's header, scores, flags, warnings, URL and the first 300 chars, followed by any conflicts.
    - `evaluate.py [--k 5]`: prints a per-question table and totals. It exits non-zero if `recall_at_k < 0.8` or `refusals_correct < 4`.

- [ ] **Step 1: Write a failing unit test** for `evaluate` with a fake `search` function:

```python
def test_evaluate_metrics():
    qs = [EvalQuestion(id="a", question="q1", expected=[ExpectedSource(canonical_key="/ro/x.html")]),
          EvalQuestion(id="b", question="q2", expected=[ExpectedSource(canonical_key="/ro/y.html")]),
          EvalQuestion(id="c", question="q3", answerable=False)]
    # fake search: q1 -> /ro/x.html at rank 2; q2 -> no hit; q3 -> insufficient_evidence
    rep = evaluate(fake_search, qs, k=5)
    assert rep.recall_at_k == 0.5 and rep.mrr == pytest.approx(0.25) and (rep.refusals_correct, rep.refusals_total) == (1, 1)
```

- [ ] **Step 2: Run it and confirm it fails, then implement `evaluation.py` and the four CLIs. Run it again and confirm it passes.**
- [ ] **Step 3: Scrape the real corpus.** Run: `.venv/Scripts/python scripts/rag/scrape.py`. Expected:
  - roughly 60–90 pages and 20–30 PDFs
  - `failed` < 10%
  - files under `data/local/rag/raw/`
  - `git status` shows nothing under `data/local/`

  If credit pages or PDFs listed in spec §5 are missing (8 cost sheets, fee list, CGB, IRCC explainer, repayment methods, documents list, restructuring page, the category hubs), adjust `sources.yaml` and run it again. Add any further hub URLs found in the sitemap (spec §16 leaves the hub list to the builder) to `category_hubs`.
- [ ] **Step 4: Ingest the real corpus.** Run: `.venv/Scripts/python scripts/rag/ingest.py`. Expected:
  - every PDF and page is either `created` or explains why it isn't
  - all 8 cost sheets use `parser_name = 'cost_sheet'`; check with `select parser_name, count(*) from knowledge_document_versions group by 1`
  - every hub uses `parser_name = 'category_hub'`
  - `select count(*) from knowledge_chunk_links l where l.target_canonical_key like '%/carduri/%' and l.link_kind = 'teaser'` returns 0
  - `search.py "credit de nevoi personale fara ipoteca"` shows `related_links` on hub card passages
  - fix parser issues before continuing
- [ ] **Step 5: Write `config/rag/eval_questions.yaml`.** It needs 30–40 Romanian questions, as in spec §13: questions plus expected `canonical_key`s and optional section prefixes, no Raiffeisen text. It must include at least:
  - "Ce acte îmi trebuie pentru un credit de nevoi personale?"
  - "Există comision de rambursare anticipată la Flexicredit?"
  - "Ce este IRCC?"
  - "Până la ce vârstă pot lua un credit de nevoi personale?"
  - "Care este DAE pentru Casa Ta cu dobândă fixă 5 ani?"
  - "Ce pot face dacă nu mai pot plăti ratele?"
  - "Pot alege rate descrescătoare?"
  - "Ce documente trebuie pentru un credit ipotecar?"
  - "Pot refinanța un credit de la altă bancă?"
  - "Ce este darea în plată?"
  - "Ce tipuri de credite de nevoi personale aveți?" (expects the hub page `/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale.html`)
  - 5 unanswerable questions: "Cât costă un leasing auto pentru persoane fizice?", "Care este cursul euro azi?", "Pot deschide un depozit în franci elvețieni?", "Ce dobândă are creditul pentru studenți în Germania?", "Cum îmi schimb parola la Netflix?"
- [ ] **Step 6: Calibrate and evaluate.** Run: `.venv/Scripts/python scripts/rag/evaluate.py`.
  - Adjust `RAG_DENSE_FLOOR`, `RAG_KEYWORD_FLOOR`, `RAG_SECONDARY_DENSE_FLOOR` and the authority weights. If needed, restructure `passes_evidence_threshold`; spec §12.4 allows this as long as the Task 9 unit tests are updated to match.
  - Iterate until `recall@5 ≥ 0.8` and `refusals ≥ 4/5`.
  - Write the final values into `.env.example`, and into the `RagSettings` defaults so they hold without a `.env`.
  - Expected: exit code 0.
- [ ] **Step 7: Write the documentation.**
  - `docs/runbooks/rag-local.md`:
    - start the DB
    - one-time model download
    - scrape → ingest → search → evaluate commands
    - `--rebuild` after chunker changes
    - the legal note: local only, never commit `data/local`, do not deploy publicly
    - troubleshooting: Docker not running → `KnowledgeStoreUnavailable`; model missing → `EmbeddingModelUnavailable`
  - `docs/decisions/0001-local-rag-pgvector.md`:
    - context, the decision (approach A, BGE-M3, hybrid RRF), the alternatives (B, C) and the consequences
    - link to the spec
  - `README.md`: one line pointing to the runbook.
- [ ] **Step 8: Run the full test suite.** Run: `.venv/Scripts/python -m pytest -v`. Expected: all pass, with none of the integration tests skipped while the database is running.
- [ ] **Step 9: Coordination files and final commit.**
  - In `.agents/BOARD.md`, set `RAG-01` → `DONE`.
  - Append `[2026-10-28 HH:MM] [Claude] Local RAG retrieval implemented; eval recall@5=<x>, refusals <n>/5.` to `.agents/log.md`.
  - Write the handoff message to the orchestrator role, covering:
    - entry point `RetrievalService.search(SearchQuery)`
    - `related_links` to offer as "read more"
    - `defer_to`/`teaser_figure`: quote rates from the cost sheet, not hub cards
    - `src/models/knowledge.py`
    - flags and warnings to surface to users
    - `content_trust`
    - that answers must cite `citation.url` and attribute Raiffeisen Bank
  - Commit with the message `agent(rag): CLIs, evaluation set, runbook and calibrated thresholds`, with `- Next: @orchestrator -> wrap RetrievalService as search_banking_policies tool`.
