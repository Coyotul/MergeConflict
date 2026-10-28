"""Retrieval evaluation over the labelled splits in config/rag/eval/ (format: config/rag/eval/README.md)."""
import math
import unicodedata
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from src.models.knowledge import DocKind, Passage, Product, SearchQuery, SearchResult, SearchStatus, Topic
from src.storage.vector_index.repository import fetch_in_force_chunks

NDCG_DEPTH = 10


class ExpectedSource(BaseModel):
    """One passage that answers a question: its document key plus anchors or a section hint."""
    model_config = ConfigDict(extra="ignore")
    canonical_key: str
    section_hint: str | None = None
    must_contain: list[str] = []
    grade: int = 2
    doc_kind: DocKind | None = None
    topic: Topic | None = None
    products: list[Product] | None = None


class EvalQuestion(BaseModel):
    """A labelled question; unanswerable ones expect status insufficient_evidence."""
    model_config = ConfigDict(extra="ignore")
    id: str
    question: str
    style: str
    answerable: bool = True
    unanswerable_kind: str | None = None
    expected: list[ExpectedSource] = []
    products: list[Product] | None = None
    all_topics: bool = False
    behaviour: list[str] = []
    group: str

    @field_validator("behaviour", mode="before")
    @classmethod
    def _behaviour_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        return [v] if isinstance(v, str) else v


class Breakdown(BaseModel):
    """Questions in one stratum and how many were handled correctly (hit in the top k, or refused)."""
    n: int = 0
    correct: int = 0
    rate: float = 0.0


class EvalReport(BaseModel):
    """Metrics of one evaluation run."""
    k: int
    recall_at_k: float
    mrr: float
    ndcg_at_10: float
    answerable_total: int
    false_refusals: int
    false_refusal_rate: float
    refusals_correct: int
    refusals_total: int
    refusal_accuracy: float
    breakdowns: dict[str, dict[str, Breakdown]]
    per_question: list[dict]


def _fold(text: str) -> str:
    """Accents stripped, lowercased, whitespace collapsed."""
    decomposed = unicodedata.normalize("NFD", text)
    return " ".join("".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower().split())


def _matches_chunk(key: str, section_path: list[str], text: str, expected: ExpectedSource) -> bool:
    if key != expected.canonical_key:
        return False
    if not expected.must_contain and not expected.section_hint:
        return True  # a label with only a document key matches any passage of that document
    folded = _fold(text)
    if expected.must_contain and all(_fold(anchor) in folded for anchor in expected.must_contain):
        return True
    return bool(expected.section_hint) and _fold(expected.section_hint) in _fold(" › ".join(section_path))


def matches(passage: Passage, expected: ExpectedSource) -> bool:
    """Same document (citation.canonical_key), and either every anchor is in the text or the hint is in the path."""
    c = passage.citation
    return _matches_chunk(c.canonical_key, c.section_path, passage.text, expected)


