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

- Windows with PowerShell. Every command below runs **from the repository root**
  (`C:\Users\<you>\...\MergeConflict`) in your own PowerShell window.
- Docker Desktop, Python 3.11+ in `.venv` (`.\.venv\Scripts\python -m pip install -r requirements.txt`).
- About 5 GB of disk for the model and torch, plus a few hundred MB for raw files and the database.
- Memory: loading BGE-M3 takes about 2–3 GB of RAM in the Python process (more on CPU while
  embedding). On a 16 GB machine, close other heavy programs first.

### Run the model outside Claude Code

Claude Code's memory guard kills large processes it launches. Run every command that loads
BGE-M3 (`ingest.py`, `embed_eval_queries.py`, `search.py`, and `evaluate.py` without
`--query-vectors`) **in your own PowerShell window**, not through an agent. Everything else
(scrape, `evaluate.py --query-vectors ...`, `--check-labels`, the tests) never loads the model.

### GPU (CUDA)

On a machine with an NVIDIA GPU (e.g. an RTX 4060), embed on the GPU. Install the CUDA build
of torch once (it replaces the CPU build in `.venv`):

```powershell
.\.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"
```

The check must print `True`. Then select the device, either for one PowerShell session:

```powershell
$env:RAG_EMBEDDING_DEVICE = "cuda"
```

or permanently with `RAG_EMBEDDING_DEVICE=cuda` in `.env` (`.env.example` ships `cpu`, which
works everywhere). Query vectors and document vectors from `cpu` and `cuda` are interchangeable.

Rough durations (estimates; note your own) for the full corpus (about 115 documents, 1,700 chunks): **GPU** a few minutes,
most of it loading the model; **CPU** 20–40 minutes, and the machine is sluggish meanwhile.
Embedding the eval questions takes about a minute on either device after the model loads.

## 1. Start the database

```powershell
docker compose -f infrastructure/local/docker-compose.yml up -d
```

The `rag-db` container listens on `127.0.0.1:5433` only. The dev database is `rag`; the test
database `rag_test` is created on first start. The service has `restart: unless-stopped`; if
Docker itself was restarted and the container is down, run the same command again.
`scripts/rag/ingest.py` applies the schema migrations itself.

## 2. Download the embedding model (once)

The adapter loads `BAAI/bge-m3` offline (`local_files_only`). Allow a download once:

```powershell
$env:RAG_ALLOW_MODEL_DOWNLOAD = "1"
.\.venv\Scripts\python -c "from src.integrations.llm.embeddings import BgeM3Embedder; BgeM3Embedder().embed_query('test')"
Remove-Item Env:RAG_ALLOW_MODEL_DOWNLOAD
```

The model is cached under `~/.cache/huggingface`. Later runs need no network.

## 3. Scrape, ingest, search, evaluate

```powershell
.\.venv\Scripts\python scripts\rag\scrape.py --manifest data\local\rag\manifest.jsonl
.\.venv\Scripts\python scripts\rag\ingest.py
.\.venv\Scripts\python scripts\rag\search.py "Există comision de rambursare anticipată la Flexicredit?"
.\.venv\Scripts\python scripts\rag\evaluate.py --split tune
```

- **scrape** follows `config/rag/sources.yaml`: the sitemap plus allowlisted pages, and the PDFs
  linked from them. It is polite (one request every 2 s, the project User-Agent, robots.txt obeyed),
  so a full run takes 5–20 minutes. Re-runs are incremental and detect withdrawn pages; a URL that
  fails to fetch keeps its last good copy in the manifest.
- **ingest** reads the manifest (`--manifest PATH`, default `data/local/rag/manifest.jsonl`) and
  stores a new version for each changed document. It checks the database and migrations before
  loading the model, so a stopped database fails in seconds. It prints the outcome counts, parser
  warnings and errors. See the durations above.
- **search** prints each passage's header, scores, flags, warnings, URL, the first 300 characters
  and "read more" links, then any conflicts. Options: `--top-k N`, `--as-of YYYY-MM-DD`, `--all-topics`.
- **evaluate** runs a labelled split and prints recall@5, MRR, nDCG@10, refusal accuracy,
  false-refusal rate, breakdowns and the 15 worst questions. Options: `--k`, `--as-of`,
  `--check-labels` (only checks that every label matches an indexed chunk), `--query-vectors`.

