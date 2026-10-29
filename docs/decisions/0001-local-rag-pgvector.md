# ADR 0001: Local RAG retrieval with PostgreSQL + pgvector, BGE-M3 and hybrid fusion

- Status: accepted (2026-10-29)
- Design: [`docs/superpowers/specs/2026-10-28-rag-retrieval-design.md`](../superpowers/specs/2026-10-28-rag-retrieval-design.md)
- Runbook: [`docs/runbooks/rag-local.md`](../runbooks/rag-local.md)

## Context

The platform's future orchestrator must answer credit policy and product questions with cited
evidence from Raiffeisen Bank Romania's public documentation (product pages, guides, FAQs,
category hubs, cost sheets, the fee list, the general banking conditions). Raiffeisen's terms
forbid republishing that content, so everything (scraped files, extracted text, the index and
the embedding model) must stay on the developer's machine. The corpus is Romanian with
inconsistent diacritics, and users ask both in natural language and with exact terms
("Flexicredit", "IRCC", "DAE").

## Decision

1. **Approach A: local PostgreSQL 16 + pgvector in Docker** (`infrastructure/local/docker-compose.yml`,
   port bound to `127.0.0.1`). Knowledge tables sit in the same Postgres the application will use,
   so moving to a managed Postgres is a connection-string change.
2. **Embeddings: `BAAI/bge-m3`** (multilingual, 1024 dimensions), run locally with
   sentence-transformers; downloaded once, then loaded offline.
3. **Hybrid retrieval**: dense cosine search plus Postgres full-text search with an unaccented
   Romanian configuration, fused with reciprocal rank fusion (RRF), filtered to versions in force on
   `as_of`, with flags, hub deferral to cost sheets, conflicts and "read more" links (spec §12).
4. **Evaluation on committed labelled splits** (`config/rag/eval/`): `tune.yaml` (261 questions,
   17 unanswerable) is used for calibration; `validation.yaml` (183 questions, 12 unanswerable) is
   a hold-out. These replace the 30–40 question `eval_questions.yaml` planned in spec §13. Labels
   are evidence (document key + short anchors or a section hint), not chunk ids, so they survive
   re-chunking.

## Alternatives considered

- **B. SQLite + sqlite-vec + FTS5:** simplest to run (one file), but a second database beside the
  future Postgres, and the tables would need porting later.
- **C. Embedded Chroma:** fastest first search, but weak keyword search and filtering make the
  versioning, withdrawal and conflict rules awkward; furthest from the specification. Dropped.

## Calibration (tune split only)

Measured with `scripts/rag/evaluate.py` on the real index (115 versions, 1,668 chunks), using
precomputed query vectors. Recall@5 counts a question as answered when a matching passage is in
the top 5 and the question is not refused.

| Configuration | recall@5 | MRR | nDCG@10 | refusals | false refusals |
|---|---|---|---|---|---|
| Initial defaults (weights 1/0.9/0.75, rrf_k 60, dense floor 0.55 or keyword route) | 0.738 | 0.554 | 0.511 | 3/17 | 0.0% |
| Flat authority weights | 0.820* | 0.610 | 0.562 | – | – |
| Flat weights, rrf_k 20 | 0.840* | 0.617 | 0.569 | – | – |
| … + margin rule (w=3, floor 0.74): validation run 1 config | 0.807 | 0.586 | 0.540 | 14/17 | 6.1% |
| Keyword list weight 0.3, rrf_k 20, flat weights | 0.889* | 0.732 | 0.669 | – | – |
| **Final: + margin rule (w=3, rank 10, floor 0.75)** | **0.840** | **0.695** | **0.635** | **15/17** | **6.6%** |

`*` ranking only, no refusals. Measured and not adopted (no tune gain): `candidate_k` 50/100,
`hnsw.iterative_scan = relaxed_order` (pgvector 0.8.7; identical results: the filtered searches
already return enough candidates), authority as a tie-breaker only, a per-document passage cap,
a document-level margin profile.

Findings that shaped the final values:

- **Authority weighting hurt recall.** Down-weighting guides and FAQs (medium) and articles and
  hubs (low) pushed the passages that answered the question below weaker high-authority ones; this
  is the interaction Task 9 flagged. Weights are now flat; authority is still reported per passage
  (`low_authority`), and the orchestrator can prefer high-authority sources when quoting.
- **The keyword list needed a lower weight.** The OR-ed keyword query matches generic terms
  broadly; dense-only ranking already beat equal-weight fusion (recall 0.865 vs 0.840). A keyword
  weight of 0.3 keeps exact-term matches as a contribution and gave the best recall (0.889).
- **The evidence threshold was restructured (spec §12.4 allows this).** Unanswerable questions
  scored best dense similarities of 0.34–0.67 and answerable ones 0.55–0.80, and keyword ranks were
  just as high for both, so no combination of the original floors could meet the gate (best: 4/17
  refusals with no false refusals). Answerable questions have a clear best match, near misses a flat
  profile of similar chunks, so the rule is now
  `best + 3 × (best − 10th best) ≥ 0.75` (dense similarities of the filtered candidates).
  The floor is the centre of the widest tune plateau that meets the gate.

## Validation (hold-out)

| Run | Configuration | recall@5 | MRR | nDCG@10 | refusals | false refusals | gate |
|---|---|---|---|---|---|---|---|
| 1 | flat weights, rrf_k 20, keyword weight 1.0, floor 0.74 | 0.754 | 0.581 | 0.538 | 10/12 (0.833) | 16/171 (0.094) | FAIL (recall) |
| 2 | final values | 0.807 | 0.660 | 0.607 | 10/12 (0.833) | 19/171 (0.111) | FAIL (false refusals) |
| 3 (last) | after fix wave: chunker 2 (table rows, long-line split, one cost_facts chunk), same settings; tune 0.840 / 15/17 / 16/244 (0.066), labels 0 unmatched | 0.784 | 0.638 | 0.586 | 10/12 (0.833) | 20/171 (0.117) | FAIL (recall, false refusals) |

The gate (recall@5 ≥ 0.8, refusal accuracy ≥ 0.8, false refusals ≤ 0.1) is **not met**: run 2
misses the false-refusal limit by two questions. Run 3, the last one, was spent after the final fix
wave re-chunked the corpus (settings unchanged, since tune still passed): recall@5 fell to 0.784 and
false refusals rose to 20/171, so it misses both limits. No tuning follows it. The recall-versus-refusal trade-off is limited by the signal a dense profile carries.

## Consequences

- Everything runs locally; Docker must be running (`KnowledgeStoreUnavailable` otherwise) and the
  model must be cached (`EmbeddingModelUnavailable` otherwise).
- Data never leaves `data/local/` and the Docker volume; the service must not be deployed publicly.
- Parser changes need `ingest.py --rebuild`; evaluation labels are re-checked with `--check-labels`.
- About 6–11% of answerable questions are refused as insufficient evidence; the orchestrator should
  offer a rephrase or a broader search rather than say "no information".
- Next improvements, in expected order of value:
  1. split over-long lines (up to 1,907 tokens) into sentence-packed chunks, then re-embed;
  2. a cross-encoder reranker, or a learned evidence check, to separate near-miss questions;
  3. grow the unanswerable sets (17 and 12 questions make refusal accuracy coarse).
