# RAG retrieval evaluation sets

Two labelled query sets for `RetrievalService.search()` (spec §13):

| File | Use |
|---|---|
| `tune.yaml` | Calibrate thresholds, fusion and authority weights, and chunking. Run as often as you like. |
| `validation.yaml` | **Hold out.** Run only to confirm a configuration chosen on `tune.yaml`. Never adjust anything to make it pass; if it fails, go back to `tune.yaml`. |

The split is made per information need (`group`): paraphrases of the same need are
always in the same file. Splitting is stratified by source document, then by
`doc_kind` × `topic`, at about 60/40. Each file's `stats` block shows its coverage.

## Question fields

- `question`: Romanian, in one of six styles: `formal`, `colloquial`, `no_diacritics`, `keyword`, `scenario`, `comparison`.
- `answerable`: `false` means the service must return `insufficient_evidence`. `unanswerable_kind` says why: `off_domain`, `realtime_personal`, `bank_out_of_scope`, `competitor` or `credit_near_miss`.
- `products`: pass as `SearchQuery.products`.
- `all_topics: true`: search all topics, not only the credit default. The question is about accounts, payments, cards, data protection and the like.
- `behaviour`: special cases to report separately:
  - `teaser_figure`: the cost sheet must outrank the hub card.
  - `campaign`
  - `worked_example`
  - `read_more`
  - `superseded_risk`: older notices cover similar ground; the newest one is expected.
- `expected[]`: every passage that answers the question, not just one. Each entry has:
  - `canonical_key`, `section_hint`
  - `must_contain`: short anchors taken from the passage
  - `grade`: 2 answers directly, 1 is acceptable partial evidence
  - `doc_kind`, `topic`, `products`, used for per-stratum reports

## Matching rule

A returned passage matches an expected entry when `canonical_key(citation.url)`
equals the entry's `canonical_key` and either:

- every `must_contain` anchor occurs in the passage text, or
- `section_hint` occurs in `" › ".join(section_path)`.

Both comparisons are case- and accent-insensitive. Labels are tied to evidence,
not to chunk ids, so they survive re-chunking. Run the label check in plan Task 11
after each chunker change: every expected entry must match at least one indexed chunk.

## Provenance

- Corpus: fetched on 2026-10-28 from Raiffeisen Bank Romania's public site (116 documents).
- Chunks: made with a throwaway mock chunker that follows the 2026-10-28 design. The mock lives outside the repo, at `C:\Users\vladb\rag-mock\`.
- Questions: drafted by model agents from those chunks and validated by script. Every anchor occurs verbatim in its chunk.
- Unanswerable questions: checked by grep against the corpus.
- No page or PDF text is committed. Only the questions, keys, headings and short anchors are in git.

The corpus disagrees with itself in a few places:

- pre-approval validity: 45 vs 90 days
- minimum income for a personal loan: 510 EUR vs the minimum net wage
- mortgage down payment: 15–25% vs 15–35%
- the Casa Ta 5-year cost sheet contains the 3-year sheet's figures

Questions touching these list every source that states the fact. Grading of the
conflicting sources is not fully consistent across drafting batches. The
drafts' `notes` (outside the repo) explain each case.