def load_eval_split(path: Path) -> list[EvalQuestion]:
    """Questions of one split file (tune.yaml or validation.yaml)."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [EvalQuestion.model_validate(q) for q in data["questions"]]


def _ndcg(passages: list[Passage], expected: list[ExpectedSource]) -> float:
    """Graded nDCG@10 with gain = grade; each expected entry is credited at most once."""
    credited: set[int] = set()
    dcg = 0.0
    for rank, p in enumerate(passages[:NDCG_DEPTH], start=1):
        candidates = [i for i, e in enumerate(expected) if i not in credited and matches(p, e)]
        if candidates:
            best = max(candidates, key=lambda i: expected[i].grade)
            credited.add(best)
            dcg += expected[best].grade / math.log2(rank + 1)
    ideal = sorted((e.grade for e in expected), reverse=True)[:NDCG_DEPTH]
    idcg = sum(g / math.log2(rank + 1) for rank, g in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def _tally(breakdowns: dict[str, dict[str, Breakdown]], dimension: str, value: str | None, correct: bool) -> None:
    if value is None:
        return
    b = breakdowns.setdefault(dimension, {}).setdefault(value, Breakdown())
    b.n += 1
    b.correct += int(correct)
    b.rate = b.correct / b.n


def _ratio(numerator: float, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate(
    search: Callable[[SearchQuery], SearchResult],
    questions: list[EvalQuestion],
    k: int = 5,
    as_of: date | None = None,
) -> EvalReport:
    """Run every question through search: recall@k, MRR@10, nDCG@10, refusal accuracy and false-refusal rate."""
    as_of = as_of or date.today()
    breakdowns: dict[str, dict[str, Breakdown]] = {}
    rows: list[dict] = []
    hits = false_refusals = refusals_correct = 0
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    answerable_total = sum(q.answerable for q in questions)

    for q in questions:
        result = search(SearchQuery(
            text=q.question,
            products=q.products,
            topics=list(Topic) if q.all_topics else None,
            top_k=max(k, NDCG_DEPTH),
            as_of=as_of,
        ))
        refused = result.status is SearchStatus.insufficient_evidence
        hit_rank = next(
            (rank for rank, p in enumerate(result.passages, start=1) if any(matches(p, e) for e in q.expected)),
            None,
        )
        row: dict[str, Any] = {
            "id": q.id, "question": q.question, "answerable": q.answerable, "status": str(result.status),
            "hit_rank": hit_rank,
            "top": [
                {"canonical_key": p.citation.canonical_key, "section_path": " › ".join(p.citation.section_path),
                 "fused": p.scores.fused}
                for p in result.passages[:k]
            ],
        }
        if q.answerable:
            hit = hit_rank is not None and hit_rank <= k
            hits += hit
            false_refusals += refused
            reciprocal_ranks.append(1 / hit_rank if hit_rank else 0.0)
            row["ndcg"] = _ndcg(result.passages, q.expected)
            ndcgs.append(row["ndcg"])
            primary = q.expected[0] if q.expected else None
            _tally(breakdowns, "style", q.style, hit)
            _tally(breakdowns, "doc_kind", str(primary.doc_kind) if primary and primary.doc_kind else None, hit)
            _tally(breakdowns, "topic", str(primary.topic) if primary and primary.topic else None, hit)
            for tag in q.behaviour:
                _tally(breakdowns, "behaviour", tag, hit)
        else:
            refusals_correct += refused
            _tally(breakdowns, "unanswerable_kind", q.unanswerable_kind or "unspecified", refused)
        rows.append(row)

    refusals_total = len(questions) - answerable_total
    return EvalReport(
        k=k,
        recall_at_k=_ratio(hits, answerable_total),
        mrr=_ratio(sum(reciprocal_ranks), answerable_total),
        ndcg_at_10=_ratio(sum(ndcgs), answerable_total),
        answerable_total=answerable_total,
        false_refusals=false_refusals,
        false_refusal_rate=_ratio(false_refusals, answerable_total),
        refusals_correct=refusals_correct,
        refusals_total=refusals_total,
        refusal_accuracy=_ratio(refusals_correct, refusals_total),
        breakdowns=breakdowns,
        per_question=rows,
    )


def check_labels(conn: psycopg.Connection, questions: list[EvalQuestion], as_of: date | None = None) -> list[str]:
    """Expected entries that no in-force indexed chunk matches, one line each."""
    chunks_by_key: dict[str, list[tuple[list[str], str]]] = {}
    for key, section_path, text in fetch_in_force_chunks(conn, as_of or date.today()):
        chunks_by_key.setdefault(key, []).append((section_path, text))
    unmatched: list[str] = []
    for q in questions:
        for e in q.expected:
            chunks = chunks_by_key.get(e.canonical_key, [])
            if not any(_matches_chunk(e.canonical_key, path, text, e) for path, text in chunks):
                reason = "document not indexed" if not chunks else "no chunk matches"
                unmatched.append(
                    f"{q.id}: {e.canonical_key} [{reason}] hint={e.section_hint!r} anchors={e.must_contain}"
                )
    return unmatched
