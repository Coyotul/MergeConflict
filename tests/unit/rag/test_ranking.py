"""Unit tests for the pure ranking functions of the retrieval service."""
from dataclasses import replace
from datetime import date, datetime, timezone
from itertools import count

import pytest

from src.core.settings import RagSettings
from src.models.knowledge import (
    Authority,
    ChunkKind,
    Citation,
    DocKind,
    Passage,
    PassageFlag,
    Product,
    Scores,
    Topic,
)
from src.services.retrieval.ranking import (
    apply_authority,
    apply_hub_deferral,
    dedupe_passages,
    detect_conflicts,
    passage_flags,
    passes_evidence_threshold,
    query_terms,
    rrf_fuse,
)
from src.storage.vector_index.repository import Candidate, PassageRow

_ids = count(1000)

BASE_ROW = PassageRow(
    chunk_id=1,
    document_id=1,
    doc_kind=DocKind.product_page,
    kind=ChunkKind.section,
    topic=Topic.costs_fees,
    products=[Product.personal_loan],
    authority=Authority.high,
    header="Raiffeisen Bank › Credit Demo · 2026-10-01",
    text="t",
    publisher="Raiffeisen Bank Romania",
    title="Credit Demo",
    url="https://www.raiffeisen.ro/ro/demo.html",
    canonical_key="/ro/demo.html",
    page=None,
    anchor=None,
    section_path=[],
    version_label="2026-10-01 (fetched_at)",
    effective_date=date(2026, 10, 1),
    fetched_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    campaign_valid_until=None,
    in_force=True,
    withdrawn=False,
)


def row(**overrides) -> PassageRow:
    """A PassageRow with sensible defaults and the given field overrides."""
    return replace(BASE_ROW, **overrides)


def passage(
    chunk_id: int | None = None,
    *,
    doc: int = 1,
    kind: DocKind = DocKind.product_page,
    chunk_kind: ChunkKind = ChunkKind.section,
    topic: Topic = Topic.costs_fees,
    products: list[Product] = [Product.personal_loan],
    text: str = "t",
) -> Passage:
    """A Passage with sensible defaults; ids auto-increment when chunk_id is None."""
    return Passage(
        chunk_id=next(_ids) if chunk_id is None else chunk_id,
        document_id=doc,
        doc_kind=kind,
        kind=chunk_kind,
        topic=topic,
        products=list(products),
        authority=Authority.high,
        header="Raiffeisen Bank › Demo · 2026-10-01",
        text=text,
        citation=Citation(
            publisher="Raiffeisen Bank Romania",
            title="Demo",
            url="https://www.raiffeisen.ro/ro/demo.html",
            canonical_key=f"/ro/demo-{doc}.html",
            section_path=[],
            effective_date=date(2026, 10, doc % 28 + 1),
            fetched_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        ),
        scores=Scores(fused=0.1),
    )


def test_query_terms_strip_stopwords_and_accents():
    assert query_terms("Există comision de rambursare anticipată?") == ["comision", "rambursare", "anticipata"]
    assert query_terms("& | ! : * ( ) '") == []


def test_query_terms_deduplicate_in_order():
    assert query_terms("Dobânda dobanda DAE și dae") == ["dobanda", "dae"]


def test_rrf_fuse():
    f = rrf_fuse([Candidate(1, .9), Candidate(2, .8)], [Candidate(2, .5), Candidate(3, .4)], k=60)
    assert f[2] == pytest.approx(1/62 + 1/61) and max(f, key=f.get) == 2


def test_rrf_fuse_scales_the_keyword_list_by_its_weight():
    f = rrf_fuse([Candidate(1, .9), Candidate(2, .8)], [Candidate(3, .5), Candidate(2, .4)], k=20, keyword_weight=0.3)
    assert f[1] == pytest.approx(1/21) and f[3] == pytest.approx(0.3/21)
    assert f[2] == pytest.approx(1/22 + 0.3/22)
    assert sorted(f, key=f.get, reverse=True) == [2, 1, 3]


def test_apply_authority_scales_by_weight():
    out = apply_authority({1: 0.02, 2: 0.02}, {1: Authority.high, 2: Authority.low}, {"high": 1.0, "medium": 0.9, "low": 0.75})
    assert out == {1: pytest.approx(0.02), 2: pytest.approx(0.015)}


def test_threshold_rewards_a_clear_best_match_over_a_flat_profile():
    s = RagSettings(dense_floor=0.74, dense_margin_weight=3.0, dense_margin_rank=10)
    strong_but_flat = [0.68, 0.675, 0.67, 0.67, 0.665, 0.66, 0.66, 0.655, 0.65, 0.65]   # 0.68 + 3 * 0.03 = 0.77
    near_miss = [0.66, 0.66, 0.655, 0.655, 0.65, 0.65, 0.65, 0.645, 0.645, 0.64]  # 0.66 + 3 * 0.02 = 0.72
    standout = [0.62, 0.58, 0.56, 0.55, 0.55, 0.54, 0.54, 0.53, 0.52, 0.52]  # 0.62 + 3 * 0.10 = 0.92
    assert passes_evidence_threshold(strong_but_flat, s)
    assert not passes_evidence_threshold(near_miss, s)
    assert passes_evidence_threshold(standout, s)
    assert not passes_evidence_threshold([], s)


