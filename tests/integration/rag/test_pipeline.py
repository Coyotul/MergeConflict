"""Integration tests for the versioned ingestion pipeline (needs the rag-db container)."""
import os
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
import pytest

from src.core.errors import IngestionError
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
        [(50, 80, "Tarife și comisioane Demo"), (50, 100, f"Valabil din {date_text}")],
        [
            (50, 60, first_section),
            (50, 80, "1.1. Produs demo"),
            (50, 100, "Tip"), (300, 100, "Comision"),
            (50, 120, "Emitere demo"), (300, 120, "0 lei"),
            (50, 140, "2. Plăți demo"),
            (50, 160, "Transfer demo"), (300, 160, "3 lei"),
        ],
    ])


def count(conn, table):
    """Row count; ends the read transaction so the pipeline gets an idle connection."""
    n = conn.execute(f"select count(*) from {table}").fetchone()[0]
    conn.commit()
    return n


def committed(sql, params=()):
    """Rows as seen from a separate connection, i.e. only committed data."""
    with psycopg.connect(TEST_DB_URL) as other:
        return other.execute(sql, params).fetchall()


def pdf_entries(tmp_path, stems):
    """Entries for distinct one-page PDFs, dated, in one shared folder."""
    entries = []
    for stem in stems:
        sha, path = save_raw(tmp_path, make_pdf_from_lines([f"Informare {stem}", f"Text demonstrativ despre {stem}."]), ".pdf")
        entries.append(entry(f"{DOCS}credite/demo/20260901-{stem}.pdf", sha=sha, raw_path=path.name))
    return entries


class FailsOn(HashingEmbedder):
    """Embedder that raises `error` when any text mentions `word`."""

    def __init__(self, word, error):
        super().__init__()
        self.word, self.error = word, error

    def embed_documents(self, texts):
        if any(self.word in t for t in texts):
            raise self.error
        return super().embed_documents(texts)


class Abort(BaseException):
    """Escapes ingest_one's `except Exception`, like KeyboardInterrupt."""


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


def test_alias_and_dated_pdf_share_one_version(db_conn, tmp_path):
    # same bytes under ".../tarife-demo.sv.pdf" and ".../tarife-demo/20260901-x.pdf.coredownload.pdf"
    sha, path = save_raw(tmp_path, fee_list_pdf("1 septembrie 2026"), ".pdf")
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    rep = p.ingest_entries([entry(DOCS + "tarife-demo.sv.pdf", sha=sha, raw_path=path.name),
                            entry(DOCS + "tarife-demo/20260901-x.pdf.coredownload.pdf", sha=sha, raw_path=path.name)], tmp_path)
    outcomes = list(rep.outcomes.values())
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
    # The withdrawal is keyed on final_url: the requested URL redirected to the indexed page.
    old_url = CREDITE + "credit-demo-vechi.html"
    rep = p.ingest_entries([entry(old_url, final_url=PRODUCT_URL, withdrawn=True)], tmp_path)
    assert rep.outcomes == {old_url: IngestOutcome.withdrawn} and rep.warnings == {}
    assert db_conn.execute("select status from knowledge_documents").fetchone()[0] == "withdrawn"
    db_conn.commit()
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
    rep = IngestionPipeline(db_conn, HashingEmbedder(), CFG).ingest_entries(pdf_entries(tmp_path, ["alfa", "beta", "gama"]), tmp_path)
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


def test_withdrawal_of_unindexed_document_is_skipped(db_conn, tmp_path):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    p.ingest_one(entry(PRODUCT_URL), PRODUCT_HTML)
    unknown = CREDITE + "nu-exista.html"
    rep = p.ingest_entries([entry(unknown, withdrawn=True)], tmp_path)
    assert rep.outcomes == {unknown: IngestOutcome.skipped}
    assert rep.warnings == {unknown: ["withdrawal target not indexed"]}
    assert committed("select status from knowledge_documents") == [("active",)]


