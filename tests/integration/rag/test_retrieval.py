"""Integration tests for the hybrid retrieval service (needs the rag-db container)."""
import os
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
import pytest

from src.core.errors import EmbeddingModelUnavailable, KnowledgeStoreUnavailable
from src.core.settings import RagSettings
from src.models.knowledge import (
    CREDIT_TOPICS,
    ChunkKind,
    DocKind,
    LinkKind,
    PassageFlag,
    Product,
    SearchQuery,
    SearchStatus,
    Topic,
)
from src.services.document_ingestion.manifest import ManifestEntry
from src.services.document_ingestion.metadata import canonical_key
from src.services.document_ingestion.pipeline import IngestionPipeline, IngestOutcome
from src.services.document_ingestion.sources import load_source_config
from src.services.retrieval.service import RetrievalService
from src.storage.document_store.raw_store import save_raw
from src.storage.document_store.repository import DocumentRepository
from tests.fixtures.rag.pdf_builders import build_demo_cost_sheet, make_pdf
from tests.support.fake_embedder import HashingEmbedder

CFG = load_source_config(Path("config/rag/sources.yaml"))
SITE = "https://www.raiffeisen.ro"
CREDITE = SITE + "/ro/persoane-fizice/produsele-noastre/credite/"
DOCS = SITE + "/content/dam/rbi/retail/eu/ro/documents/"
PAGE_URL = CREDITE + "credit-de-nevoi-personale-fara-ipoteca.html"
FAQ_URL = CREDITE + "intrebari-frecvente-credit-nevoi-personale.html"
HUB_URL = CREDITE + "credite-de-nevoi-personale.html"
COST_SHEET_URL = DOCS + "costuri/costuri-complete-flexicredit-demo/20261015-x.pdf"
FEE_URL = DOCS + "pf/tarife-comisioane-standard-pf.sv.pdf"
FIXTURES = Path("tests/fixtures/rag")
TEST_URL = os.getenv("RAG_TEST_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5433/rag_test")
FETCHED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
D = date(2026, 10, 28)

# Fee list v1 and v2 differ in one payments row: label and fee value.
V1_FEE = ("Transfer demo urgent", "3 lei")
V2_FEE = ("Transfer demo programat", "5 lei")


def fee_list_pdf(date_text: str, payment_row: tuple[str, str]) -> bytes:
    return make_pdf([
        [(50, 80, "Tarife și comisioane Demo"), (50, 100, f"Valabil din {date_text}")],
        [
            (50, 60, "1. Conturi demo"),
            (50, 80, "1.1. Cont curent demo"),
            (50, 100, "Tip"), (300, 100, "Comision"),
            (50, 120, "Deschidere cont curent demo"), (300, 120, "0 lei"),
            (50, 140, "2. Plăți demo"),
            (50, 160, payment_row[0]), (300, 160, payment_row[1]),
        ],
    ])


@pytest.fixture
def settings():
    # HashingEmbedder scores are lexical and the synthetic corpus is tiny, so the evidence rule keeps its
    # shape (best dense + margin bonus) with values for this embedder: the margin is over the 2nd score.
    return RagSettings(database_url=TEST_URL, dense_floor=0.45, dense_margin_weight=3.0, dense_margin_rank=2)


@pytest.fixture
def service(db_conn, tmp_path, settings):
    """Ingest the synthetic corpus (overdraft.html deliberately not ingested) and return a service."""
    docs = [
        (PAGE_URL, (FIXTURES / "product_page.html").read_bytes(), ".html"),
        (FAQ_URL, (FIXTURES / "faq_page.html").read_bytes(), ".html"),
        (HUB_URL, (FIXTURES / "category_hub.html").read_bytes(), ".html"),
        (COST_SHEET_URL, build_demo_cost_sheet(), ".pdf"),
        (FEE_URL, fee_list_pdf("1 septembrie 2026", V1_FEE), ".pdf"),
        (FEE_URL, fee_list_pdf("1 noiembrie 2026", V2_FEE), ".pdf"),
    ]
    entries = []
    for url, data, ext in docs:
        sha, path = save_raw(tmp_path, data, ext)
        entries.append(ManifestEntry(url=url, final_url=url, fetched_at=FETCHED_AT, status_code=200, content_type=None,
                                     sitemap_lastmod=None, sha256=sha, raw_path=path.name))
    rep = IngestionPipeline(db_conn, HashingEmbedder(), CFG).ingest_entries(entries, tmp_path)
    assert set(rep.outcomes.values()) == {IngestOutcome.created} and rep.errors == {}
    assert db_conn.execute("select count(*) from knowledge_document_versions").fetchone()[0] == 6
    db_conn.commit()
    return RetrievalService(lambda: psycopg.connect(TEST_URL), HashingEmbedder(), settings)


def stored_key(db_conn, url):
    key = db_conn.execute("select canonical_key from knowledge_documents where source_url = %s", (url,)).fetchone()[0]
    db_conn.commit()
    return key


