"""Tests for metadata extraction."""
from datetime import date, datetime, timezone
from src.models.knowledge import DocKind
from src.services.document_ingestion.metadata import (
    canonical_key,
    extract_effective_date,
    extract_campaign_window,
    shared_dated_folders,
)

D = "https://www.raiffeisen.ro/content/dam/rbi/retail/eu/ro/documents/"
FETCHED = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)


def test_canonical_key_alias_and_dated_file_match():
    a = canonical_key(D + "pf/tarife-comisioane-standard-pf.sv.pdf")
    b = canonical_key(D + "pf/tarife-comisioane-standard-pf/20260901-Tarife-si-comisioane-standard-persoane-fizice.pdf.coredownload.pdf")
    assert a == b == "/content/dam/rbi/retail/eu/ro/documents/pf/tarife-comisioane-standard-pf"


def test_canonical_key_uses_folder_for_misnamed_cost_sheet():
    k = canonical_key(D + "costuri/garantate/costuri-casa-ta-dobanda-fixa-5-ani/20261022-Costuri-casa-ta-dobanda-fixa-3-ani.pdf.coredownload.pdf")
    assert k.endswith("costuri-casa-ta-dobanda-fixa-5-ani")


def test_canonical_key_html():
    assert canonical_key("https://www.raiffeisen.ro/ro/a/b.html?x=1") == "/ro/a/b.html"


def test_shared_dated_folders_and_keys():
    F = D + "pf/in-sprijinul-tau/"
    urls = [F + "20260101-Notificare-card.pdf", F + "20250301-Notificare-call-center.pdf",
            F + "20170501-Conditii-creditare.pdf.coredownload.pdf",
            D + "pf/tarife-comisioane-standard-pf/20260901-Tarife-si-comisioane-standard-persoane-fizice.pdf.coredownload.pdf",
            D + "pf/tarife-comisioane-standard-pf/20261101-Tarife-si-comisioane-standard-persoane-fizice.pdf.coredownload.pdf"]
    shared = shared_dated_folders(urls)
    assert shared == frozenset({"/content/dam/rbi/retail/eu/ro/documents/pf/in-sprijinul-tau"})
    k1, k2 = (canonical_key(u, shared) for u in urls[:2])
    assert k1 != k2 and k1 == "/content/dam/rbi/retail/eu/ro/documents/pf/in-sprijinul-tau/notificare-card"
    assert canonical_key(urls[2], shared).endswith("/in-sprijinul-tau/conditii-creditare")
    assert canonical_key(urls[3], shared) == canonical_key(urls[4], shared) == canonical_key(D + "pf/tarife-comisioane-standard-pf.sv.pdf", shared)


def test_effective_date_precedence():
    assert extract_effective_date(DocKind.fee_list, "Tarife\n1 septembrie 2026\n", D + "x.pdf", None, FETCHED) == (date(2026, 9, 1), "document_text")
    assert extract_effective_date(DocKind.general_terms, "Conditiile ... Editia 26.02.2026", D + "20262602-C.pdf", None, FETCHED) == (date(2026, 2, 26), "document_text")
    assert extract_effective_date(DocKind.cost_sheet, "15.10.2026\nFlexi", D + "y.pdf", None, FETCHED) == (date(2026, 10, 15), "document_text")
    assert extract_effective_date(DocKind.pdf_generic, "fara data", D + "c/20240129-x.pdf", None, FETCHED) == (date(2024, 1, 29), "filename")
    assert extract_effective_date(DocKind.pdf_generic, "fara data", D + "c/20262602-x.pdf", date(2026, 3, 1), FETCHED) == (date(2026, 3, 1), "sitemap_lastmod")
    assert extract_effective_date(DocKind.product_page, "Perioada campaniei: 15.10 - 26.11.2026", "https://x/ro/p.html", None, FETCHED) == (date(2026, 10, 28), "fetched_at")


def test_campaign_window():
    assert extract_campaign_window("Perioada campaniei: 15.10 - 26.11.2026.", date(2026, 10, 28)) == date(2026, 11, 26)
    assert extract_campaign_window("Perioada campaniei: 01.03 - 31.03", date(2026, 10, 28)) == date(2026, 3, 31)
    assert extract_campaign_window("Fără campanie", date(2026, 10, 28)) is None


def test_campaign_window_variations():
    # Test "campania este valabilă" variant
    assert extract_campaign_window("campania este valabilă: 01.12 - 31.12.2026", date(2026, 10, 28)) == date(2026, 12, 31)
    # Test "campania se desfășoară" variant
    assert extract_campaign_window("campania se desfășoară în perioada 01.01 - 28.02", date(2026, 10, 28)) == date(2026, 2, 28)
