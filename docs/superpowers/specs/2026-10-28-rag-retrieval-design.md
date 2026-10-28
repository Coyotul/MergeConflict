# Local RAG retrieval over Raiffeisen public credit documentation — design

Date: 2026-10-28 · Status: draft for approval · Spec reference: SPECIFICATION.md §8, §15, §16

## 1. Intent

Give the platform a working knowledge base for credit questions, built from
Raiffeisen Bank Romania's real, public credit documentation, so that the future
AI orchestrator can answer policy and product questions with grounded,
cited evidence ("according to Raiffeisen Bank's published conditions …").

Everything on the retrieval side runs on the developer's machine: the database,
the vector and keyword indexes, and the embedding model. The answer-writing LLM
(Featherless AI, via `src/integrations/llm/`) is **not** part of this work. It
belongs to the orchestrator, which will call this service through the
`search_banking_policies` tool (spec §7).

## 2. Goals, non-goals, anti-goals

**Goals**
- Collect Raiffeisen's public credit material (HTML pages and PDFs) with a
  re-runnable, polite scraper.
- Ingest it through a pipeline matching spec §8: extract → clean/normalize →
  structure-aware chunking → metadata → local embeddings → index.
- Provide a retrieval-only Python service. It returns ranked passages, each
  with a full citation (URL, title, page/section, version, effective date, fetch date).
- Track document versions: superseded versions and ended campaigns are
  identified, never silently mixed with current material.
- Return an explicit "insufficient evidence" result instead of loosely
  related passages.
- Provide a committed evaluation question set and a script that measures
  retrieval quality, so changes to chunking or models can be judged.

**Non-goals (this piece of work)**
- Answer generation, prompts, Featherless integration, orchestrator.
- A FastAPI endpoint (the service will be wrapped later).
- Admin document upload UI (spec §3.3). The pipeline accepts local files, so
  upload can reuse it later.
- Rerankers, scheduled re-scraping, English-language site content, detecting
  contradictory numbers *inside* passages, applicant document processing.

**Anti-goals (failure even if it "works")**
- Presenting Raiffeisen content as the platform's own products, or implying
  affiliation (spec §1). Every passage is attributed to Raiffeisen Bank.
- Committing scraped Raiffeisen content to Git (see §3).
- Returning weakly related text as if it answered the question.
- Silently returning a superseded fee list, or an ended campaign rate without a warning.
- Retrieved text being treated as instructions anywhere downstream.

## 3. Constraints

- **Legal:** Raiffeisen's terms of use (`/ro/despre-noi/termeni-si-conditii.html`)
  forbid reproduction or publication without consent and claim database rights.
  The project owner confirmed the app stays on their machine. Therefore:
  raw downloads, extracted text and the database live only locally (ignored
  `data/local/` and a local Docker volume). Git contains code, the source list
  (URLs and rules) and evaluation questions, not page or PDF content.
  Test fixtures must be **synthetic** imitations of the document structures,
  not copied Raiffeisen text.
- **Spec alignment:** PostgreSQL + pgvector (spec §14–15), with tables
  `knowledge_documents`, `knowledge_document_versions`, `knowledge_chunks`
  (spec §14). Pydantic models at boundaries (RULES.md). Module placement per
  ARCHITECTURE.md. Retrieved documents are evidence, not instructions.
- **Locality:** the embedding model is downloaded once from Hugging Face and
  then runs offline. No external API is called during ingestion or retrieval.
- **Corpus language:** Romanian, with inconsistent diacritics. The same page
  can mix "dobândă" and "dobanda"; older PDFs use cedilla "ş/ţ" instead of
  comma "ș/ț".
- **Source site behaviour (verified 2026-10-28):** server-rendered AEM site,
  no JavaScript needed. `robots.txt` disallows only `/errors/`. Sitemap at
  `/ro/sitemap.xml` (1,257 URLs with `lastmod`, HTML only). The server is slow
  and sometimes stalls for minutes.
- **Platform:** Windows 11 dev machine with Docker Desktop; Python 3.11+ in `.venv`.

## 4. Approaches considered

