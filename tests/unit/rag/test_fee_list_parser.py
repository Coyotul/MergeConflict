"""Tests for fee list parser."""
from datetime import date, datetime, timezone

import pytest
from src.models.knowledge import ChunkKind, DocKind
from src.services.document_ingestion.metadata import extract_effective_date
from src.services.document_ingestion.parsers.fee_list import parse_fee_list
from tests.fixtures.rag.pdf_builders import make_pdf


def test_fee_list_sections_and_value_lines():
    """Test fee list parsing with sections and value line filtering."""
    pdf = make_pdf([
        [(50, 80, "Tarife și comisioane Demo")],
        [
            (50, 60, "1. Conturi demo"),
            (50, 80, "1.1. Cont curent demo"),
            (50, 100, "Tip"),
            (300, 100, "Comision"),
            (50, 120, "Deschidere cont"),
            (300, 120, "0 lei"),
            (50, 140, "100 lei"),
            (50, 160, "2. Plăți demo"),
            (50, 180, "Transfer"),
            (300, 180, "3 lei"),
        ]
    ])
    doc = parse_fee_list(pdf)
    paths = [c.section_path for c in doc.chunks]
    assert paths == [["1. Conturi demo", "1.1. Cont curent demo"], ["2. Plăți demo"]]
    assert "Deschidere cont | 0 lei" in doc.chunks[0].text and "100 lei" in doc.chunks[0].text
    assert doc.chunks[0].kind is ChunkKind.fee_table and doc.chunks[0].page == 2


def test_fee_list_repeats_column_header_when_split():
    """Test that column header is repeated when a section is split into multiple chunks."""
    rows = [(50, 100, "Tip"), (300, 100, "Comision")]
    # Add 50 long operation rows to force splitting
    for i in range(50):
        rows.append((50, 120 + i * 12, f"Operațiune demo numărul {i} cu descriere lungă"))
        rows.append((300, 120 + i * 12, f"{i} lei"))

    pdf = make_pdf([
        [(50, 80, "Tarife Demo")],
        [(50, 80, "1. Secțiune demo")] + rows
    ])
    doc = parse_fee_list(pdf)
    assert len(doc.chunks) >= 2
    assert doc.chunks[1].text.startswith("Tip | Comision")
    assert "Operațiune demo numărul 0 cu descriere lungă | 0 lei" in doc.chunks[0].text


def test_fee_list_title_extraction():
    """Test title extraction from cover page."""
    pdf = make_pdf([
        [(50, 80, "Tarife și comisioane Banca Demo")],
        [(50, 60, "1. Sectiune test"), (50, 80, "Content demo")]
    ])
    doc = parse_fee_list(pdf)
    assert doc.title == "Tarife și comisioane Banca Demo"


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
            (50, 80, "10 lei/operațiune"),  # Value line
            (50, 100, "30 EUR/intrare/persoană"),  # Value line
            (50, 120, "60 euro sau echivalent în lei (TVA inclus)"),  # Value line
            (50, 140, "10 intrări gratuite pe an,"),  # Value line
            (50, 160, "1.1. Subsectiune valida"),  # Valid heading
            (50, 180, "Content pentru 1.1"),  # Content for subsection
        ]
    ])
    doc = parse_fee_list(pdf)
    # Value lines should not create sections; only the two headings should
    paths = [c.section_path for c in doc.chunks]
    assert len(paths) == 2
    assert paths[0] == ["1. Sectiune test"]
    assert paths[1] == ["1. Sectiune test", "1.1. Subsectiune valida"]
    # Verify value lines are in first chunk, subsection content in second
    assert "10 lei/operațiune" in doc.chunks[0].text
    assert "Content pentru 1.1" in doc.chunks[1].text


def test_fee_list_flushes_on_every_heading():
    """Test that every heading (any depth) starts a new section."""
    pdf = make_pdf([
        [(50, 80, "Tarife Demo")],
        [
            (50, 60, "1. Sectiune prima"),
            (50, 80, "Content pentru 1"),
            (50, 100, "1.1. Subsectiune 1.1"),
            (50, 120, "Content pentru 1.1"),
            (50, 140, "1.2. Subsectiune 1.2"),
            (50, 160, "Content pentru 1.2"),
            (50, 180, "2. Sectiune a doua"),
            (50, 200, "Content pentru 2"),
            (50, 220, "2.1. Subsectiune 2.1"),
            (50, 240, "Content pentru 2.1"),
        ]
    ])
    doc = parse_fee_list(pdf)
    paths = [c.section_path for c in doc.chunks]
    # Should have 5 chunks, one per heading
    assert len(paths) == 5
    assert paths[0] == ["1. Sectiune prima"]
    assert paths[1] == ["1. Sectiune prima", "1.1. Subsectiune 1.1"]
    assert paths[2] == ["1. Sectiune prima", "1.2. Subsectiune 1.2"]
    assert paths[3] == ["2. Sectiune a doua"]
    assert paths[4] == ["2. Sectiune a doua", "2.1. Subsectiune 2.1"]
    # Check content landed in right chunks
    assert "Content pentru 1" in doc.chunks[0].text
    assert "Content pentru 1.1" in doc.chunks[1].text
    assert "Content pentru 1.2" in doc.chunks[2].text


