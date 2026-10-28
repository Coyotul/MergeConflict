# Runbook: local RAG knowledge base

The knowledge base indexes Raiffeisen Bank Romania's public credit documentation for
retrieval by `RetrievalService.search()`. Everything runs on this machine: Postgres with
pgvector in Docker, the BGE-M3 embedding model and the scraped files. Design:
[`docs/superpowers/specs/2026-10-28-rag-retrieval-design.md`](../superpowers/specs/2026-10-28-rag-retrieval-design.md).
Decision record: [`docs/decisions/0001-local-rag-pgvector.md`](../decisions/0001-local-rag-pgvector.md).

## Legal note: local only

Raiffeisen's terms of use forbid reproducing or publishing their content. Therefore:

- Raw downloads, the manifest and extracted text stay in `data/local/` (ignored by Git) and
  the database stays in the local Docker volume. **Never commit anything under `data/local/`**,
  and never paste page or PDF text into committed files, tests or fixtures (fixtures are
  synthetic imitations).
- Do not deploy this knowledge base, or a service backed by it, publicly.
- Answers built on it must cite `citation.url` and attribute Raiffeisen Bank Romania.

## Requirements

- Docker Desktop, Python 3.11+ in `.venv` (`pip install -r requirements.txt`).
- About 5 GB of disk for the model and torch, plus a few hundred MB for raw files and the database.

## 1. Start the database

```bash
docker compose -f infrastructure/local/docker-compose.yml up -d
```

The `rag-db` container listens on `127.0.0.1:5433` only. The dev database is `rag`; the test
database `rag_test` is created on first start. The service has `restart: unless-stopped`; if
Docker itself was restarted and the container is down, run the same command again.
`scripts/rag/ingest.py` applies the schema migrations itself.

## 2. Download the embedding model (once)

The adapter loads `BAAI/bge-m3` offline (`local_files_only`). Allow a download once:

```bash
RAG_ALLOW_MODEL_DOWNLOAD=1 .venv/Scripts/python -c "from src.integrations.llm.embeddings import BgeM3Embedder; BgeM3Embedder().embed_query('test')"
```

The model is cached under `~/.cache/huggingface`. Later runs need no network.

## 3. Scrape, ingest, search, evaluate

```bash
.venv/Scripts/python scripts/rag/scrape.py --manifest data/local/rag/manifest.jsonl
.venv/Scripts/python scripts/rag/ingest.py
.venv/Scripts/python scripts/rag/search.py "Există comision de rambursare anticipată la Flexicredit?"
.venv/Scripts/python scripts/rag/evaluate.py --split tune
```

- **scrape** follows `config/rag/sources.yaml`: the sitemap plus allowlisted pages, and the PDFs
  linked from them. It is polite (one request every 2 s, the project User-Agent, robots.txt obeyed),
  so a full run takes 5–20 minutes. Re-runs are incremental and detect withdrawn pages.
- **ingest** reads the manifest and stores a new version for each changed document. It prints the
  outcome counts, parser warnings and errors. Embedding the corpus on CPU takes 10+ minutes.
- **search** prints each passage's header, scores, flags, warnings, URL, the first 300 characters
  and "read more" links, then any conflicts. Options: `--top-k N`, `--as-of YYYY-MM-DD`, `--all-topics`.
- **evaluate** runs a labelled split and prints recall@5, MRR, nDCG@10, refusal accuracy,
  false-refusal rate, breakdowns and the 15 worst questions. Options: `--k`, `--as-of`,
  `--check-labels` (only checks that every label matches an indexed chunk).

Settings come from `RAG_*` variables in `.env` (see `.env.example`); the defaults in
`src/core/settings.py` hold the calibrated values. A local `.env` overrides them, so keep its
`RAG_*` lines in step with `.env.example` after a recalibration.

| Setting | Value | Meaning |
|---|---|---|
| `RAG_DENSE_FLOOR` | 0.75 | evidence floor for `best + RAG_DENSE_MARGIN_WEIGHT × (best − Nth best)` dense similarity |
| `RAG_DENSE_MARGIN_WEIGHT` | 3.0 | how much a clear best match counts over a flat profile of near misses |
| `RAG_DENSE_MARGIN_RANK` | 10 | N: the dense candidate the margin is measured against |
| `RAG_KEYWORD_WEIGHT` | 0.3 | weight of the keyword list in reciprocal rank fusion (dense = 1) |
| `RAG_RRF_K` | 20 | RRF constant |
| `RAG_CANDIDATE_K` | 30 | candidates per retriever |
| `RAG_AUTHORITY_WEIGHTS` | all 1.0 | fused-score multipliers per authority level |

### Evaluating without loading the model

On a machine short of memory, embed the eval questions once and evaluate from the saved vectors:

```bash
.venv/Scripts/python scripts/rag/embed_eval_queries.py          # loads BGE-M3 once
.venv/Scripts/python scripts/rag/evaluate.py --split tune --query-vectors data/local/rag/eval_query_vectors.npz
```

The vectors file lives in `data/local/` (not committed). Re-run the embedding step after editing
question texts; an unknown question raises `EmbeddingModelUnavailable`.

### Rebuild after chunker or parser changes

Ingestion skips documents whose bytes are unchanged, so a parser change needs a rebuild:

```bash
.venv/Scripts/python scripts/rag/ingest.py --rebuild
```

`--rebuild` empties the knowledge tables, then ingests the whole manifest again.

## Evaluation splits and the hold-out rule

`config/rag/eval/` holds two labelled splits (format: `config/rag/eval/README.md`):

- `tune.yaml`: use it freely to calibrate floors, weights and chunking.
- `validation.yaml`: a **hold-out**. Run it only to confirm a configuration chosen on tune;
  never change anything to make it pass. Its gate: recall@5 ≥ 0.8, refusal accuracy ≥ 0.8,
  false-refusal rate ≤ 0.1 (`evaluate.py --split validation` exits non-zero otherwise).

After a chunker or parser change, run `evaluate.py --split tune --check-labels`. Fix a parser
that drops content; edit a label (`section_hint`, `must_contain`) only when the content is
present but chunked or headed differently, and never edit a question.

## Tests

```bash
.venv/Scripts/python -m pytest -v --basetemp=C:/Users/<you>/pytest-tmp
```

On this machine, tests that use `tmp_path` need `--basetemp` pointing at a writable folder.
The integration tests use `rag_test` and are skipped when the database is unreachable. They never
download a model; they use a fake embedder.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `error: KnowledgeStoreUnavailable: ...` (exit code 2) | Docker or `rag-db` is not running. Start it (step 1). |
| `error: EmbeddingModelUnavailable: ...` (exit code 2) | The model is not in the cache. Download it once (step 2). |
| `relation ... does not exist` in integration tests | Another session reset `rag_test`; run the tests again. |
| A document is reported `failed: no extractable content` | A scanned PDF or a page without main content. Nothing is written and any older version stays in force. |
