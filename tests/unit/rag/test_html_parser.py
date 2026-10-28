"""Tests for HTML page parser."""
from pathlib import Path

from src.services.document_ingestion.parsers.html_page import parse_html_page
from src.services.document_ingestion.sources import load_source_config
from src.models.knowledge import ChunkKind

CFG = load_source_config(Path("config/rag/sources.yaml"))
BASE = "https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/"


def test_faq_items_become_qa_chunks():
    faq = [c for c in parse_html_page(Path("tests/fixtures/rag/faq_page.html").read_bytes(), BASE + "x/intrebari-frecvente-demo.html", CFG).chunks if c.kind is ChunkKind.faq]
    assert len(faq) == 4 and faq[0].text.startswith("Întrebare: ") and "\nRăspuns: " in faq[0].text
    assert len(faq[0].section_path) == 3


def test_page_title_matching_a_drop_heading_keeps_the_page():
    """A real guide's h1 starts with "Cum obții", a drop_headings pattern meant for promo sections."""
    html = (
        "<html><body><main><h1>Cum obții un credit demo pentru construcție</h1>"
        "<h2>Ce este creditul demo</h2><p>Creditul demo finanțează construcția unei case demo.</p>"
        "<h2>Cum obții creditul demo</h2><p>Text promoțional demo.</p>"
        "<h2>Ce acte îți trebuie</h2><p>Actele demo sunt buletinul și autorizația.</p>"
        "</main></body></html>"
    ).encode("utf-8")
    doc = parse_html_page(html, BASE + "credite-imobiliare/cum-obtii-demo.html", CFG)
    texts = [c.text for c in doc.chunks]
    assert texts == ["Creditul demo finanțează construcția unei case demo.", "Actele demo sunt buletinul și autorizația."]
    assert [c.section_path for c in doc.chunks] == [["Ce este creditul demo"], ["Ce acte îți trebuie"]]