def test_threshold_uses_the_last_score_when_fewer_than_margin_rank():
    s = RagSettings(dense_floor=0.74, dense_margin_weight=3.0, dense_margin_rank=10)
    assert passes_evidence_threshold([0.65, 0.60], s)        # 0.65 + 3 * 0.05 = 0.80
    assert not passes_evidence_threshold([0.70], s)          # no margin: 0.70 < 0.74


def test_default_settings_are_the_calibrated_values():
    s = RagSettings()
    assert (s.dense_floor, s.dense_margin_weight, s.dense_margin_rank) == (0.75, 3.0, 10)
    assert (s.rrf_k, s.keyword_weight, s.candidate_k) == (20, 0.3, 30)
    assert s.authority_weights == {"high": 1.0, "medium": 1.0, "low": 1.0}


def test_campaign_flags():
    flags, warns = passage_flags(row(campaign_valid_until=date(2026, 11, 26)), date(2026, 12, 1))
    assert PassageFlag.campaign_ended in flags
    assert warns == ["This page advertised a campaign that ended on 2026-11-26; its figures may be out of date until the page is re-fetched."]


def test_active_campaign_superseded_and_withdrawn_flags():
    flags, warns = passage_flags(row(campaign_valid_until=date(2026, 11, 26), in_force=False, withdrawn=True), date(2026, 11, 26))
    assert flags == [PassageFlag.superseded, PassageFlag.withdrawn, PassageFlag.campaign_active]
    assert warns == ["This page advertises a time-limited campaign running until 2026-11-26."]
    assert passage_flags(row(), date(2026, 11, 26)) == ([], [])


def test_conflicts_only_same_kind_topic_specific_product():
    a = passage(doc=1, kind=DocKind.cost_sheet, topic=Topic.costs_fees, products=[Product.personal_loan])
    b = passage(doc=2, kind=DocKind.cost_sheet, topic=Topic.costs_fees, products=[Product.personal_loan])
    c = passage(doc=3, kind=DocKind.product_page, topic=Topic.costs_fees, products=[Product.personal_loan])
    g = passage(doc=4, kind=DocKind.cost_sheet, topic=Topic.costs_fees, products=[Product.general])
    cs = detect_conflicts([a, b, c, g])
    assert len(cs) == 1 and cs[0].product is Product.personal_loan and sorted(cs[0].chunk_ids) == [a.chunk_id, b.chunk_id]


def test_conflicts_ignore_superseded_and_list_effective_dates():
    a = passage(doc=1, kind=DocKind.cost_sheet)
    b = passage(doc=2, kind=DocKind.cost_sheet)
    old = passage(doc=3, kind=DocKind.cost_sheet)
    old.flags = [PassageFlag.superseded]
    assert detect_conflicts([a, old]) == []
    [conflict] = detect_conflicts([a, b, old])
    assert conflict.chunk_ids == [a.chunk_id, b.chunk_id]
    assert conflict.effective_dates == [a.citation.effective_date, b.citation.effective_date]


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


def test_hub_deferral_skips_superseded_and_general_only_sheets():
    card = passage(1, kind=DocKind.category_hub, chunk_kind=ChunkKind.hub_card, products=[Product.personal_loan, Product.general])
    card.flags = [PassageFlag.teaser_figure]
    old = passage(5, doc=2, kind=DocKind.cost_sheet, products=[Product.personal_loan])
    old.flags = [PassageFlag.superseded]
    general = passage(6, doc=3, kind=DocKind.cost_sheet, products=[Product.general])
    apply_hub_deferral([card, old, general])
    assert card.defer_to is None and card.warnings == []
    apply_hub_deferral([card, old, general, passage(9, doc=4, kind=DocKind.cost_sheet), passage(10, doc=5, kind=DocKind.cost_sheet)])
    assert card.defer_to == 9


def test_dedupe_keeps_first():
    assert [p.chunk_id for p in dedupe_passages([passage(1, text="Dobânda fixă"), passage(2, text="dobanda  fixa")])] == [1]


def test_threshold_margin_is_against_the_margin_rank_not_the_tail():
    s = RagSettings(dense_floor=0.74, dense_margin_weight=3.0, dense_margin_rank=10)
    near_misses_then_noise = [0.66] + [0.655] * 8 + [0.645, 0.40, 0.30]   # 0.66 + 3 * 0.015 = 0.705
    assert not passes_evidence_threshold(near_misses_then_noise, s)
