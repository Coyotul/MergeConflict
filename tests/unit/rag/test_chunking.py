"""Tests for chunking primitives."""
from pathlib import Path
from datetime import date

from src.services.document_ingestion.chunking import (
    pack_lines,
    build_header,
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


def test_dropped_sections_duplicates_and_site_chrome():
    doc = _page()
    assert not any("Articole utile" in " ".join(c.section_path) for c in doc.chunks)
    joined = "\n".join(c.text for c in doc.chunks)
    assert joined.count("Ofertele sunt supuse unor termeni și condiții specifice.") == 1
    assert "Mergi acasă" not in joined
    assert doc.title and doc.parser_name == "html_page"
