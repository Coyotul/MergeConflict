"""Integration tests for the versioned ingestion pipeline (needs the rag-db container)."""
import os
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg

from src.services.document_ingestion.chunking import CHUNKER_VERSION
from src.services.document_ingestion.manifest import ManifestEntry
from src.services.document_ingestion.pipeline import IngestionPipeline, IngestOutcome
from src.services.document_ingestion.sources import load_source_config
from src.storage.document_store.raw_store import save_raw
from tests.fixtures.rag.pdf_builders import make_pdf, make_pdf_from_lines
from tests.support.fake_embedder import HashingEmbedder

CFG = load_source_config(Path("config/rag/sources.yaml"))
SITE = "https://www.raiffeisen.ro"
CREDITE = SITE + "/ro/persoane-fizice/produsele-noastre/credite/"
DOCS = SITE + "/content/dam/rbi/retail/eu/ro/documents/pf/"
PRODUCT_URL = CREDITE + "credit-de-nevoi-personale-fara-ipoteca.html"
HUB_URL = CREDITE + "credite-de-nevoi-personale.html"
FEE_URL = DOCS + "tarife-comisioane-standard-pf.sv.pdf"
PDF_URL = DOCS + "credite/informare-demo.pdf"
FIXTURES = Path("tests/fixtures/rag")
PRODUCT_HTML = (FIXTURES / "product_page.html").read_bytes()
HUB_HTML = (FIXTURES / "category_hub.html").read_bytes()
TEST_DB_URL = os.getenv("RAG_TEST_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5433/rag_test")
FETCHED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)


def entry(url, sha="h1", **kw):
    """A fetched (200) manifest entry with a raw_path."""
    fields = dict(url=url, final_url=url, fetched_at=FETCHED_AT, status_code=200, content_type=None,
                  sitemap_lastmod=None, sha256=sha, raw_path=f"{sha}.bin")
    fields.update(kw)
    return ManifestEntry(**fields)


def fee_list_pdf(date_text: str, first_section: str = "1. Conturi demo") -> bytes:
    return make_pdf([
        [(50, 80, "Tarife și comisioane Demo")],
        [
            (50, 40, f"Valabil din {date_text}"),  # the fee-list parser reads dates from page 2 on
            (50, 60, first_section),
            (50, 80, "1.1. Produs demo"),
            (50, 100, "Tip"), (300, 100, "Comision"),
            (50, 120, "Emitere demo"), (300, 120, "0 lei"),
            (50, 140, "2. Plăți demo"),
            (50, 160, "Transfer demo"), (300, 160, "3 lei"),
        ],
    ])


def count(conn, table):
    return conn.execute(f"select count(*) from {table}").fetchone()[0]


def test_ingest_creates_document_version_and_chunks(db_conn, tmp_path):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    out, _ = p.ingest_one(entry(PRODUCT_URL), PRODUCT_HTML)
    assert out is IngestOutcome.created
    n, = db_conn.execute("select count(*) from knowledge_chunks").fetchone()
    hdr, = db_conn.execute("select header from knowledge_chunks order by ordinal limit 1").fetchone()
    assert n > 3 and hdr.startswith("Raiffeisen Bank › ")
    prev_null, = db_conn.execute("select count(*) from knowledge_chunks where prev_chunk_id is null").fetchone()
    assert prev_null == 1
    # The neighbour chain follows ordinal order in both directions.
    rows = db_conn.execute("select id, prev_chunk_id, next_chunk_id from knowledge_chunks order by ordinal").fetchall()
    ids = [r[0] for r in rows]
    assert [r[1] for r in rows] == [None] + ids[:-1]
    assert [r[2] for r in rows] == ids[1:] + [None]
    key, status, kind = db_conn.execute("select canonical_key, status, doc_kind from knowledge_documents").fetchone()
    assert (key, status, kind) == ("/ro/persoane-fizice/produsele-noastre/credite/credit-de-nevoi-personale-fara-ipoteca.html",
                                   "active", "product_page")


def test_reingest_same_content_is_unchanged(db_conn):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    first, _ = p.ingest_one(entry(PRODUCT_URL), PRODUCT_HTML)
    chunks_after_first = count(db_conn, "knowledge_chunks")
    second, _ = p.ingest_one(entry(PRODUCT_URL), PRODUCT_HTML)
    assert (first, second) == (IngestOutcome.created, IngestOutcome.unchanged)
    assert count(db_conn, "knowledge_document_versions") == 1
    assert count(db_conn, "knowledge_chunks") == chunks_after_first


