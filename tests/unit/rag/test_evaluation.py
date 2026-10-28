"""Unit tests for the retrieval evaluation: matching rule, metrics and breakdowns, with a fake search."""
import math
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.models.knowledge import (
    Authority,
    ChunkKind,
    Citation,
    DocKind,
    Passage,
    Product,
    Scores,
    SearchQuery,
    SearchResult,
    SearchStatus,
    Topic,
)
from src.services.retrieval.evaluation import (
    EvalQuestion,
    ExpectedSource,
    evaluate,
    load_eval_split,
    matches,
)


def passage(key: str, text: str = "text demo", section_path: list[str] | None = None, chunk_id: int = 1) -> Passage:
    return Passage(
        chunk_id=chunk_id,
        document_id=1,
        doc_kind=DocKind.product_page,
        kind=ChunkKind.section,
        topic=Topic.costs_fees,
        products=[Product.personal_loan],
        authority=Authority.high,
        header="Raiffeisen Bank › Credit Demo",
        text=text,
        citation=Citation(
            publisher="Raiffeisen Bank Romania",
            title="Credit Demo",
            # Deliberately not derivable from the key: matching must use citation.canonical_key.
            url="https://www.raiffeisen.ro/content/dam/demo/20260901-file.pdf",
            canonical_key=key,
            section_path=section_path or [],
            effective_date=date(2026, 10, 1),
            fetched_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        ),
        scores=Scores(fused=0.5),
    )


def q(id: str, keys: list[tuple[str, int]] | None = None, *, answerable: bool = True, **extra) -> EvalQuestion:
    expected = [ExpectedSource(canonical_key=k, grade=g) for k, g in (keys or [])]
    return EvalQuestion(id=id, question=f"intrebare {id}", style=extra.pop("style", "formal"),
                        answerable=answerable, expected=expected, group=id, **extra)


def fake_search(results: dict[str, SearchResult], seen: list[SearchQuery] | None = None):
    def search(query: SearchQuery) -> SearchResult:
        if seen is not None:
            seen.append(query)
        return results[query.text]
    return search


def ok(*keys: str) -> SearchResult:
    return SearchResult(status=SearchStatus.ok,
                        passages=[passage(k, chunk_id=i) for i, k in enumerate(keys, start=1)])


REFUSED = SearchResult(status=SearchStatus.insufficient_evidence)


# --- matches ---------------------------------------------------------------------------------

def test_matches_folds_accents_and_case_in_anchors():
    p = passage("/ro/demo.html", text="Comisionul de ANALIZĂ este 0 lei la Dobânda  Fixă Demo.")
    assert matches(p, ExpectedSource(canonical_key="/ro/demo.html", must_contain=["comisionul de analiza", "dobanda fixa demo"]))


def test_matches_needs_every_anchor():
    p = passage("/ro/demo.html", text="Comisionul de analiză este 0 lei.")
    assert not matches(p, ExpectedSource(canonical_key="/ro/demo.html", must_contain=["comisionul", "dobândă fixă"]))


def test_matches_by_section_hint_when_anchors_are_missing():
    p = passage("/ro/demo.html", text="alt text", section_path=["Credit Demo", "Întrebări frecvente", "Ce acte îmi trebuie?"])
    assert matches(p, ExpectedSource(canonical_key="/ro/demo.html", section_hint="intrebari FRECVENTE › ce acte",
                                     must_contain=["absent"]))


def test_matches_rejects_other_document_even_when_text_matches():
    p = passage("/ro/alt.html", text="Comisionul de analiză", section_path=["Credit Demo"])
    assert not matches(p, ExpectedSource(canonical_key="/ro/demo.html", section_hint="Credit Demo",
                                         must_contain=["comisionul"]))


def test_matches_uses_citation_canonical_key_not_url():
    p = passage("/content/dam/demo/shared/file")
    assert matches(p, ExpectedSource(canonical_key="/content/dam/demo/shared/file"))
    assert not matches(p, ExpectedSource(canonical_key="/content/dam/demo"))


# --- metrics ---------------------------------------------------------------------------------

def test_evaluate_recall_mrr_and_refusals():
    qs = [q("a", [("/ro/x.html", 2)]), q("b", [("/ro/y.html", 2)]), q("c", answerable=False, unanswerable_kind="off_domain")]
    search = fake_search({"intrebare a": ok("/ro/o.html", "/ro/x.html"), "intrebare b": ok("/ro/o.html"),
                          "intrebare c": REFUSED})
    rep = evaluate(search, qs, k=5, as_of=date(2026, 10, 28))
    assert rep.recall_at_k == 0.5
    assert rep.mrr == pytest.approx(0.25)
    assert (rep.refusals_correct, rep.refusals_total) == (1, 1)
    assert rep.refusal_accuracy == 1.0


def test_hit_beyond_k_counts_for_mrr_but_not_recall():
    keys = [f"/ro/o{i}.html" for i in range(5)] + ["/ro/x.html"]
    rep = evaluate(fake_search({"intrebare a": ok(*keys)}), [q("a", [("/ro/x.html", 2)])], k=5)
    assert rep.recall_at_k == 0.0
    assert rep.mrr == pytest.approx(1 / 6)


