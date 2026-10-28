"""Tests for PDF row rebuilding."""
import pytest
from src.services.document_ingestion.parsers.pdf_rows import Word, rebuild_rows


def test_rebuild_rows_joins_columns():
    """Test that rebuild_rows joins columns with | separator."""
    words = [
        Word(10, 100, 60, 108, "Comision"),
        Word(62, 100, 90, 108, "analiză"),
        Word(300, 101, 330, 109, "200"),
        Word(332, 101, 350, 109, "lei")
    ]
    assert rebuild_rows(words) == ["Comision analiză | 200 lei"]


def test_rebuild_rows_multiple_rows():
    """Test rebuild_rows with multiple rows."""
    words = [
        Word(10, 100, 60, 108, "First"),
        Word(300, 100, 330, 108, "Value1"),
        Word(10, 120, 60, 128, "Second"),
        Word(300, 120, 330, 128, "Value2"),
    ]
    result = rebuild_rows(words)
    assert len(result) == 2
    assert result[0] == "First | Value1"
    assert result[1] == "Second | Value2"


def test_rebuild_rows_same_row_no_separator():
    """Test that words in same row without large gap are joined with space."""
    words = [
        Word(10, 100, 60, 108, "Word1"),
        Word(65, 100, 110, 108, "Word2"),
        Word(115, 100, 160, 108, "Word3"),
    ]
    assert rebuild_rows(words) == ["Word1 Word2 Word3"]


def test_furniture_filter_counts_distinct_pages():
    """Test that furniture filtering counts distinct pages, not occurrences."""
    from tests.fixtures.rag.pdf_builders import make_pdf
    from src.services.document_ingestion.parsers.pdf_rows import pdf_lines
    
    # Create a 4-page PDF where "Header" appears twice on page 1 only
    pdf = make_pdf([
        [(50, 60, "Header"), (50, 80, "Header"), (50, 100, "Content page 1")],
        [(50, 60, "Content page 2")],
        [(50, 60, "Content page 3")],
        [(50, 60, "Content page 4")],
    ])
    
    lines = pdf_lines(pdf, skip_first_page=False)
    line_texts = [line for _, line in lines]
    
    # "Header" appears on 1 of 4 pages (25%), should NOT be filtered
    assert "Header" in line_texts
    # All content should be present
    assert "Content page 1" in line_texts
    assert "Content page 2" in line_texts


def test_make_pdf_roundtrips_romanian_diacritics():
    """Test that make_pdf preserves Romanian diacritics."""
    from tests.fixtures.rag.pdf_builders import make_pdf
    from src.services.document_ingestion.parsers.pdf_rows import pdf_lines
    
    # Create PDF with Romanian diacritics
    text = "Plăți în lei: ș ț ă î â"
    pdf = make_pdf([
        [(50, 60, text)],
    ])
    
    lines = pdf_lines(pdf, skip_first_page=False)
    extracted_texts = [line for _, line in lines]
    
    # Should extract exactly the same text
    assert len(extracted_texts) == 1
    assert extracted_texts[0] == text


def test_make_pdf_from_lines_roundtrips_romanian_diacritics_and_wraps_without_loss():
    """Wrapped lines keep every word, diacritics included."""
    from tests.fixtures.rag.pdf_builders import make_pdf_from_lines
    from src.services.document_ingestion.parsers.pdf_rows import pdf_lines

    long_line = " ".join(f"Plăți{i} în lei ș ț ă î â" for i in range(60))
    pdf = make_pdf_from_lines(["Titlu demo cu diacritice: ș ț ă î â", long_line])

    texts = [line for _, line in pdf_lines(pdf)]
    assert texts[0] == "Titlu demo cu diacritice: ș ț ă î â"
    assert len(texts) > 2  # the long line wrapped
    assert " ".join(texts[1:]) == long_line


def test_make_pdf_from_lines_raises_instead_of_clipping():
    """A word that cannot fit on a line must raise, never be silently clipped."""
    from tests.fixtures.rag.pdf_builders import make_pdf_from_lines

    with pytest.raises(ValueError):
        make_pdf_from_lines(["Ă" * 200])


def test_furniture_line_on_one_page_of_two_is_kept():
    """A line written twice on page 1 of a 2-page PDF appears on 1 distinct page: kept."""
    from tests.fixtures.rag.pdf_builders import make_pdf
    from src.services.document_ingestion.parsers.pdf_rows import pdf_lines

    pdf = make_pdf([
        [(50, 60, "Antet demo"), (50, 80, "Antet demo"), (50, 100, "Continut pagina 1")],
        [(50, 60, "Continut pagina 2")],
    ])
    texts = [line for _, line in pdf_lines(pdf)]
    assert texts == ["Antet demo", "Antet demo", "Continut pagina 1", "Continut pagina 2"]


def test_furniture_footer_on_two_of_four_pages_is_dropped():
    """A footer on 2 of 4 pages (50%) is page furniture."""
    from tests.fixtures.rag.pdf_builders import make_pdf
    from src.services.document_ingestion.parsers.pdf_rows import pdf_lines

    pdf = make_pdf([
        [(50, 60, "Continut 1"), (50, 800, "Subsol demo")],
        [(50, 60, "Continut 2")],
        [(50, 60, "Continut 3"), (50, 800, "Subsol demo")],
        [(50, 60, "Continut 4")],
    ])
    texts = [line for _, line in pdf_lines(pdf)]
    assert texts == ["Continut 1", "Continut 2", "Continut 3", "Continut 4"]


def test_furniture_footer_on_one_of_four_pages_is_kept():
    """A footer on 1 of 4 pages (25%) is kept, even when written twice on that page."""
    from tests.fixtures.rag.pdf_builders import make_pdf
    from src.services.document_ingestion.parsers.pdf_rows import pdf_lines

    pdf = make_pdf([
        [(50, 60, "Continut 1"), (50, 780, "Subsol demo"), (50, 800, "Subsol demo")],
        [(50, 60, "Continut 2")],
        [(50, 60, "Continut 3")],
        [(50, 60, "Continut 4")],
    ])
    texts = [line for _, line in pdf_lines(pdf)]
    assert texts == ["Continut 1", "Subsol demo", "Subsol demo", "Continut 2", "Continut 3", "Continut 4"]