def test_alias_and_dated_pdf_share_one_version(db_conn):
    # same bytes under ".../tarife-demo.sv.pdf" and ".../tarife-demo/20260901-x.pdf.coredownload.pdf"
    data = fee_list_pdf("1 septembrie 2026")
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    outcomes = [p.ingest_one(entry(DOCS + "tarife-demo.sv.pdf"), data)[0],
                p.ingest_one(entry(DOCS + "tarife-demo/20260901-x.pdf.coredownload.pdf"), data)[0]]
    assert outcomes == [IngestOutcome.created, IngestOutcome.unchanged]
    assert db_conn.execute("select count(*) from knowledge_document_versions").fetchone()[0] == 1
    assert count(db_conn, "knowledge_documents") == 1


def test_changed_content_adds_version_with_effective_dates(db_conn):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    first, _ = p.ingest_one(entry(FEE_URL, sha="v1"), fee_list_pdf("1 septembrie 2026"))
    second, _ = p.ingest_one(entry(FEE_URL, sha="v2"), fee_list_pdf("1 noiembrie 2026"))
    assert (first, second) == (IngestOutcome.created, IngestOutcome.created)
    rows = db_conn.execute("select effective_from from knowledge_document_versions order by effective_from").fetchall()
    assert [r[0] for r in rows] == [date(2026, 9, 1), date(2026, 11, 1)]
    labels = [r[0] for r in db_conn.execute("select version_label from knowledge_document_versions order by effective_from")]
    assert labels == ["2026-09-01 (document_text)", "2026-11-01 (document_text)"]
    assert count(db_conn, "knowledge_documents") == 1


def test_fee_list_chunks_take_section_products(db_conn):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    out, _ = p.ingest_one(entry(FEE_URL), fee_list_pdf("1 septembrie 2026", first_section="1. Carduri de credit demo"))
    assert out is IngestOutcome.created
    rows = db_conn.execute("select products, topic, parent_section_key from knowledge_chunks order by ordinal").fetchall()
    assert rows[0] == (["credit_card"], "costs_fees", "1. Carduri de credit demo › 1.1. Produs demo")
    assert rows[1] == (["general"], "payments", "2. Plăți demo")


def test_document_without_chunks_writes_nothing(db_conn):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    out, msgs = p.ingest_one(entry(PDF_URL), make_pdf([[]]))
    assert out is IngestOutcome.failed and "no extractable content" in msgs[0]
    assert db_conn.execute("select count(*) from knowledge_documents").fetchone()[0] == 0


def test_failed_ingest_rolls_back(db_conn):
    class Boom(HashingEmbedder):
        def embed_documents(self, texts):
            raise RuntimeError("boom")

    good, _ = IngestionPipeline(db_conn, HashingEmbedder(), CFG).ingest_one(entry(FEE_URL, sha="v1"), fee_list_pdf("1 septembrie 2026"))
    chunks_v1 = count(db_conn, "knowledge_chunks")
    out, msgs = IngestionPipeline(db_conn, Boom(), CFG).ingest_one(entry(FEE_URL, sha="v2"), fee_list_pdf("1 noiembrie 2026"))
    assert good is IngestOutcome.created
    assert out is IngestOutcome.failed and msgs == ["boom"]
    assert db_conn.execute("select count(*) from knowledge_document_versions").fetchone()[0] == 1
    assert count(db_conn, "knowledge_chunks") == chunks_v1
    # v1 was committed and v2 left no trace: a separate connection sees only v1.
    with psycopg.connect(TEST_DB_URL) as other:
        assert other.execute("select effective_from from knowledge_document_versions").fetchall() == [(date(2026, 9, 1),)]


def test_withdrawn_entry_marks_document(db_conn, tmp_path):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    p.ingest_one(entry(PRODUCT_URL), PRODUCT_HTML)
    rep = p.ingest_entries([entry(PRODUCT_URL, withdrawn=True)], tmp_path)
    assert rep.outcomes == {PRODUCT_URL: IngestOutcome.withdrawn}
    assert db_conn.execute("select status from knowledge_documents").fetchone()[0] == "withdrawn"
    # Re-ingesting the page later makes it active again.
    p.ingest_one(entry(PRODUCT_URL), PRODUCT_HTML)
    assert db_conn.execute("select status from knowledge_documents").fetchone()[0] == "active"