def test_search_returns_cited_passages(service, db_conn):
    r = service.search(SearchQuery(text="comision analiză dosar Demoflex", as_of=date(2026, 10, 28)))
    assert r.status is SearchStatus.ok and r.passages
    top = r.passages[0]
    assert top.citation.publisher == "Raiffeisen Bank Romania" and top.citation.url.startswith("https://")
    assert top.header.startswith("Raiffeisen Bank › ") and r.content_trust == "untrusted_evidence"
    assert top.doc_kind is DocKind.cost_sheet and top.citation.url == COST_SHEET_URL
    assert top.citation.canonical_key == stored_key(db_conn, COST_SHEET_URL)
    assert top.citation.effective_date == date(2026, 10, 1) and top.citation.title == "Demoflex Fara Asigurare"
    assert top.scores.dense is not None and top.scores.keyword is not None and top.scores.fused > 0
    assert r.index_info is not None and r.index_info.embedding_model == "hashing-test"


def test_unaccented_query_matches(service):
    r = service.search(SearchQuery(text="dobanda fixa Demoflex", as_of=D))
    assert r.status is SearchStatus.ok
    # The keyword retriever matches the accented text itself, not only the "Demoflex" token.
    assert any("dobândă fixă" in p.text and "Demoflex" not in p.text and p.scores.keyword for p in r.passages)


def test_version_in_force_by_effective_date(service):
    v1, v2 = V1_FEE[0], V2_FEE[0]
    before = service.search(SearchQuery(text=v1, topics=list(Topic), as_of=date(2026, 10, 1)))
    fee_before = [p for p in before.passages if p.doc_kind is DocKind.fee_list]
    assert fee_before and all(p.citation.effective_date == date(2026, 9, 1) for p in fee_before)
    assert any(v1 in p.text for p in fee_before) and not any(v2 in p.text for p in fee_before)

    after = service.search(SearchQuery(text=v2, topics=list(Topic), as_of=date(2026, 11, 15)))
    fee_after = [p for p in after.passages if p.doc_kind is DocKind.fee_list]
    assert fee_after and all(p.citation.effective_date == date(2026, 11, 1) for p in fee_after)
    assert any(v2 in p.text for p in fee_after) and not any(v1 in p.text for p in fee_after)
    assert not any(PassageFlag.superseded in p.flags for p in fee_after)

    both = service.search(SearchQuery(text=v1, topics=list(Topic), as_of=date(2026, 11, 15), include_superseded=True))
    old = [p for p in both.passages if v1 in p.text]
    assert old and all(PassageFlag.superseded in p.flags for p in old)


def test_future_dated_version_excluded(service):
    r = service.search(SearchQuery(text=V2_FEE[0], topics=list(Topic), as_of=date(2026, 10, 1), include_superseded=True))
    fee = [p for p in r.passages if p.doc_kind is DocKind.fee_list]
    assert fee and all(p.citation.effective_date == date(2026, 9, 1) for p in fee)
    assert not any(V2_FEE[0] in p.text for p in r.passages)


def test_default_scope_excludes_non_credit_topics(service):
    r = service.search(SearchQuery(text="deschidere cont curent demo", as_of=D))
    assert all(p.topic in CREDIT_TOPICS for p in r.passages)
    # The phrase does find the accounts row once every topic is in scope.
    wide = service.search(SearchQuery(text="deschidere cont curent demo", topics=list(Topic), as_of=D))
    assert any(p.topic is Topic.accounts for p in wide.passages)


def test_unrelated_query_is_insufficient_evidence(service):
    r = service.search(SearchQuery(text="rețetă de clătite cu ciocolată", as_of=D))
    assert r.status is SearchStatus.insufficient_evidence and r.passages == []
    assert r.index_info is not None


def test_query_with_tsquery_operators_is_safe(service):
    r = service.search(SearchQuery(text="DAE & (comision | 'dobândă') :* !", as_of=D))   # no exception
    assert r.status is SearchStatus.ok


def test_campaign_flag_after_end(service):
    phrase = "Perioada campaniei Credit Demo acte"
    r = service.search(SearchQuery(text=phrase, as_of=date(2026, 12, 1)))
    assert any(PassageFlag.campaign_ended in p.flags for p in r.passages)
    during = service.search(SearchQuery(text=phrase, as_of=D))
    assert any(PassageFlag.campaign_active in p.flags for p in during.passages)
    assert not any(PassageFlag.campaign_ended in p.flags for p in during.passages)


