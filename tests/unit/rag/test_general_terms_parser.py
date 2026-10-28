"""Tests for general terms parser."""
import pytest
from src.models.knowledge import ChunkKind
from src.services.document_ingestion.parsers.general_terms import parse_general_terms
from src.services.document_ingestion.chunking import estimate_tokens
from tests.fixtures.rag.pdf_builders import make_pdf_from_lines


def test_general_terms_splits_by_numbering_including_flattened_subclauses():
    """Test general terms parsing with flattened sub-clauses."""
    long = " ".join(f"5.1.{i} Clauza demo {i} " + "text demonstrativ. " * 40 for i in range(1, 6))
    text_lines = [
        "Conditii Generale Demo Editia 01.01.2026",
        "5. PREVEDERI DEMO CARDURI",
        "5.1 Emiterea demo " + long,
        "5.2 Utilizatori demo Text scurt."
    ]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    s51 = [c for c in doc.chunks if c.section_path[1].startswith("5.1 ")]
    assert len(s51) >= 2
    assert all(c.kind is ChunkKind.clause for c in s51)
    assert doc.chunks[-1].section_path == ["5. Prevederi Demo Carduri", "5.2 Utilizatori demo Text scurt."]
    assert all(estimate_tokens(c.text) <= 600 for c in doc.chunks)


def test_general_terms_chapter_and_section_detection():
    """Test chapter and section number detection."""
    text_lines = [
        "Conditii Generale Demo",
        "1. DEFINITII SI TERMENI",
        "1.1 Termeni generali Aici sunt termenii demo.",
        "1.2 Definitii specifice Aici sunt definitiile demo.",
        "2. PREVEDERI GENERALE",
        "2.1 Obligatii Textul despre obligatii demo."
    ]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    assert len(doc.chunks) == 3
    assert doc.chunks[0].section_path == ["1. Definitii Si Termeni", "1.1 Termeni generali Aici sunt termenii demo."]
    assert doc.chunks[1].section_path == ["1. Definitii Si Termeni", "1.2 Definitii specifice Aici sunt definitiile demo."]
    assert doc.chunks[2].section_path == ["2. Prevederi Generale", "2.1 Obligatii Textul despre obligatii demo."]


def test_general_terms_title_extraction():
    """Test title extraction from first line."""
    text_lines = [
        "Conditii generale de emitere si utilizare a cardurilor",
        "1. INTRODUCERE",
        "1.1 Prezentare Text demo aici."
    ]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    assert doc.title == "Conditii generale de emitere si utilizare a cardurilor"


def test_general_terms_parser_name():
    """Test parser metadata."""
    text_lines = [
        "Conditii Demo",
        "1. CAPITOL TEST",
        "1.1 Sectiune demo Text aici."
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
        f"1.1 {long_title} 1.1.1 Subclauza text."
    ]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    section_title = doc.chunks[0].section_path[1]
    # Should be capped and not include the subclause
    assert len(section_title) <= 100  # 1.1 + space + 90 chars + potential truncation
    assert "1.1.1" not in section_title


def test_general_terms_rejects_cross_reference_as_section():
    """A wrapped line that starts with a cross-reference ("3.4 din ...") inside chapter 5 is not a section."""
    text_lines = [
        "Conditii Demo",
        "5. CAPITOL CINCI DEMO",
        "5.1 Prima sectiune Clientul respecta obligatiile prevazute la punctul",
        "3.4 din prezentele Conditii, clientul demo informeaza banca in scris.",
        "5.2 A doua sectiune Text scurt."
    ]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    paths = [c.section_path for c in doc.chunks]
    assert paths == [
        ["5. Capitol Cinci Demo", "5.1 Prima sectiune Clientul respecta obligatiile prevazute la punctul"],
        ["5. Capitol Cinci Demo", "5.2 A doua sectiune Text scurt."],
    ]
    assert "3.4 din prezentele Conditii, clientul demo informeaza banca in scris." in doc.chunks[0].text
    assert "3.4" not in doc.chunks[1].text


def test_pack_clauses_estimates_joined_text_not_sum_of_parts():
    """Parts that sum to <= MAX_TOKENS can join to > MAX_TOKENS; every chunk must stay <= MAX_TOKENS."""
    from src.services.document_ingestion.chunking import MAX_TOKENS
    from src.services.document_ingestion.parsers.general_terms import _pack_clauses

    # Clause packing: five clauses of 401 chars (100 tokens each) sum to 500,
    # but joined with newlines they are 2009 chars = 502 tokens.
    clauses = [f"5.1.{i} " + "c" * (401 - len(f"5.1.{i} ")) for i in range(1, 6)]
    assert sum(estimate_tokens(c) for c in clauses) == MAX_TOKENS
    packed = _pack_clauses(clauses)
    assert all(estimate_tokens(p) <= MAX_TOKENS for p in packed)
    assert "\n".join(packed) == "\n".join(clauses)

    # Sentence windowing: one over-long clause of 401-char sentences (100 tokens each).
    sentences = [f"Fraza {i:02d} " + "s" * (401 - len(f"Fraza {i:02d} ") - 1) + "." for i in range(12)]
    windowed = _pack_clauses([" ".join(sentences)])
    assert all(estimate_tokens(p) <= MAX_TOKENS for p in windowed)
    for sentence in sentences:
        assert any(sentence in p for p in windowed)


def test_general_terms_windowing_respects_max_tokens():
    """Test that sentence windowing produces chunks within MAX_TOKENS."""
    # Create a section with a very long sentence
    huge_sentence = "Text " * 1000  # 5000 chars, ~1250 tokens
    text_lines = [
        "Conditii Demo",
        "5. CAPITOL TEST",
        f"5.1 Sectiune demo {huge_sentence} Mai mult text dupa."
    ]
    doc = parse_general_terms(make_pdf_from_lines(text_lines))
    # All chunks must be <= MAX_TOKENS (500)
    for chunk in doc.chunks:
        tokens = estimate_tokens(chunk.text)
        assert tokens <= 500, f"Chunk has {tokens} tokens, exceeds MAX_TOKENS=500"