def test_ndcg_uses_graded_labels_and_credits_each_label_once():
    qs = [q("a", [("/ro/x.html", 2), ("/ro/y.html", 1)])]
    # ranks: y (grade 1) at 1, x duplicate at 2 and 3 (credited once), nothing else
    rep = evaluate(fake_search({"intrebare a": ok("/ro/y.html", "/ro/x.html", "/ro/x.html")}), qs)
    dcg = 1 / math.log2(2) + 2 / math.log2(3)
    idcg = 2 / math.log2(2) + 1 / math.log2(3)
    assert rep.ndcg_at_10 == pytest.approx(dcg / idcg)


def test_false_refusals_counted_over_answerable():
    qs = [q("a", [("/ro/x.html", 2)]), q("b", [("/ro/x.html", 2)]), q("c", [("/ro/x.html", 2)]),
          q("d", [("/ro/x.html", 2)]), q("u", answerable=False)]
    results = {"intrebare a": REFUSED, "intrebare b": ok("/ro/x.html"), "intrebare c": ok("/ro/x.html"),
               "intrebare d": ok("/ro/x.html"), "intrebare u": ok("/ro/x.html")}
    rep = evaluate(fake_search(results), qs)
    assert (rep.false_refusals, rep.answerable_total) == (1, 4)
    assert rep.false_refusal_rate == pytest.approx(0.25)
    assert (rep.refusals_correct, rep.refusals_total) == (0, 1)
    assert rep.recall_at_k == pytest.approx(0.75)


def test_breakdowns_by_style_doc_kind_behaviour_and_unanswerable_kind():
    a = q("a", style="keyword", behaviour=["teaser_figure"])
    a.expected = [ExpectedSource(canonical_key="/ro/x.html", doc_kind=DocKind.cost_sheet, topic=Topic.costs_fees)]
    b = q("b", [("/ro/y.html", 2)], style="keyword")
    u = q("u", answerable=False, unanswerable_kind="competitor", style="formal")
    rep = evaluate(fake_search({"intrebare a": ok("/ro/x.html"), "intrebare b": ok("/ro/o.html"), "intrebare u": REFUSED}),
                   [a, b, u])
    assert rep.breakdowns["style"]["keyword"].model_dump() == {"n": 2, "correct": 1, "rate": 0.5}
    assert rep.breakdowns["doc_kind"]["cost_sheet"].correct == 1
    assert rep.breakdowns["topic"]["costs_fees"].n == 1
    assert rep.breakdowns["behaviour"]["teaser_figure"].model_dump() == {"n": 1, "correct": 1, "rate": 1.0}
    assert rep.breakdowns["unanswerable_kind"]["competitor"].model_dump() == {"n": 1, "correct": 1, "rate": 1.0}
    assert "formal" not in rep.breakdowns["style"]  # unanswerable questions only count under unanswerable_kind


def test_query_built_from_question_fields():
    seen: list[SearchQuery] = []
    qs = [q("a", [("/ro/x.html", 2)], products=[Product.personal_loan]), q("b", [("/ro/x.html", 2)], all_topics=True)]
    evaluate(fake_search({"intrebare a": ok(), "intrebare b": ok()}, seen), qs, k=5, as_of=date(2026, 10, 28))
    assert seen[0].products == [Product.personal_loan] and seen[0].topics is None
    assert seen[0].top_k == 10 and seen[0].as_of == date(2026, 10, 28)
    assert set(seen[1].topics) == set(Topic)


def test_per_question_rows_list_top_passages():
    rep = evaluate(fake_search({"intrebare a": ok("/ro/o.html", "/ro/x.html")}), [q("a", [("/ro/x.html", 2)])])
    row = rep.per_question[0]
    assert row["id"] == "a" and row["hit_rank"] == 2 and row["status"] == "ok"
    assert [t["canonical_key"] for t in row["top"]] == ["/ro/o.html", "/ro/x.html"]
    assert row["top"][0]["fused"] == 0.5


def test_load_eval_split_tolerates_extra_keys_and_list_behaviour(tmp_path: Path):
    path = tmp_path / "split.yaml"
    path.write_text(
        "version: 1\nquestions:\n"
        "- id: t-1\n  question: Ce este demo?\n  style: formal\n  answerable: true\n  behaviour: [campaign]\n"
        "  extra_field: ignored\n  group: g1\n"
        "  expected:\n  - canonical_key: /ro/demo.html\n    section_hint: Demo\n    must_contain: [demo]\n"
        "    grade: 1\n    doc_kind: guide\n    topic: eligibility\n    products: [general]\n    chunk_kind: section\n"
        "- id: t-2\n  question: Cat e ceasul?\n  style: colloquial\n  answerable: false\n"
        "  unanswerable_kind: off_domain\n  expected: []\n  group: u1\n",
        encoding="utf-8",
    )
    first, second = load_eval_split(path)
    assert first.behaviour == ["campaign"] and first.expected[0].grade == 1
    assert first.expected[0].doc_kind is DocKind.guide
    assert second.answerable is False and second.unanswerable_kind == "off_domain"
