"""Tests for fee list parser."""
import pytest
from src.models.knowledge import ChunkKind
from src.services.document_ingestion.parsers.fee_list import parse_fee_list
from tests.fixtures.rag.pdf_builders import make_pdf


def test_fee_list_sections_and_value_lines():
    """Test fee list parsing with sections and value line filtering."""
    pdf = make_pdf([
        [(50, 80, "Tarife si comisioane Demo")],
        [
            (50, 60, "1. Conturi demo"),
            (50, 80, "1.1. Cont curent demo"),
            (50, 100, "Tip"),
            (300, 100, "Comision"),
            (50, 120, "Deschidere cont"),
            (300, 120, "0 lei"),
            (50, 140, "100 lei"),
            (50, 160, "2. Plati demo"),
            (50, 180, "Transfer"),
            (300, 180, "3 lei"),
        ]
    ])
    doc = parse_fee_list(pdf)
    paths = [c.section_path for c in doc.chunks]
    assert paths == [["1. Conturi demo", "1.1. Cont curent demo"], ["2. Plati demo"]]
    assert "Deschidere cont | 0 lei" in doc.chunks[0].text and "100 lei" in doc.chunks[0].text
    assert doc.chunks[0].kind is ChunkKind.fee_table and doc.chunks[0].page == 2


def test_fee_list_repeats_column_header_when_split():
    """Test that column header is repeated when a section is split into multiple chunks."""
    rows = [(50, 100, "Tip"), (300, 100, "Comision")]
    # Add 50 long operation rows to force splitting
    for i in range(50):
        rows.append((50, 120 + i * 12, f"Operatiune demo numarul {i} cu descriere lunga"))
        rows.append((300, 120 + i * 12, f"{i} lei"))

    pdf = make_pdf([
        [(50, 80, "Tarife Demo")],
        [(50, 80, "1. Sectiune demo")] + rows
    ])
    doc = parse_fee_list(pdf)
    assert len(doc.chunks) >= 2
    assert doc.chunks[1].text.startswith("Tip | Comision")


def test_fee_list_title_extraction():
    """Test title extraction from cover page."""
    pdf = make_pdf([
        [(50, 80, "Tarife si comisioane Banca Demo")],
        [(50, 60, "1. Sectiune test"), (50, 80, "Content demo")]
    ])
    doc = parse_fee_list(pdf)
    assert "Tarife" in doc.title


def test_fee_list_parser_name():
    """Test parser metadata."""
    pdf = make_pdf([
        [(50, 80, "Tarife Demo")],
        [(50, 60, "1. Sectiune"), (50, 80, "Text demo")]
    ])
    doc = parse_fee_list(pdf)
    assert doc.parser_name == "fee_list"


def test_fee_list_value_line_patterns():
    """Test various value line patterns are not treated as section headings."""
    pdf = make_pdf([
        [(50, 80, "Tarife Demo")],
        [
            (50, 60, "1. Sectiune test"),
            (50, 80, "10 lei/operatiune"),  # Value line
            (50, 100, "30 EUR/intrare/persoana"),  # Value line
            (50, 120, "60 euro sau echivalent in lei (TVA inclus)"),  # Value line
            (50, 140, "10 intrari gratuite pe an,"),  # Value line
            (50, 160, "1.1. Subsectiune valida"),  # Valid heading
        ]
    ])
    doc = parse_fee_list(pdf)
    # Should only have one section path (the value lines should not create sections)
    paths = [c.section_path for c in doc.chunks]
    assert len(paths) == 1
    assert paths[0] == ["1. Sectiune test", "1.1. Subsectiune valida"]
