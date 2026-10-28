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
