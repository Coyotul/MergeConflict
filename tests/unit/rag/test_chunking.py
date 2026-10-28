"""Tests for chunking primitives."""
from pathlib import Path
from datetime import date

from src.services.document_ingestion.chunking import (
    pack_lines,
    build_header,
    estimate_tokens,
)
from src.services.document_ingestion.parsers.html_page import parse_html_page
from src.services.document_ingestion.sources import load_source_config
from src.models.knowledge import ChunkKind

CFG = load_source_config(Path("config/rag/sources.yaml"))
BASE = "https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/"
PAGE_URL = BASE + "credit-de-nevoi-personale-fara-ipoteca.html"


def test_pack_lines_respects_limit_and_repeats_header():
    lines = ["x" * 800] * 5  # 200 tokens each
    parts = pack_lines(lines, max_tokens=500, repeat_header="H")
    assert len(parts) == 3 and parts[1].startswith("H\n")


def test_pack_lines_estimates_the_joined_piece_including_repeat_header():
    # 125 tokens per line: four lines sum to 500, but the joined text (with
    # newlines, and the repeated header on later pieces) is over the limit.
    lines = ["x" * 501] * 8
    parts = pack_lines(lines, max_tokens=500, repeat_header="H" * 40)
    assert len(parts) == 3 and all(estimate_tokens(p) <= 500 for p in parts)


def test_build_header():
    assert build_header("Credit Demo", ["Costuri", ""], date(2026, 10, 15)) == "Raiffeisen Bank › Credit Demo › Costuri · 2026-10-15"


def _page():
    return parse_html_page(Path("tests/fixtures/rag/product_page.html").read_bytes(), PAGE_URL, CFG)


def test_heading_only_conditions_are_kept():
    elig = [c for c in _page().chunks if "Ce condiții" in " ".join(c.section_path)]
    assert len(elig) == 1 and "- Vârstă între 20 și 60 de ani" in elig[0].text and "- Venit minim 2.500 lei" in elig[0].text


def test_worked_examples_are_atomic_and_exclude_trailing_text():
    ex = [c for c in _page().chunks if c.kind is ChunkKind.worked_example]
    assert len(ex) == 2 and all(c.text.startswith("Exemplu de calcul") for c in ex)
    assert all("Ofertele sunt supuse" not in c.text for c in ex)
    # Examples have proper section_path with h2 context
    assert all("Exemple de calcul" in " ".join(c.section_path) for c in ex)


def test_dropped_sections_duplicates_and_site_chrome():
    doc = _page()
    assert not any("Articole utile" in " ".join(c.section_path) for c in doc.chunks)
    joined = "\n".join(c.text for c in doc.chunks)
    # Duplicate text appears only once (deduped across page)
    assert joined.count("Ofertele sunt supuse unor termeni și condiții specifice.") == 1
    assert "Mergi acasă" not in joined
    assert doc.title and doc.parser_name == "html_page"
    # No empty section_path parts
    assert all(all(p for p in c.section_path) for c in doc.chunks)


def test_section_chunks_are_normalized():
    """Test that section chunks have normalized text (cedilla->comma, NBSP->space)."""
    # Create HTML with ş, ţ (cedilla forms) and NBSP
    html = b"""
    <html><body><main>
    <h1>Test</h1>
    <h2>Section</h2>
    <p>Text with \xc5\x9f \xc5\xa3 and\xc2\xa0NBSP.</p>
    </main></body></html>
    """
    
    doc = parse_html_page(html, PAGE_URL, CFG)
    section_chunks = [c for c in doc.chunks if c.kind == ChunkKind.section]
    
    assert len(section_chunks) >= 1
    # Should have comma-below forms (ș ț) and plain space, not cedilla (ş ţ) or NBSP
    assert "ș ț" in section_chunks[0].text
    assert "ş ţ" not in section_chunks[0].text
    assert "\xa0" not in section_chunks[0].text


def test_table_cell_links_extracted():
    """Test that links in table cells are extracted."""
    html = b"""
    <html><body><main>
    <h1>Test</h1>
    <h2>Fees</h2>
    <table>
    <tr>
        <td>Product</td>
        <td><a href="/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale/conditii-credit-nevoi-personale.html">Details</a></td>
    </tr>
    </table>
    </main></body></html>
    """
    
    doc = parse_html_page(html, PAGE_URL, CFG)
    section_chunks = [c for c in doc.chunks if c.kind == ChunkKind.section]
    
    assert len(section_chunks) >= 1
    # Table chunk should have the link
    table_chunk = [c for c in section_chunks if "Product" in c.text and "Details" in c.text]
    assert len(table_chunk) == 1
    assert len(table_chunk[0].links) == 1
    assert "conditii-credit-nevoi-personale.html" in table_chunk[0].links[0].target_url


def test_worked_examples_in_document_order():
    """Test that worked examples appear in document order after preceding sections."""
    doc = _page()
    
    # Get indices of different chunk types
    acte_idx = next(i for i, c in enumerate(doc.chunks) if "Ce acte" in " ".join(c.section_path))
    example_indices = [i for i, c in enumerate(doc.chunks) if c.kind == ChunkKind.worked_example]
    
    # Worked examples should come after "Ce acte" section
    assert all(idx > acte_idx for idx in example_indices)
    
    # And before any chunk from a later h2 (FAQ section)
    faq_idx = next((i for i, c in enumerate(doc.chunks) if c.kind == ChunkKind.faq), len(doc.chunks))
    assert all(idx < faq_idx for idx in example_indices)


def test_accordion_in_dropped_section_not_emitted():
    """Test that accordions inside dropped sections are not emitted."""
    # Add an accordion to the dropped "Articole utile" section
    html = b"""
    <html><body><main>
    <h1>Credit Demo</h1>
    <h2>Kept Section</h2>
    <p>This stays.</p>
    <h2>Articole utile</h2>
    <p>Dropped intro.</p>
    <div class="cmp-accordion">
        <div class="cmp-accordion__item">
            <div class="cmp-accordion__title">Should not appear</div>
            <div class="cmp-accordion__panel">
                <p>This should be dropped.</p>
            </div>
        </div>
    </div>
    </main></body></html>
    """
    
    doc = parse_html_page(html, PAGE_URL, CFG)
    
    # No FAQ chunk should contain "Should not appear"
    faq_chunks = [c for c in doc.chunks if c.kind == ChunkKind.faq]
    assert not any("Should not appear" in c.text for c in faq_chunks)


def test_faq_exact_section_path():
    """Test that FAQ has exact section path [h1, group_heading, question]."""
    doc = _page()
    faq_chunks = [c for c in doc.chunks if c.kind == ChunkKind.faq]
    
    assert len(faq_chunks) >= 1
    faq = faq_chunks[0]
    
    # Should have 3 parts: [h1, group_heading, question]
    assert len(faq.section_path) == 3
    assert faq.section_path[0] == "Credit Demo"
    assert faq.section_path[1] == "Întrebări frecvente"
    assert faq.section_path[2] == "Pot rambursa anticipat?"