def test_failed_withdrawal_is_recorded_and_run_continues(db_conn, tmp_path, monkeypatch):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)

    def broken(keys):
        db_conn.execute("select * from no_such_table")

    monkeypatch.setattr(p.documents, "mark_withdrawn", broken)
    sha, path = save_raw(tmp_path, PRODUCT_HTML, ".html")
    gone = CREDITE + "retras.html"
    rep = p.ingest_entries([entry(gone, withdrawn=True), entry(PRODUCT_URL, sha=sha, raw_path=path.name)], tmp_path)
    assert rep.outcomes == {gone: IngestOutcome.failed, PRODUCT_URL: IngestOutcome.created}
    assert "withdrawal failed" in rep.errors[gone] and "no_such_table" in rep.errors[gone]
    assert committed("select status, failures, versions_created from index_runs") == [("completed", 1, 1)]


def test_pipeline_rejects_connection_with_open_transaction(db_conn, tmp_path):
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    db_conn.execute("select 1")  # opens a transaction and leaves it open
    with pytest.raises(IngestionError, match="idle connection"):
        p.ingest_one(entry(PRODUCT_URL), PRODUCT_HTML)
    with pytest.raises(IngestionError, match="idle connection"):
        p.ingest_entries([], tmp_path)
    with pytest.raises(IngestionError, match="idle connection"):
        p.rebuild([], tmp_path)
    db_conn.rollback()
    assert count(db_conn, "index_runs") == 0 and count(db_conn, "knowledge_documents") == 0


def test_document_failing_mid_run_leaves_others_committed(db_conn, tmp_path):
    p = IngestionPipeline(db_conn, FailsOn("beta", RuntimeError("embedder down")), CFG)
    entries = pdf_entries(tmp_path, ["alfa", "beta", "gama"])
    rep = p.ingest_entries(entries, tmp_path)
    assert list(rep.outcomes.values()) == [IngestOutcome.created, IngestOutcome.failed, IngestOutcome.created]
    assert rep.errors == {entries[1].url: "embedder down"}
    base = "/content/dam/rbi/retail/eu/ro/documents/pf/credite/demo/"
    assert committed("select canonical_key from knowledge_documents order by canonical_key") == [(base + "alfa",), (base + "gama",)]
    assert committed("select count(*) from knowledge_document_versions") == [(2,)]


def test_exception_escaping_run_marks_index_run_failed(db_conn, tmp_path):
    p = IngestionPipeline(db_conn, FailsOn("beta", Abort()), CFG)
    entries = pdf_entries(tmp_path, ["alfa", "beta", "gama"])
    with pytest.raises(Abort):
        p.ingest_entries(entries, tmp_path)
    rows = committed("select status, finished_at is not null, documents_seen, versions_created, failures from index_runs")
    assert rows == [("failed", True, 1, 1, 0)]
    # The document committed before the abort stays; the aborted one left nothing behind.
    assert committed("select count(*) from knowledge_documents") == [(1,)]


def test_links_normalizing_to_one_key_are_stored_once(db_conn):
    # The parser dedupes by canonical_key without shared folders, so these two hrefs survive it
    # (".../demo/alfa" vs ".../demo"). With "demo" as a shared folder both become ".../demo/alfa",
    # and only ON CONFLICT DO NOTHING keeps the insert from failing.
    folder = "/content/dam/rbi/retail/eu/ro/documents/pf/credite/demo"
    html = f"""<html><body><main><h1>Credit Demo</h1><h2>Documente demo</h2>
        <p>Vezi <a href="{folder}/alfa.pdf">informarea</a> sau <a href="{folder}/20260901-alfa.pdf">ediția datată</a>.</p>
        </main></body></html>""".encode("utf-8")
    p = IngestionPipeline(db_conn, HashingEmbedder(), CFG)
    out, msgs = p.ingest_one(entry(PRODUCT_URL), html, shared_folders=frozenset({folder}))
    assert out is IngestOutcome.created, msgs
    rows = db_conn.execute("select target_canonical_key, anchor_text, ordinal from knowledge_chunk_links").fetchall()
    assert rows == [(folder + "/alfa", "informarea", 0)]
