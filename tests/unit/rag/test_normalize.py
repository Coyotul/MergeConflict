"""Tests for text normalization."""
from src.services.document_ingestion.normalize import fold_accents, normalize_text


def test_normalize_text():
    assert normalize_text("Dobânda  fixă la\tşi ţară") == "Dobânda fixă la și țară"


def test_normalize_text_nfc():
    # Test NFC normalization
    assert normalize_text("café") == "café"


def test_normalize_text_nbsp():
    # Test NBSP replacement
    text = "Rate\xa0fixe"
    assert normalize_text(text) == "Rate fixe"


def test_normalize_text_collapses_whitespace():
    text = "Multiple    spaces  and\t\ttabs"
    assert normalize_text(text) == "Multiple spaces and tabs"


def test_normalize_text_keeps_single_newlines():
    text = "Line 1\nLine 2\nLine 3"
    assert normalize_text(text) == "Line 1\nLine 2\nLine 3"


def test_normalize_text_collapses_multiple_newlines():
    text = "Para 1\n\n\n\nPara 2"
    assert normalize_text(text) == "Para 1\n\nPara 2"


def test_normalize_text_trims_lines():
    text = "  Line 1  \n  Line 2  "
    assert normalize_text(text) == "Line 1\nLine 2"


def test_fold_accents_strips_diacritics_and_lowercases():
    assert fold_accents("Dobândă FIXĂ, ȘI ţară Țară") == "dobanda fixa, si tara tara"
    assert fold_accents("Plată  anticipată") == "plata  anticipata"   # whitespace is left alone
