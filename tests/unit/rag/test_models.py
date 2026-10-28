"""Tests for shared knowledge models and taxonomies."""
import pytest
from datetime import date, datetime

from src.models.knowledge import (
    DocKind,
    ChunkKind,
    Authority,
    AUTHORITY_BY_DOC_KIND,
    LinkKind,
    RelatedLink,
    Product,
    Topic,
    CREDIT_TOPICS,
    PassageFlag,
    SearchStatus,
    SearchQuery,
    Citation,
    Scores,
    PassageContext,
    Passage,
    Conflict,
    IndexInfo,
    SearchResult,
)
from pydantic import ValidationError


def test_query_text_validation():
    """Test that SearchQuery text is stripped and within 1-1000 chars."""
    with pytest.raises(ValidationError):
        SearchQuery(text="   ")
    with pytest.raises(ValidationError):
        SearchQuery(text="a" * 1001)
    assert SearchQuery(text="  Ce este DAE?  ").text == "Ce este DAE?"


def test_default_topics_are_credit_topics():
    """Test that when topics is None, effective_topics returns CREDIT_TOPICS."""
    q = SearchQuery(text="dobanda")
    assert set(q.effective_topics) == CREDIT_TOPICS
    assert Topic.accounts not in CREDIT_TOPICS and len(CREDIT_TOPICS) == 11


def test_top_k_bounds():
    """Test that top_k must be between 1 and 20."""
    with pytest.raises(ValidationError):
        SearchQuery(text="x", top_k=21)


def test_result_marks_content_untrusted():
    """Test that SearchResult always marks content as untrusted_evidence."""
    assert SearchResult(status=SearchStatus.ok).content_trust == "untrusted_evidence"


def test_authority_map_complete():
    """Test that AUTHORITY_BY_DOC_KIND covers all DocKind values with correct mappings."""
    assert set(AUTHORITY_BY_DOC_KIND) == set(DocKind)
    assert AUTHORITY_BY_DOC_KIND[DocKind.article] is Authority.low
    assert AUTHORITY_BY_DOC_KIND[DocKind.category_hub] is Authority.low
