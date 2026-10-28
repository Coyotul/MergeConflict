"""Tests for the generic PDF parser."""
import pymupdf as fitz

from src.models.knowledge import DocKind
from src.services.document_ingestion.parsers import parse_document
from src.services.document_ingestion.parsers.pdf_generic import parse_pdf_generic
from src.services.document_ingestion.sources import SourceConfig
from tests.fixtures.rag.pdf_builders import build_demo_cost_sheet, make_pdf, make_pdf_from_lines


def test_pdf_generic_short_and_sectioned():
    short = parse_pdf_generic(make_pdf([[(50, 60, "Informare demo"), (50, 80, "Text scurt.")]]))
    assert len(short.chunks) == 1 and short.chunks[0].section_path == []
    long = parse_pdf_generic(make_pdf_from_lines(["Ghid demo"] + [f"{i}. Capitol demo {i}" if j == 0 else "text demonstrativ " * 30 for i in range(1, 5) for j in range(4)]))
    assert [c.section_path[0] for c in long.chunks][:2] == ["1. Capitol demo 1", "2. Capitol demo 2"]


def test_pdf_generic_bold_lines_are_headings():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 50
    page.insert_text((50, y), "Ghid demo", fontname="helv", fontsize=6)
    for heading in ("Capitol demo intai", "Capitol demo doi"):
        y += 10
        page.insert_text((50, y), heading, fontname="hebo", fontsize=6)
        for _ in range(8):
            y += 8
            page.insert_text((50, y), "text demonstrativ " * 10, fontname="helv", fontsize=6)
    data = doc.tobytes()
    doc.close()
    parsed = parse_pdf_generic(data)
    assert [c.section_path for c in parsed.chunks] == [["Capitol demo intai"], ["Capitol demo doi"]]
    assert parsed.title == "Ghid demo" and parsed.parser_name == "pdf_generic"


def test_parse_document_dispatches_cost_sheet_and_pdf_generic():
    cfg = SourceConfig.model_construct()
    url = "https://example.invalid/demo.pdf"
    assert parse_document(DocKind.cost_sheet, build_demo_cost_sheet(), url, cfg).parser_name == "cost_sheet"
    generic = make_pdf([[(50, 60, "Informare demo"), (50, 80, "Text scurt.")]])
    assert parse_document(DocKind.pdf_generic, generic, url, cfg).parser_name == "pdf_generic"


def test_pdf_generic_short_document_is_one_chunk_despite_headings():
    doc = parse_pdf_generic(make_pdf([[(50, 60, "Informare demo"), (50, 80, "1. Capitol demo"), (50, 100, "Text scurt.")]]))
    assert [(c.section_path, c.text) for c in doc.chunks] == [([], "Informare demo\n1. Capitol demo\nText scurt.")]