| Option | Summary | Trade-off |
|---|---|---|
| **A. Local PostgreSQL + pgvector in Docker (chosen)** | Knowledge tables in the same Postgres the app will use; pgvector for dense search, Postgres full-text for keyword search, hybrid in one query | Matches spec; migration to Supabase is a connection-string change. Needs Docker running. |
| B. SQLite + sqlite-vec + FTS5 | Single file in `data/local/`, no server | Simplest to run, but a second database beside the future Postgres; tables need porting later. |
| C. Chroma embedded | Fastest first search | Weak keyword search and filtering makes versioning/conflict handling awkward; furthest from spec. Dropped. |

The project owner chose **A**. Docker Desktop is already installed.

Fixed across options (designer's call, accepted by the owner during discussion):
- Embedding model **BAAI/bge-m3**: multilingual including Romanian, 1024-dim
  dense vectors, up to 8k token input, CPU-capable at this corpus size.
- **Hybrid retrieval** (dense + keyword), because users ask about exact terms
  ("Flexicredit", "IRCC", "DAE", "comision de analiză").

## 5. Corpus

Scope, from the 2026-10-28 survey. Estimated 60–90 HTML pages and 20–30 PDFs.

- **Product pages** under `/ro/persoane-fizice/produsele-noastre/credite/`:
  personal loan (Flexicredit), refinancing unsecured / mortgage-backed
  (Flexi Integral), mortgage Casa Ta, Casa Ta Verde, Noua Casă, residential
  projects, overdraft; about 26 guide sub-pages; FAQ pages
  (`intrebari-frecvente-credit-nevoi-personale.html`,
  `intrebari-frecvente-despre-creditele-ipotecare-si-creditele-imobiliare.html`).
- **Credit cards:** about 15 pages under `produsele-noastre/carduri/` (lower priority).
- **Help / difficulty pages:** `/ro/aplica/restructurare-credit.html`,
  `/ro/persoane-fizice/in-sprijinul-tau/tine-ti-ratele-sub-control.html`,
  `informatii-utile/` pages (darea în plată, payment-suspension notices, CGB and
  fee change notices).
- **Blog** (`despre-bani-1-la-1/`): about 12 credit-related posts, tagged low authority.
- **PDFs** under `/content/dam/rbi/retail/eu/ro/documents/`: the 8 per-product
  cost sheets (`costuri/...`), the standard fee list (`pf/tarife-comisioane-standard-pf.sv.pdf`),
  the general banking conditions (CGB PF, Romanian edition), the IRCC explainer
  (`contractul-de-credit-pe-intelesul-tuturor`), repayment methods
  (`informare-modalitati-de-rambursare`), the required-documents list
  (`lista-documente-client-credite-garantate`), and credit-related PDFs linked
  from in-scope pages.

Known gaps: no dedicated early-repayment page (the early repayment fee appears
in the cost sheets), no public SECCI/FEIS template, no individual car loan.

## 6. Architecture and module placement

Placement follows ARCHITECTURE.md. Each module starts as a single file and is
split only when needed.

| Location | Responsibility |
|---|---|
| `config/rag/sources.yaml` | Committed source registry: URL allowlist patterns, extra PDF URLs, URL/filename → product and topic mapping rules, doc-type rules. |
| `config/rag/eval_questions.yaml` | Committed evaluation set (questions + expected source/section keys, no content). |
| `scripts/rag/scrape.py` | CLI: fetch sources into `data/local/rag/raw/` and write a manifest. |
| `scripts/rag/ingest.py` | CLI: run the ingestion pipeline over the manifest (or given local files). |
| `scripts/rag/search.py` | CLI: ad-hoc query for manual inspection during development. |
| `scripts/rag/evaluate.py` | CLI: run the eval set and print recall@k / MRR per question and overall. |
| `src/services/document_ingestion/` | Pipeline coordination, parsers per document kind, cleaning, chunking, metadata, versioning decisions. |
| `src/storage/document_store/` | Repository for `knowledge_documents` / `knowledge_document_versions`, plus raw-file access under `data/local/rag/raw/`. |
| `src/storage/vector_index/` | Repository for `knowledge_chunks`: upsert, hybrid search SQL. |
| `src/integrations/llm/embeddings.py` | `Embedder` protocol + local BGE-M3 implementation (sentence-transformers). Designer's call: embeddings sit with model adapters so the model can be swapped. |
| `src/services/retrieval/` | `RetrievalService.search()`: filtering, fusion, authority weighting, thresholds, conflict/staleness flags, context expansion. |
| `src/models/` | Shared Pydantic models that cross module boundaries (`SearchQuery`, `SearchResult`, `Passage`, `Citation`). |
| `src/core/` | Settings (DB URL, model name, thresholds) from environment / `.env`; dependency composition. |
| `src/storage/application_db/migrations/` | Schema migrations for the three knowledge tables and extensions. |
| `infrastructure/local/docker-compose.yml` | `pgvector/pgvector` Postgres 16 image, named Docker volume, port bound to localhost only. |

Data flow: `sources.yaml` → scrape → `data/local/rag/raw/` + `manifest.jsonl`
→ ingest (parse → clean → chunk → metadata → embed) → Postgres → `RetrievalService`
→ (later) orchestrator tool `search_banking_policies`.

## 7. Scraper

- **Seeds:** sitemap URLs matching the allowlist in `sources.yaml`, plus PDFs
  discovered as links on in-scope pages (filtered to `/content/dam/.../documents/`
  and allowlisted path patterns), plus explicitly listed extra URLs.
- **Politeness and robustness:** obey robots.txt; at most 1 request every 2 s;
  identifying User-Agent naming the project; 30 s timeout; 3 retries with
  exponential backoff; one stalled URL must not abort the run.
- **Output:** raw bytes saved by content hash in `data/local/rag/raw/`;
  `manifest.jsonl` records URL, final URL, fetched_at, HTTP status, content
  type, sitemap `lastmod`, sha256, and failure reason if any.
- **Incremental:** unchanged hash → no new version. A run summary lists new,
  changed, unchanged and failed URLs.

## 8. Cleaning and normalization

- Unicode NFC; map cedilla ş/ţ/Ş/Ţ → comma-below ș/ț/Ș/Ț; collapse whitespace.
- HTML: remove `header`, `footer`, `nav`, scripts, styles, forms, embedded JSON;
  deduplicate repeated text blocks (AEM renders some content twice);
  drop marketing-only sections by heading (testimonials, cross-sell, "Articole
  utile", "Motive în plus…", lead-capture forms, calculators). The heading
  deny-list lives in `sources.yaml`.
- PDF text via PyMuPDF. pdftotext garbles the fee list's diacritics. Tables are
  rebuilt as rows from word coordinates, with large horizontal gaps turned into
  ` | ` column separators. Repeated page furniture ("Banking 1:1") and cover
  pages are removed.

## 9. Chunking (validated by a throwaway spike on 5 real documents)

General rules:
- Target 300–500 tokens per chunk. Atomic units (one FAQ pair, one worked
  example, one table row group) are never split, even if somewhat larger.
- Every chunk carries a **context header** that is embedded with it and returned
  with it:
  `Raiffeisen Bank › <document title> › <section path> · <effective date>`.
- Every chunk records `prev`/`next` chunk ids and its parent section key, for
  context expansion.

Per document kind:

| Kind | Rule |
|---|---|
| `product_page` (HTML) | Split on h1/h2/h3. **Headings with no body text count as content**: Flexicredit's eligibility conditions are written only as h3 headings. Oversized sections split on paragraph boundaries. Each paragraph starting with "Exemplu de calcul" begins its own atomic **worked-example** chunk, which ends at the next heading or example. Following "general info" text is not appended to it. HTML tables are converted to pipe rows. |
| `faq` (HTML accordions, on FAQ pages *and* product pages) | One question + answer per chunk (`Întrebare: … / Răspuns: …`), section path = FAQ group heading + question. |
| `fee_list` (PDF) | Group rows by numbered section (`1.`, `1.1.`, …). Section detection must not mistake value lines ("100 lei", "10 lei/operațiune") for headings. When a section is split, its column header row is repeated in each piece. Footnotes stay with their section. |
| `general_terms` (CGB PDF) | Split by the document's numbering: chapter → section (`4.3`) → sub-clause (`4.3.1`). Sub-clauses can appear flattened on one line and must be split there too. A section ≤ 500 tokens is one chunk; otherwise pack sub-clauses; a single over-long clause is windowed by sentences with one-sentence overlap. |
| `cost_sheet` (PDF, ~8 files, one template) | **Template-specific parser**: generic row rebuilding scrambles multi-line table cells. Output: one chunk with product facts (type, currency, amount range, max period, benefits) and a clean table with one line per variant (client type, rate type, rate range, analysis fee, monthly admin fee, DAE range), plus footnotes and the **early repayment fee**. A second chunk holds the worked examples. If a sheet fails the template's checks, ingestion falls back to generic row text and logs a warning. |
| `pdf_generic` (IRCC explainer, repayment methods, required-documents list, others) | Split on numbered headings / bold heading lines; tables as rows; short documents (< ~600 tokens) stay one chunk. |
| `article` (blog, guides) | As `product_page`, but `authority=low`. |

## 10. Metadata, versioning and freshness

**Per chunk:**
- `publisher` ("Raiffeisen Bank Romania")
- `doc_kind`
- `products[]`
- `topic`
- `authority` (high: cost_sheet, fee_list, general_terms, product_page; medium: faq; low: article)
- `section_path[]`
- `page` (PDF) or `anchor` (HTML heading id)
- `token_count`

**Products** (from URL and filename rules): `personal_loan`, `refinancing_unsecured`,
`refinancing_mortgage`, `mortgage_casa_ta`, `mortgage_casa_ta_verde`,
`mortgage_noua_casa`, `mortgage_residential_projects`, `overdraft`,
`credit_card`, or `general`.

**Topics:**
- Credit topics: `eligibility`, `costs_fees`, `worked_example`, `required_documents`,
  `early_repayment`, `refinancing`, `restructuring_difficulty`, `variable_rate_ircc`,
  `repayment_methods`, `credit_process`, `general_terms_credit`
- Non-credit topics: `accounts`, `payments`, `cards`, `data_protection`, `aml`, `other`

Topics are assigned by rules: source path, CGB chapter/section number → topic
map, fee-list section → topic map, and section-keyword rules.
**Default search covers credit topics only.** The spike showed the CGB
(264 chunks, ~3 credit-related) and the fee list (accounts/payments/cards)
would otherwise make up ~80% of the index.

**Document identity:** `canonical_key` = URL path for HTML; for PDFs, the path
with the date prefix and `.coredownload*` suffix stripped. So
`20260901-Tarife-…pdf` and the stable `.sv.pdf` alias share an identity.
Designer's call: if both the alias and a dated file are fetched with identical
hashes, store one version.

**Effective date**, in order of preference:
1. Date printed in the document ("1 septembrie 2026", "Editia 26.02.2026", or a leading `DD.MM.YYYY` line on cost sheets)
2. `YYYYMMDD` filename prefix
3. Sitemap `lastmod`
4. fetch date

Record which one was used (`effective_date_source`).

**Campaign windows (decided by the project owner: warn, don't hide):**
campaign phrases such as "Perioada campaniei: 15.10 - 26.11.2026" are detected
and stored as `campaign_valid_until` on the **document version**, because
campaign rates and campaign dates often sit in different sections. The year
is inferred from context when it's missing. Nothing is hidden when a campaign
ends. Every passage from a version whose campaign has ended (`campaign_valid_until < as_of`)
carries the `campaign_ended` flag and a warning: the page advertised a campaign
that ended on <date>, and its figures may be out of date until the page is
re-fetched. While the campaign runs, passages carry `campaign_active` with the
end date.

**Version lifecycle (designer's call, revised after builder review):**
"Which version is in force" is decided by **effective date**, not by ingestion
order.

- Each version has `effective_from` (its effective date) and a derived
  `effective_to` (the next version's `effective_from`).
- The version in force on date D is the one with the latest
  `effective_from ≤ D`.
- A newer-dated file ingested earlier still wins, and an older dated file
  ingested later never displaces it.
- A future-dated version (for example a fee list announced before it takes
  effect) is stored and indexed, but excluded until its date unless
  `as_of` asks for it.
- `as_of` therefore selects the versions in force and determines campaign flags.
- Passages from a version that is no longer in force carry the `superseded`
  flag when they are requested explicitly.
- Ingestion of one version is a single transaction.

**Withdrawn documents (designer's call):** a document is marked `withdrawn`
only when all of these are true in the same scrape run:

- the run completed (failures under a threshold, e.g. < 10% of URLs)
- the URL is absent from both the sitemap and in-scope page links
- fetching it returns HTTP 404 or 410

Timeouts or stalls never withdraw anything. Withdrawn documents are excluded
by default and their passages carry a `withdrawn` flag if requested.

## 11. Database schema (conceptual; refine in migration)

Extensions: `vector`, `unaccent`. Keyword search uses a custom text-search
configuration combining `unaccent` with the Romanian snowball stemmer, so
"dobanda" matches "dobândă". The builder should verify that the image ships
the `romanian` configuration and fall back to `simple` + unaccent if not.

- `knowledge_documents`: `id`, `canonical_key` (unique), `source_url`,
  `title`, `doc_kind`, `publisher`, `language`, `created_at`
- `knowledge_document_versions`: `id`, `document_id` FK, `content_hash`,
  `version_label`, `effective_from` (the effective date), `effective_date_source`, `fetched_at`,
  `sitemap_lastmod`, `raw_path`, `campaign_valid_until`,
  `ingested_at`, `parser_name`, `parser_version`.
  Unique (`document_id`, `content_hash`). "In force" is computed from
  `effective_from` (a view or query helper), not stored as a flag.
  `knowledge_documents` additionally has `status` (`active` | `withdrawn`)
  and `last_seen_at`.
- `knowledge_chunks`: `id`, `version_id` FK, `ordinal`, `kind`, `topic`,
  `products text[]`, `authority`, `section_path text[]`, `page`, `anchor`,
  `header`, `text`, `token_count`, `prev_chunk_id`,
  `next_chunk_id`, `parent_section_key`, `embedding vector(1024)`,
  `tsv tsvector` (generated from header + text). Indexes: HNSW on embedding
  (cosine), GIN on `tsv`, btree/GIN on `topic`, `products`, `version_id`.
- An `index_runs` record (designer's call) stores the embedding model name and
  version and chunker version for each ingest run, so results can report
  which index produced them.

## 12. Retrieval service

`RetrievalService.search(query: SearchQuery) -> SearchResult`, with Pydantic models in `src/models/`.

**`SearchQuery` fields:**

| Field | Default | Notes |
|---|---|---|
| `text` | required | 1–1000 chars |
| `products` | `None` | |
| `topics` | credit topics | |
| `doc_kinds` | `None` | |
| `top_k` | 6 | max 20 |
| `as_of` | today | |
| `include_superseded` | `False` | |
| `expand_context` | `False` | |

**Algorithm:**
1. Embed the query (BGE-M3).
2. Run two candidate searches (top 30 each) restricted by filters and,
   unless requested otherwise, to versions in force on `as_of` and documents not withdrawn:
   - dense: cosine on `embedding`
   - keyword: `websearch_to_tsquery` on `tsv` with the unaccent/Romanian configuration
3. Fuse with Reciprocal Rank Fusion (k = 60), then apply a small authority
   multiplier (high > medium > low). The exact weights are tuned with the eval set.
4. **Evidence threshold (designer's call, revised after builder review):**
   - Keyword search ORs the query's content terms (stopwords removed) rather
     than ANDing every word.
   - Passing the threshold requires either the best dense similarity ≥ a
     dense floor, or the best keyword rank ≥ a keyword floor **and** that
     chunk's dense similarity ≥ a lower secondary floor. A bare match on a
     generic word like "credit" is not enough.
   - Otherwise return `status="insufficient_evidence"` with no passages.
   - All floors are calibrated on the eval set, including the unanswerable questions.
   - The builder may restructure this rule if the eval shows a better one.
     The requirement is the eval gate in §13, not this exact formula.
5. Deduplicate near-identical passages (e.g. the same FAQ on a product page and an FAQ page).
6. Flags per passage: `superseded`, `withdrawn`, `campaign_active` /
   `campaign_ended` (with date and warning text; never excluded), `low_authority`.
7. **Conflict notice (designer's call, narrowed after builder review):** add a
   `conflicts` entry only when the results contain passages from two
   *different* documents that are both in force and share all of the following:
   - the same `doc_kind`
   - the same `topic`
   - at least one *specific* product (`general` matches nothing)

   For example, two cost sheets for the same product. Cross-kind combinations
   (product page + cost sheet + FAQ) are normal and do not trigger it. Both
   passages are kept and the orchestrator decides. Detecting contradictory
   numbers within text is out of scope.
8. `expand_context`: attach the previous and next chunk texts of each passage.

**`SearchResult` fields:**
- `status`: `ok` | `insufficient_evidence`
- `passages[]`, each with:
  - `chunk_id`, `header`, `text`
  - `citation`: `publisher`, `title`, `url`, `page` / `anchor`, `section_path`,
    `version_label`, `effective_date`, `fetched_at`, `campaign_valid_until`
  - `scores` (`dense`, `keyword`, `fused`)
  - `flags`
  - `context`
- `conflicts[]`
- `index_info` (model, chunker version, last ingest time)
- `content_trust: "untrusted_evidence"`

**Errors:** a database being unreachable or the model failing to load raises
typed errors from `src/core`. A failure must never come back as an empty "ok" result.

## 13. Quality evaluation

- `config/rag/eval_questions.yaml`: 30–40 Romanian questions drawn from spec §4.1
  and real customer phrasing. Each lists expected `canonical_key` (+ optional
  section-path prefix). Include about 5 questions the corpus cannot answer,
  expecting `insufficient_evidence`. Examples:
  - "Ce acte îmi trebuie pentru un credit de nevoi personale?"
  - "Există comision de rambursare anticipată la Flexicredit?"
  - "Ce este IRCC?"
  - "Până la ce vârstă pot lua un credit?"
- `scripts/rag/evaluate.py` reports recall@5, MRR, and accuracy on the
  unanswerable questions.
- Designer's call: target recall@5 ≥ 0.8 and ≥ 4 of 5 unanswerable questions correctly refused before calling the work done.

## 14. Testing

- **Unit (synthetic fixtures in `tests/fixtures/rag/`)**:
  - each parser/chunker on small hand-written HTML/PDF imitations of the
    real structures: AEM accordion, heading-only conditions, worked-example
    paragraphs, fee table with value lines, flattened CGB sub-clauses, cost-sheet template
  - diacritic normalization
  - canonical-key and effective-date extraction
  - campaign window parsing
  - RRF fusion and threshold logic
- **Integration (Docker Postgres)**:
  - migrations apply cleanly
  - ingest → search round trip
  - re-ingesting unchanged content creates no version
  - changed content supersedes the previous version
  - superseded, future-dated and withdrawn content is excluded by default; ended campaigns are flagged, not excluded
  - conflict notice appears
  - unaccented keyword match ("dobanda" finds "dobândă")
- The eval script runs against the real local index. It is a manual quality
  gate, not a CI test, because the corpus is not committed.

## 15. Dependencies (to add to `requirements.txt`)

| Package | Purpose |
|---|---|
| `psycopg[binary]` | Postgres driver |
| `pgvector` | pgvector support |
| `sentence-transformers` | embeddings (pulls in PyTorch; CPU build is sufficient) |
| `beautifulsoup4` | HTML parsing |
| `pymupdf` | PDF text extraction |
| `httpx` | scraper HTTP client |
| `pyyaml` | config files |
| migration tool (builder's choice) | schema migrations |

Note: PyMuPDF is AGPL-licensed, which is acceptable for a local hackathon
prototype; revisit before any distribution.

## 16. Decided vs. left to the builder

**Decided with the project owner:**
- Raiffeisen public documentation, attributed
- local-only database, indexes and embeddings
- Featherless LLM later, in the orchestrator
- retrieval-only service
- app runs only locally
- approach A (Postgres + pgvector in Docker)
- chunking plan in §9 with the spike's four adjustments:
  - topic tagging with credit-default search
  - template parser for cost sheets
  - heading-only content kept
  - campaign window recorded per version; ended campaigns warn, not hide

**Designer's calls (flagged for review):**
- BGE-M3
- RRF + authority weighting
- topic and product taxonomies
- effective-date precedence
- conflict-notice rule
- `index_runs` table
- eval targets
- embedding adapter location
- alias/dated PDF dedup
- localhost-only DB port

**Left to the builder:**
- migration tool
- exact SQL
- token counting method
- HNSW parameters
- fusion weights and thresholds (tuned by eval)
- CLI ergonomics
- internal file split within each module
- exact allowlist patterns

**Process:**
- Follow GIT_AGENT_PROTOCOL.md: claim the task in `.agents/BOARD.md`, use
  `agent(<role>): …` commit messages, and append to `.agents/log.md`.

**Reference spike:**
- The throwaway spike lives outside the repo at `C:\Users\vladb\rag-spike\`
  (script `scripts/chunk_spike.py`, outputs in `out/`). It is reference material, not code to keep.