def test_hub_cards_and_links_stored(db_conn):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    p.ingest_one(entry(HUB_URL), HUB_HTML)        # category_hub.html fixture from Task 4
    rows = db_conn.execute("select c.kind, c.products, c.authority from knowledge_chunks c where c.kind = 'hub_card' order by c.ordinal").fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [("hub_card", ["personal_loan"], "low"), ("hub_card", ["overdraft"], "low")]
    keys = [r[0] for r in db_conn.execute("select target_canonical_key from knowledge_chunk_links order by chunk_id, ordinal")]
    assert "/ro/persoane-fizice/produsele-noastre/credite/overdraft.html" in keys
    assert not any("/carduri/" in k for k in keys)
    card_links = db_conn.execute(
        "select l.link_kind, l.ordinal from knowledge_chunk_links l join knowledge_chunks c on c.id = l.chunk_id "
        "where c.kind = 'hub_card' order by c.ordinal").fetchall()
    assert card_links == [("card", 0), ("card", 0)]
    teaser_ordinals = [r[0] for r in db_conn.execute(
        "select l.ordinal from knowledge_chunk_links l join knowledge_chunks c on c.id = l.chunk_id "
        "where c.kind = 'hub_teasers' order by l.ordinal")]
    assert teaser_ordinals == [0, 1, 2]


def test_ingest_entries_records_index_run(db_conn, tmp_path):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    sha, path = save_raw(tmp_path, PRODUCT_HTML, ".html")
    entries = [
        entry(PRODUCT_URL, sha=sha, raw_path=path.name),
        entry(CREDITE + "ascuns.html", index=False),
        entry(CREDITE + "lipsa.html", status_code=404, raw_path=None),
        entry(PDF_URL, sha="gol", raw_path=save_raw(tmp_path, make_pdf([[]]), ".pdf")[1].name),
    ]
    rep = p.ingest_entries(entries, tmp_path)
    status, model, chunker = db_conn.execute("select status, embedding_model, chunker_version from index_runs where id=%s", (rep.run_id,)).fetchone()
    assert (status, model, chunker) == ("completed", "hashing-test", CHUNKER_VERSION)
    assert rep.outcomes == {
        PRODUCT_URL: IngestOutcome.created,
        CREDITE + "ascuns.html": IngestOutcome.skipped,
        CREDITE + "lipsa.html": IngestOutcome.skipped,
        PDF_URL: IngestOutcome.failed,
    }
    assert "no extractable content" in rep.errors[PDF_URL]
    seen, created, failures, finished = db_conn.execute(
        "select documents_seen, versions_created, failures, finished_at from index_runs where id=%s", (rep.run_id,)).fetchone()
    assert (seen, created, failures) == (4, 1, 1) and finished is not None


def test_dated_pdfs_with_distinct_stems_are_distinct_documents(db_conn, tmp_path):
    folder = DOCS + "credite/demo/"
    entries = []
    for stem in ("alfa", "beta", "gama"):
        sha, path = save_raw(tmp_path, make_pdf_from_lines([f"Informare {stem}", f"Text demonstrativ despre {stem}."]), ".pdf")
        entries.append(entry(f"{folder}20260901-{stem}.pdf", sha=sha, raw_path=path.name))
    rep = IngestionPipeline(db_conn, HashingEmbedder(), CFG).ingest_entries(entries, tmp_path)
    assert list(rep.outcomes.values()) == [IngestOutcome.created] * 3
    keys = sorted(r[0] for r in db_conn.execute("select canonical_key from knowledge_documents"))
    base = "/content/dam/rbi/retail/eu/ro/documents/pf/credite/demo/"
    assert keys == [base + "alfa", base + "beta", base + "gama"]


def test_rebuild_truncates_knowledge_tables_first(db_conn, tmp_path):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    p.ingest_one(entry(FEE_URL), fee_list_pdf("1 septembrie 2026"))
    sha, path = save_raw(tmp_path, PRODUCT_HTML, ".html")
    rep = p.rebuild([entry(PRODUCT_URL, sha=sha, raw_path=path.name)], tmp_path)
    assert rep.outcomes == {PRODUCT_URL: IngestOutcome.created}
    assert [r[0] for r in db_conn.execute("select source_url from knowledge_documents")] == [PRODUCT_URL]
    assert count(db_conn, "knowledge_document_versions") == 1


def test_campaign_window_stored_on_version(db_conn):
    # product fixture containing "Perioada campaniei: 15.10 - 26.11.2026"
    IngestionPipeline(db_conn, HashingEmbedder(), CFG).ingest_one(entry(PRODUCT_URL), PRODUCT_HTML)
    assert db_conn.execute("select campaign_valid_until from knowledge_document_versions").fetchone()[0] == date(2026, 11, 26)
