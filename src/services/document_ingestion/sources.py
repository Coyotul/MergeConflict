"""Source configuration and document classification."""
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

import yaml
from pydantic import BaseModel

from src.models.knowledge import DocKind, ChunkKind, Product, Topic
from src.services.document_ingestion.normalize import fold_accents


class PatternRule(BaseModel):
    """A pattern-based rule with a value."""
    pattern: str
    value: DocKind


class ProductRule(BaseModel):
    """A pattern-based rule for products."""
    pattern: str
    products: list[Product]


class TopicRule(BaseModel):
    """A pattern-based rule for topics."""
    pattern: str
    topic: Topic


class FeeSectionRule(BaseModel):
    """A rule for fee list sections based on heading keywords."""
    pattern: str
    topic: Topic
    products: list[Product]


class SourceConfig(BaseModel):
    """Configuration for RAG source crawling and classification."""
    sitemap_url: str
    page_allow: list[str]
    pdf_allow: list[str]
    discovery_seeds: list[str]
    extra_urls: list[str]
    drop_headings: list[str]
    category_hubs: list[str]
    link_drop_patterns: list[str]
    doc_kind_rules: list[PatternRule]
    product_rules: list[ProductRule]
    topic_keyword_rules: list[TopicRule]
    general_terms_sections: dict[str, Topic]
    fee_list_sections: list[FeeSectionRule]
    default_topic_by_doc_kind: dict[DocKind, Topic]


def load_source_config(path: Path) -> SourceConfig:
    """Load source configuration from YAML file."""
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return SourceConfig(**data)


def _strip_query_fragment(url: str) -> str:
    """Strip query string and fragment from URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def products_for_url(url: str, cfg: SourceConfig) -> list[Product]:
    """Get products for a URL based on product rules.

    Returns first matching rule's products, else [Product.general].
    """
    for rule in cfg.product_rules:
        if re.search(rule.pattern, url):
            return rule.products
    return [Product.general]


def classify_document(url: str, cfg: SourceConfig) -> tuple[DocKind, list[Product]]:
    """Classify document kind and products from URL.

    - Category hubs (exact match after stripping query/fragment) → category_hub
    - First matching doc_kind rule
    - Else: pdf_generic for .pdf, product_page otherwise

    Products from products_for_url.
    """
    stripped_url = _strip_query_fragment(url)

    # Check category hubs
    for hub in cfg.category_hubs:
        if _strip_query_fragment(hub) == stripped_url:
            return (DocKind.category_hub, products_for_url(url, cfg))

    # Check doc_kind rules
    for rule in cfg.doc_kind_rules:
        if re.search(rule.pattern, url):
            return (rule.value, products_for_url(url, cfg))

    # Default
    if url.endswith('.pdf'):
        return (DocKind.pdf_generic, products_for_url(url, cfg))
    else:
        return (DocKind.product_page, products_for_url(url, cfg))


def is_allowed_url(url: str, cfg: SourceConfig) -> bool:
    """Check if URL is allowed based on allowlist and drop patterns.

    Returns True when URL (query and fragment stripped) matches any page_allow
    or pdf_allow pattern and no link_drop_patterns pattern.
    """
    stripped_url = _strip_query_fragment(url)

    # Check drop patterns first
    for pattern in cfg.link_drop_patterns:
        if re.search(pattern, stripped_url):
            return False

    # Check allow patterns
    for pattern in cfg.page_allow + cfg.pdf_allow:
        if re.search(pattern, stripped_url):
            return True

    return False


def _longest_number_prefix_match(section_str: str, mapping: dict[str, Any]) -> Any | None:
    """Find longest number prefix match in section string.

    Example: "3.4.1 Text" matches "3.4" if "3.4" is in mapping and "3.4.1" is not.
    """
    # Extract number prefix from section string
    match = re.match(r'^(\d+(?:\.\d+)*)', section_str)
    if not match:
        return None

    number = match.group(1)
    parts = number.split('.')

    # Try from longest to shortest prefix
    for i in range(len(parts), 0, -1):
        prefix = '.'.join(parts[:i])
        if prefix in mapping:
            return mapping[prefix]

    return None


def fee_section_products(section_path: list[str], cfg: SourceConfig) -> list[Product] | None:
    """Get products for a fee list section based on heading keyword match.

    Returns products from first matching FeeSectionRule on section_path[0],
    or None if no match (caller falls back to document products).
    """
    if not section_path:
        return None

    top_heading = section_path[0]
    top_heading_normalized = fold_accents(top_heading)

    for rule in cfg.fee_list_sections:
        pattern_normalized = fold_accents(rule.pattern)
        if re.search(pattern_normalized, top_heading_normalized):
            return rule.products

    return None


def classify_topic(
    doc_kind: DocKind,
    chunk_kind: ChunkKind,
    section_path: list[str],
    text: str,
    cfg: SourceConfig
) -> Topic:
    """Classify topic based on document context.

    Priority:
    1. chunk_kind == worked_example → worked_example
    2. chunk_kind == cost_facts → costs_fees
    3. general_terms / fee_list: number-prefix or heading-keyword match
    4. First topic_keyword_rules match on section_path + text[:300]
    5. default_topic_by_doc_kind[doc_kind], else other
    """
    # Rule 1: worked_example chunk
    if chunk_kind == ChunkKind.worked_example:
        return Topic.worked_example

    # Rule 2: cost_facts chunk
    if chunk_kind == ChunkKind.cost_facts:
        return Topic.costs_fees

    # Rule 3a: general_terms sections (number prefix)
    if doc_kind == DocKind.general_terms and section_path:
        # Try both section_path[-1] and section_path[0]
        for section_str in [section_path[-1], section_path[0]]:
            result = _longest_number_prefix_match(section_str, cfg.general_terms_sections)
            if result is not None:
                return result

    # Rule 3b: fee_list sections (heading keyword)
    if doc_kind == DocKind.fee_list and section_path:
        top_heading = section_path[0]
        top_heading_normalized = fold_accents(top_heading)

        for rule in cfg.fee_list_sections:
            pattern_normalized = fold_accents(rule.pattern)
            if re.search(pattern_normalized, top_heading_normalized):
                return rule.topic

    # Rule 4: topic keyword rules
    search_text = " ".join(section_path) + " " + text[:300]
    search_text_normalized = fold_accents(search_text)

    for rule in cfg.topic_keyword_rules:
        pattern_normalized = fold_accents(rule.pattern)
        if re.search(pattern_normalized, search_text_normalized):
            return rule.topic

    # Rule 5: default by doc_kind
    if doc_kind in cfg.default_topic_by_doc_kind:
        return cfg.default_topic_by_doc_kind[doc_kind]

    return Topic.other