In code, build the service with `src/services/retrieval/factory.py`:
`build_retrieval_service(settings=None, embedder=None)` reads `.env`/`RAG_*` and uses the local
BGE-M3 adapter (loaded lazily on the first search) unless you pass your own.

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

**Narrow filters weaken refusal.** The margin is measured against the Nth dense candidate
(`RAG_DENSE_MARGIN_RANK`). When the filters (`products`, `doc_kinds`, a few `topics`) leave fewer
than N candidates, it is measured against the last one instead: the tail of a short, sparse list,
which can sit far below the best match. That inflates the margin, so an off-topic question searched
with narrow filters can pass where the same question unfiltered is refused. The threshold was
calibrated on unfiltered searches; give weak-looking filtered results less weight.

### Evaluating without loading the model

On a machine short of memory, embed the eval questions once (in your own terminal) and evaluate
from the saved vectors:

```powershell
.\.venv\Scripts\python scripts\rag\embed_eval_queries.py          # loads BGE-M3 once
.\.venv\Scripts\python scripts\rag\evaluate.py --split tune --query-vectors data\local\rag\eval_query_vectors.npz
```

The vectors file lives in `data/local/` (not committed). Re-run the embedding step after editing
question texts; an unknown question raises `EmbeddingModelUnavailable`. A re-ingest does not
require it: the vectors depend only on the questions and the model.

### Rebuild after chunker or parser changes

Ingestion skips documents whose bytes are unchanged, so a parser change needs a rebuild:

```powershell
$env:RAG_EMBEDDING_DEVICE = "cuda"   # if you have the GPU set up
.\.venv\Scripts\python scripts\rag\ingest.py --rebuild
```

`--rebuild` empties the knowledge tables, then ingests the whole manifest again. Each run is
recorded in `index_runs` with its `embedding_model` and `chunker_version`.

### Recovering from a killed ingest

If an ingest is killed (closed window, out of memory, Ctrl+C at the wrong moment), its
`index_runs` row can stay `running`. Each document is committed on its own, so the index holds
every document ingested before the kill; after a killed `--rebuild` it is therefore partial,
while searches still report the last completed run. Mark the stale row failed, then run the same
ingest again:

```powershell
docker compose -f infrastructure/local/docker-compose.yml exec rag-db psql -U rag -d rag -c "UPDATE index_runs SET status = 'failed', finished_at = now() WHERE status = 'running';"
.\.venv\Scripts\python scripts\rag\ingest.py --rebuild
```

Only do this when no ingest is running. To see the recent runs:

```powershell
docker compose -f infrastructure/local/docker-compose.yml exec rag-db psql -U rag -d rag -c "SELECT id, status, started_at, finished_at, chunker_version, versions_created, failures FROM index_runs ORDER BY id DESC LIMIT 5;"
```

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

```powershell
.\.venv\Scripts\python -m pytest -v --basetemp=C:\Users\<you>\pytest-tmp
```

On this machine, tests that use `tmp_path` need `--basetemp` pointing at a folder outside the
repository whose parent exists. The integration tests use `rag_test` (the fixture refuses any
database whose name doesn't end in `_test`) and are skipped when the database is unreachable.
They never download or load a model; they use a fake embedder.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `error: KnowledgeStoreUnavailable: knowledge store unreachable ...` (exit code 2) | Docker or `rag-db` is not running. Start it (step 1). |
| `error: KnowledgeStoreUnavailable: knowledge index is empty ...` | No completed ingest run in this database. Run `ingest.py` (step 3). |
| `error: KnowledgeStoreUnavailable: knowledge store query failed ...` | Tables or the `vector` extension are missing (wrong or unmigrated database). Check `RAG_DATABASE_URL`, then run `ingest.py`, which applies migrations. |
| `error: manifest not found: ...` (exit code 2) | Run `scrape.py` first, or pass `--manifest`. |
| `error: EmbeddingModelUnavailable: ...` (exit code 2) | The model is not in the cache. Download it once (step 2). With `cuda`, also check that the CUDA build of torch is installed. |
| The ingest process disappears without an error | Out of memory, or it was started by an agent and killed by its memory guard. Run it in your own PowerShell, on the GPU if possible; then see "Recovering from a killed ingest". |
| `relation ... does not exist` in integration tests | Another session reset `rag_test`; run the tests again. |
| A document is reported `failed: no extractable content` | A scanned PDF or a page without main content. Nothing is written and any older version stays in force. |
