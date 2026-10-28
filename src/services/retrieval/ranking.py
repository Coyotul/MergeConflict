"""Pure ranking steps of hybrid retrieval: terms, fusion, thresholds, flags, deferral and conflicts."""
import re
import unicodedata
from collections.abc import Mapping
from datetime import date

from src.core.settings import RagSettings
from src.models.knowledge import Authority, ChunkKind, Conflict, DocKind, Passage, PassageFlag, Product, Topic
from src.storage.vector_index.repository import Candidate, PassageRow


def _fold(text: str) -> str:
    """Strip accents and lowercase."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


RO_STOPWORDS: frozenset[str] = frozenset(_fold(w) for w in (
    "și si sau de la în in pe cu un o ce care este sunt pentru din mi îmi imi pot am ai a al ale lui "
    "să sa nu da cum cât cat dacă daca mai există exista trebuie fi se eu tu meu mea vreau vrea"
).split())


def query_terms(text: str) -> list[str]:
    """Accent-stripped lowercase word tokens of 2+ characters, minus stopwords, deduplicated in order."""
    terms: list[str] = []
    for token in re.findall(r"\w{2,}", _fold(text)):
        if token not in RO_STOPWORDS and token not in terms:
            terms.append(token)
    return terms


def rrf_fuse(dense: list[Candidate], keyword: list[Candidate], k: int) -> dict[int, float]:
    """Reciprocal rank fusion: each list adds 1 / (k + rank) to a chunk, ranks starting at 1."""
    fused: dict[int, float] = {}
    for candidates in (dense, keyword):
        for rank, candidate in enumerate(candidates, start=1):
            fused[candidate.chunk_id] = fused.get(candidate.chunk_id, 0.0) + 1 / (k + rank)
    return fused


def apply_authority(
    fused: dict[int, float], authority: dict[int, Authority], weights: Mapping[str, float]
) -> dict[int, float]:
    """Scale each fused score by the weight of its chunk's authority."""
    return {chunk_id: score * weights[str(authority[chunk_id])] for chunk_id, score in fused.items()}


def passes_evidence_threshold(
    best_dense: float | None, best_keyword: float | None, keyword_top_dense: float | None, s: RagSettings
) -> bool:
    """Enough evidence: a strong dense hit, or a strong keyword hit that is also semantically close."""
    if best_dense is not None and best_dense >= s.dense_floor:
        return True
    return (
        best_keyword is not None and best_keyword >= s.keyword_floor
        and keyword_top_dense is not None and keyword_top_dense >= s.secondary_dense_floor
    )


def _comparable_text(text: str) -> str:
    return " ".join(_fold(text).split())


def dedupe_passages(passages: list[Passage]) -> list[Passage]:
    """Drop passages whose text repeats an earlier one (accents, case and whitespace ignored)."""
    seen: set[str] = set()
    kept: list[Passage] = []
    for p in passages:
        key = _comparable_text(p.text)
        if key not in seen:
            seen.add(key)
            kept.append(p)
    return kept


def passage_flags(row: PassageRow, as_of: date) -> tuple[list[PassageFlag], list[str]]:
    """Flags and warnings for a passage's version state, authority, chunk kind and campaign window."""
    flags: list[PassageFlag] = []
    warnings: list[str] = []
    if not row.in_force:
        flags.append(PassageFlag.superseded)
    if row.withdrawn:
        flags.append(PassageFlag.withdrawn)
    if row.authority is Authority.low:
        flags.append(PassageFlag.low_authority)
    if row.kind is ChunkKind.hub_card:
        flags.append(PassageFlag.teaser_figure)
    d = row.campaign_valid_until
    if d is not None and d >= as_of:
        flags.append(PassageFlag.campaign_active)
        warnings.append(f"This page advertises a time-limited campaign running until {d:%Y-%m-%d}.")
    elif d is not None:
        flags.append(PassageFlag.campaign_ended)
        warnings.append(
            f"This page advertised a campaign that ended on {d:%Y-%m-%d}; "
            "its figures may be out of date until the page is re-fetched."
        )
    return flags, warnings


def _specific_products(p: Passage) -> set[Product]:
    return set(p.products) - {Product.general}


def apply_hub_deferral(passages: list[Passage]) -> None:
    """Point each teaser-figure passage at the best-ranked current cost sheet passage for its product."""
    for p in passages:
        if PassageFlag.teaser_figure not in p.flags:
            continue
        sheet = next(
            (
                s for s in passages
                if s.doc_kind is DocKind.cost_sheet
                and PassageFlag.superseded not in s.flags
                and _specific_products(s) & _specific_products(p)
            ),
            None,
        )
        if sheet is not None:
            p.defer_to = sheet.chunk_id
            p.warnings.append(
                f"Teaser figure; the cost sheet passage {sheet.chunk_id} holds the authoritative rates and fees."
            )


def detect_conflicts(passages: list[Passage]) -> list[Conflict]:
    """Current passages of one doc kind, topic and specific product that come from 2+ documents."""
    groups: dict[tuple[DocKind, Topic, Product], list[Passage]] = {}
    for p in passages:
        if PassageFlag.superseded in p.flags:
            continue
        for product in p.products:
            if product is not Product.general:
                groups.setdefault((p.doc_kind, p.topic, product), []).append(p)
    return [
        Conflict(
            doc_kind=doc_kind,
            topic=topic,
            product=product,
            chunk_ids=[p.chunk_id for p in group],
            effective_dates=[p.citation.effective_date for p in group],
        )
        for (doc_kind, topic, product), group in groups.items()
        if len({p.document_id for p in group}) >= 2
    ]