def test_fee_list_flushes_on_numbering_restart():
    """Numbering that restarts at 1. later in the document still starts new sections."""
    pdf = make_pdf([
        [(50, 80, "Tarife Demo")],
        [
            (50, 60, "1. A"),
            (50, 80, "1.1. A1"), (50, 100, "Rând A1"), (300, 100, "1 lei"),
            (50, 120, "1.2. A2"), (50, 140, "Rând A2"), (300, 140, "2 lei"),
            (50, 160, "2. B"),
            (50, 180, "2.1. B1"), (50, 200, "Rând B1"), (300, 200, "3 lei"),
            (50, 220, "1. C"),
            (50, 240, "1.1. C1"), (50, 260, "Rând C1"), (300, 260, "4 lei"),
        ]
    ])
    doc = parse_fee_list(pdf)
    paths = [c.section_path for c in doc.chunks]
    assert paths == [["1. A", "1.1. A1"], ["1. A", "1.2. A2"], ["2. B", "2.1. B1"], ["1. C", "1.1. C1"]]
    rows = ["Rând A1 | 1 lei", "Rând A2 | 2 lei", "Rând B1 | 3 lei", "Rând C1 | 4 lei"]
    for i, chunk in enumerate(doc.chunks):
        for j, row in enumerate(rows):
            assert (row in chunk.text) is (i == j), (paths[i], row)


def test_fee_list_repeated_parent_and_child_headings_do_not_split_section():
    """A continuation page that repeats "1. A" and "1.1. B" keeps one section starting on page 2."""
    filler = [[(50, 60, f"{n}. Altă secțiune {n}"), (50, 80, f"Rând filler {n}"), (300, 80, f"{n} lei")]
              for n in range(2, 6)]
    pdf = make_pdf([
        [(50, 80, "Tarife Demo")],
        [(50, 60, "1. A"), (50, 80, "1.1. B"), (50, 100, "Rând pagina doi"), (300, 100, "5 lei")],
        [(50, 60, "1. A"), (50, 80, "1.1. B"), (50, 100, "Rând pagina trei"), (300, 100, "6 lei")],
        *filler,
    ])
    doc = parse_fee_list(pdf)
    section = [c for c in doc.chunks if c.section_path[0] == "1. A"]
    assert len(section) == 1
    assert section[0].section_path == ["1. A", "1.1. B"]
    assert section[0].page == 2
    assert "Rând pagina doi | 5 lei" in section[0].text
    assert "Rând pagina trei | 6 lei" in section[0].text
    assert [c.section_path for c in doc.chunks][1:] == [[f"{n}. Altă secțiune {n}"] for n in range(2, 6)]


REJECTED_AS_HEADINGS = [
    "5 intrări pe lună",
    "10 intrări gratuite pe an,",
    "2. 5 lei",
    "3. 10% din sumă",
    "1.5 lei",
    "2.50 lei",
    "100 lei",
    "10 lei/operațiune",
    "30 EUR/intrare/persoană",
    "60 euro sau echivalent în lei (TVA inclus)",
]
ACCEPTED_AS_HEADINGS = [
    "1.1. Conturi curente",
    "7. Taxe, comisioane și dobânzi aplicabile cardurilor de credit",
    "10. Diverse",
    "1. Europa demo",  # a unit word must not match as a prefix ("eur")
]


@pytest.mark.parametrize("line", REJECTED_AS_HEADINGS)
def test_is_section_heading_rejects_value_lines(line):
    from src.services.document_ingestion.parsers.fee_list import is_section_heading
    assert not is_section_heading(line)


@pytest.mark.parametrize("line", ACCEPTED_AS_HEADINGS)
def test_is_section_heading_accepts_headings(line):
    from src.services.document_ingestion.parsers.fee_list import is_section_heading
    assert is_section_heading(line)


def test_fee_list_cover_date_reaches_metadata_text():
    """The edition date printed only on the cover is found by extract_effective_date."""
    pdf = make_pdf([
        [(50, 80, "Tarife și comisioane Demo"), (50, 100, "Valabil din 1 septembrie 2026")],
        [(50, 60, "1. Conturi demo"), (50, 80, "Deschidere cont"), (300, 80, "0 lei")],
    ])
    doc = parse_fee_list(pdf)
    assert doc.metadata_text.startswith("Tarife și comisioane Demo\nValabil din 1 septembrie 2026\n")
    assert all("septembrie" not in c.text for c in doc.chunks)
    fetched = datetime(2026, 10, 20, tzinfo=timezone.utc)
    assert extract_effective_date(DocKind.fee_list, doc.metadata_text, "https://example.invalid/tarife.pdf", None, fetched) \
        == (date(2026, 9, 1), "document_text")


def test_fee_list_value_lines_with_diacritics_stay_content():
    """Diacritic value lines go through parse_fee_list as content, never as section paths."""
    items = [(50, 60, "1. Conturi și operațiuni demo"), (50, 80, "1.1. Conturi curente")]
    y = 100
    for line in REJECTED_AS_HEADINGS:
        items.append((50, y, line))
        y += 20
    items += [(50, y, "7. Taxe, comisioane și dobânzi aplicabile cardurilor de credit"),
              (50, y + 20, "Emitere card demo"), (300, y + 20, "0 lei"),
              (50, y + 40, "10. Diverse"),
              (50, y + 60, "Adeverință demo"), (300, y + 60, "20 lei")]
    doc = parse_fee_list(make_pdf([[(50, 80, "Tarife Demo")], items]))
    paths = [c.section_path for c in doc.chunks]
    assert paths == [
        ["1. Conturi și operațiuni demo", "1.1. Conturi curente"],
        ["7. Taxe, comisioane și dobânzi aplicabile cardurilor de credit"],
        ["10. Diverse"],
    ]
    for line in REJECTED_AS_HEADINGS:
        assert line in doc.chunks[0].text.splitlines()
