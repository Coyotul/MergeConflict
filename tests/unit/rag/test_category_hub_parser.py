"""Tests for category hub parser."""
from pathlib import Path

from src.services.document_ingestion.parsers.category_hub import parse_category_hub
from src.services.document_ingestion.sources import load_source_config
from src.models.knowledge import ChunkKind, Product, LinkKind

CFG = load_source_config(Path("config/rag/sources.yaml"))
BASE = "https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/"
HUB_URL = BASE + "credite-de-nevoi-personale.html"


def _hub():
    return parse_category_hub(Path("tests/fixtures/rag/category_hub.html").read_bytes(), HUB_URL, CFG)


def test_hub_cards_one_chunk_each_with_product_from_link_target():
    cards = [c for c in _hub().chunks if c.kind is ChunkKind.hub_card]
    assert [c.section_path[-1] for c in cards] == ["Credit Demo fără ipotecă", "Overdraft Demo"]
    assert cards[0].text == "Credit Demo fără ipotecă\nAplici ușor. Dobândă de la 6,10%."
    assert cards[0].products_override == [Product.personal_loan] and cards[1].products_override == [Product.overdraft]
    assert [l.link_kind for l in cards[0].links] == [LinkKind.card]


def test_hub_article_teasers_one_block_without_chip_link():
    block = [c for c in _hub().chunks if c.kind is ChunkKind.hub_teasers]
    assert len(block) == 1 and block[0].text.count("\n- ") == 3
    targets = [l.target_url for l in block[0].links]
    assert len(targets) == 3 and all("/carduri/" not in t for t in targets)
    assert all(l.link_kind is LinkKind.teaser for l in block[0].links)


def test_hub_faq_and_intro_dropped():
    doc = _hub()
    assert sum(c.kind is ChunkKind.faq for c in doc.chunks) == 2
    assert not any("Descoperă soluțiile noastre" in c.text for c in doc.chunks)
    assert doc.parser_name == "category_hub"
