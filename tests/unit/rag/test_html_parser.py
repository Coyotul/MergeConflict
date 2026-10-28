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