def test_withdrawn_excluded_by_default(service, db_conn):
    phrase = "Vârstă între 20 și 60 de ani venit minim"
    key = stored_key(db_conn, PAGE_URL)
    assert any(p.citation.canonical_key == key for p in service.search(SearchQuery(text=phrase, as_of=D)).passages)
    DocumentRepository(db_conn).mark_withdrawn([key])
    db_conn.commit()
    r = service.search(SearchQuery(text=phrase, as_of=D))
    assert not any(p.citation.canonical_key == key for p in r.passages)
    w = service.search(SearchQuery(text=phrase, as_of=D, include_withdrawn=True))
    page = [p for p in w.passages if p.citation.canonical_key == key]
    assert page and all(PassageFlag.withdrawn in p.flags for p in page)


def test_related_links_resolve_only_to_indexed_active_targets(service, db_conn):
    r = service.search(SearchQuery(text="Credit Demo fără ipotecă Aplici ușor", doc_kinds=[DocKind.category_hub], as_of=D))
    cards = {p.text.splitlines()[0]: p for p in r.passages if p.kind is ChunkKind.hub_card}
    assert [l.url for l in cards["Credit Demo fără ipotecă"].related_links] == [PAGE_URL]
    link = cards["Credit Demo fără ipotecă"].related_links[0]
    assert link.link_kind is LinkKind.card
    assert link.title == "Credit Demo" and link.canonical_key == stored_key(db_conn, PAGE_URL)
    assert cards.get("Overdraft Demo") is None or cards["Overdraft Demo"].related_links == []   # target not indexed
    DocumentRepository(db_conn).mark_withdrawn([canonical_key(PAGE_URL)]); db_conn.commit()
    r2 = service.search(SearchQuery(text="Credit Demo fără ipotecă Aplici ușor", doc_kinds=[DocKind.category_hub], as_of=D))
    assert any(p.kind is ChunkKind.hub_card for p in r2.passages)
    assert all(not p.related_links for p in r2.passages if p.kind is ChunkKind.hub_card)


def test_related_links_need_a_target_version_in_force(service, db_conn):
    # Date the product page after the hub: on 2026-10-22 the card is in force but its target is not yet.
    db_conn.execute("update knowledge_document_versions v set effective_from = '2026-10-25' from knowledge_documents d "
                    "where d.id = v.document_id and d.source_url = %s", (PAGE_URL,))
    db_conn.commit()
    q = dict(text="Credit Demo fără ipotecă Aplici ușor", doc_kinds=[DocKind.category_hub])
    early = [p for p in service.search(SearchQuery(as_of=date(2026, 10, 22), **q)).passages if p.kind is ChunkKind.hub_card]
    assert early and all(not p.related_links for p in early)
    late = [p for p in service.search(SearchQuery(as_of=date(2026, 10, 25), **q)).passages if p.kind is ChunkKind.hub_card]
    assert [l.url for p in late for l in p.related_links] == [PAGE_URL]


def test_hub_card_defers_to_cost_sheet(service):
    r = service.search(SearchQuery(text="Dobândă de la 6,10% Demoflex comision analiză", products=[Product.personal_loan], top_k=10, as_of=D))
    card = next(p for p in r.passages if p.kind is ChunkKind.hub_card)
    sheet = next(p for p in r.passages if p.doc_kind is DocKind.cost_sheet)
    assert PassageFlag.teaser_figure in card.flags and card.defer_to == sheet.chunk_id
    assert not any(c.doc_kind is DocKind.category_hub for c in r.conflicts)


def test_expand_context(service):
    phrase = "Opțiunea Avantaj rambursare anticipată gratuită"
    r = service.search(SearchQuery(text=phrase, as_of=D, expand_context=True))
    top = r.passages[0]
    assert top.text.startswith("Exemplu de calcul pentru Opțiunea Avantaj")
    assert top.context and (top.context.previous or top.context.next)
    assert top.context.previous.startswith("Exemplu de calcul pentru Opțiunea Standard")
    assert top.context.next.startswith("Întrebare: Pot rambursa anticipat?")
    assert service.search(SearchQuery(text=phrase, as_of=D)).passages[0].context is None


def test_search_raises_typed_errors(settings, db_conn):   # db_conn: skip when the test DB is down
    class Broken(HashingEmbedder):
        def embed_query(self, t): raise RuntimeError("x")
    with pytest.raises(EmbeddingModelUnavailable):
        RetrievalService(lambda: psycopg.connect(TEST_URL), Broken(), settings).search(SearchQuery(text="dae"))
    with pytest.raises(KnowledgeStoreUnavailable):
        RetrievalService(lambda: psycopg.connect("postgresql://rag:rag@127.0.0.1:1/none", connect_timeout=2), HashingEmbedder(), settings).search(SearchQuery(text="dae"))

    def dropped_connection():
        """A connection whose server session is killed before the service queries it."""
        conn = psycopg.connect(TEST_URL)
        with psycopg.connect(TEST_URL, autocommit=True) as admin:
            admin.execute("select pg_terminate_backend(%s)", (conn.info.backend_pid,))
        return conn
    with pytest.raises(KnowledgeStoreUnavailable):
        RetrievalService(dropped_connection, HashingEmbedder(), settings).search(SearchQuery(text="dae"))
