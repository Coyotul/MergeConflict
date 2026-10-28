"""Tests for link extraction and filtering."""
from pathlib import Path

from src.services.document_ingestion.parsers.html_page import parse_html_page, clean_html
from src.services.document_ingestion.parsers.links import absolutize
from src.services.document_ingestion.sources import load_source_config
from src.services.document_ingestion.metadata import canonical_key
from src.models.knowledge import LinkKind

CFG = load_source_config(Path("config/rag/sources.yaml"))
BASE = "https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/"
PAGE_URL = BASE + "credit-de-nevoi-personale-fara-ipoteca.html"


def _page():
    return parse_html_page(Path("tests/fixtures/rag/product_page.html").read_bytes(), PAGE_URL, CFG)


def test_inline_links_kept_filtered_and_attached():
    acte = next(c for c in _page().chunks if "Ce acte" in " ".join(c.section_path))
    assert [(l.target_url, l.link_kind) for l in acte.links] == [
        (BASE + "credite-de-nevoi-personale/conditii-credit-nevoi-personale.html", LinkKind.inline)]
    # Self-link dropped (moved to "Exemple de calcul" section in fixture)
    assert all(l.target_url != PAGE_URL for c in _page().chunks for l in c.links)
    # Text not glued at tag boundaries
    assert "vezi articolul despre condiții" in acte.text


def test_absolutize_odd_hrefs():
    page = PAGE_URL
    for junk in ["", "#", "#top", "javascript:void(0)", "tel:*2000", "mailto:a@b.ro"]:
        assert absolutize(junk, page) is None
    assert absolutize("overdraft.html?utm=x#faq", page) == BASE + "overdraft.html"
    assert canonical_key(absolutize("http://raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/overdraft.html", page)) == canonical_key(BASE + "overdraft.html")


def test_clean_html_keeps_teaser_header_links():
    soup = clean_html(Path("tests/fixtures/rag/category_hub.html").read_bytes())
    assert soup.select("article.cmp-teaser header.cmp-teaser__header a.cmp-image__link")
    assert not soup.select("body > header")


def test_links_split_with_pack_lines():
    """Test that links are attached to the correct piece when a section splits."""
    # Create HTML with enough paragraphs to exceed MAX_TOKENS, with link only in last paragraph
    html = b"""
    <html><body><main>
    <h1>Test</h1>
    <h2>Large Section</h2>
    <p>""" + b"x" * 800 + b"""</p>
    <p>""" + b"y" * 800 + b"""</p>
    <p>""" + b"z" * 800 + b"""</p>
    <p>""" + b"w" * 700 + b""" <a href="/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale/test.html">vezi aici</a>.</p>
    </main></body></html>
    """

    doc = parse_html_page(html, PAGE_URL, CFG)

    # Find section chunks with "Large Section" path
    large_section_chunks = [c for c in doc.chunks if "Large Section" in c.section_path]

    # Should have split into at least 2 pieces
    assert len(large_section_chunks) >= 2

    # All pieces should have same section_path
    assert all(c.section_path == large_section_chunks[0].section_path for c in large_section_chunks)

    # First piece should not have the link
    assert len(large_section_chunks[0].links) == 0

    # Last piece should have the link (contains "vezi aici")
    last_piece = [c for c in large_section_chunks if "vezi aici" in c.text]
    assert len(last_piece) == 1
    assert len(last_piece[0].links) == 1
