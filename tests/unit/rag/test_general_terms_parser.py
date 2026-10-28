"""Tests for general terms parser."""
import pytest
from src.models.knowledge import ChunkKind
from src.services.document_ingestion.parsers.general_terms import parse_general_terms
from src.services.document_ingestion.chunking import estimate_tokens
from tests.fixtures.rag.pdf_builders import make_pdf_from_lines


def test_general_terms_splits_by_numbering_including_flattened_subclauses():
    """Test general terms parsing with flattened sub-clauses."""
    # Create section 5.1 with sub-clauses that will exceed MAX_TOKENS and require splitting
    text_lines = [
        "Conditii Generale Demo Editia 01.01.2026",
        "5. PREVEDERI DEMO CARDURI",
        "5.1 Emiterea cardurilor Text introductiv demo pentru testare.",
    ]
    # Add many sub-clauses to ensure we exceed MAX_TOKENS (500)
    # Each sub-clause on its own line with moderate text (~15 chars per clause)
    for i in range(1, 36):
        text_lines.append(f"5.1.{i} Clauza demo {i} cu continut semnificativ pentru testare si validare.")
    text_lines.append("5.2 Utilizatori demo Text scurt.")

    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    s51 = [c for c in doc.chunks if c.section_path[1].startswith("5.1 ")]
    assert len(s51) >= 2, f"Expected at least 2 chunks for 5.1, got {len(s51)}"
    assert all(c.kind is ChunkKind.clause for c in s51)
    # Verify last chunk is from section 5.2
    assert any("5.2" in c.section_path[1] for c in doc.chunks)
    assert all(estimate_tokens(c.text) <= 600 for c in doc.chunks)


def test_general_terms_chapter_and_section_detection():
    """Test chapter and section number detection."""
    text_lines = [
        "Conditii Generale Demo",
        "1. DEFINITII SI TERMENI",
        "N.1 Termeni generali Aici sunt termenii demo.",
        "N.2 Definitii specifice Aici sunt definitiile demo.",
        "2. PREVEDERI GENERALE",
        "N.3 Obligatii Textul despre obligatii demo."
    ]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    assert len(doc.chunks) == 3
    assert doc.chunks[0].section_path == ["1. Definitii Si Termeni", "N.1 Termeni generali Aici sunt termenii demo."]
    assert doc.chunks[1].section_path == ["1. Definitii Si Termeni", "N.2 Definitii specifice Aici sunt definitiile demo."]
    assert doc.chunks[2].section_path == ["2. Prevederi Generale", "N.3 Obligatii Textul despre obligatii demo."]


def test_general_terms_title_extraction():
    """Test title extraction from first line."""
    text_lines = [
        "Conditii generale de emitere si utilizare a cardurilor",
        "1. INTRODUCERE",
        "N.1 Prezentare Text demo aici."
    ]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    assert doc.title == "Conditii generale de emitere si utilizare a cardurilor"


def test_general_terms_parser_name():
    """Test parser metadata."""
    text_lines = [
        "Conditii Demo",
        "1. CAPITOL TEST",
        "N.1 Sectiune demo Text aici."
    ]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    assert doc.parser_name == "general_terms"
    assert doc.chunks[0].kind is ChunkKind.clause


def test_general_terms_section_title_capping():
    """Test section title is capped at 90 chars and stops at first sub-clause."""
    long_title = "A" * 120
    text_lines = [
        "Conditii Demo",
        "1. CAPITOL",
        f"N.1 {long_title} N.1.1 Subclauza text."
    ]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    section_title = doc.chunks[0].section_path[1]
    # Should be capped and not include the subclause
    assert len(section_title) <= 100  # N.1 + space + 90 chars + potential truncation
    assert "N.1.1" not in section_title
