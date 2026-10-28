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
    # Section path has correct h2
    assert all(c.section_path[0] == "Credite demo în detaliu" for c in cards)
    assert cards[0].text == "Credit Demo fără ipotecă\nAplici ușor. Dobândă de la 6,10%."
    assert cards[0].products_override == [Product.personal_loan] and cards[1].products_override == [Product.overdraft]
    assert [l.link_kind for l in cards[0].links] == [LinkKind.card]


def test_hub_article_teasers_one_block_without_chip_link():
    block = [c for c in _hub().chunks if c.kind is ChunkKind.hub_teasers]
    assert len(block) == 1 and block[0].text.count("\n- ") == 3
    targets = [l.target_url for l in block[0].links]
    assert len(targets) == 3 and all("/carduri/" not in t for t in targets)
    assert all(l.link_kind is LinkKind.teaser for l in block[0].links)
    # Section path and text start with h2
    assert block[0].section_path[0] == "Vrei să știi mai multe?"
    assert block[0].text.startswith("Vrei să știi mai multe?")


def test_hub_faq_and_intro_dropped():
    doc = _hub()
    assert sum(c.kind is ChunkKind.faq for c in doc.chunks) == 2
    assert not any("Descoperă soluțiile noastre" in c.text for c in doc.chunks)
    assert doc.parser_name == "category_hub"
    # FAQ chunks have correct h2
    faq = [c for c in doc.chunks if c.kind is ChunkKind.faq]
    assert all(c.section_path[0] == "FAQ Întrebări frecvente" for c in faq)


def test_hub_chunk_order_deterministic():
    """Chunks appear in document order."""
    doc = _hub()
    kinds = [c.kind for c in doc.chunks]
    # Expected order: 2 cards, 1 teasers block, 2 FAQs
    assert kinds == [ChunkKind.hub_card, ChunkKind.hub_card, ChunkKind.hub_teasers, ChunkKind.faq, ChunkKind.faq]


def test_chip_rule_button_only_card():
    """Chip detection: button-only card + 2 article teasers with same image = chip."""
    from src.services.document_ingestion.parsers.category_hub import parse_category_hub

    # Create a hub with: 1 button-only card (target X), 2 article teasers with image link X
    # Use proper raiffeisen.ro URLs that will pass is_allowed_url
    product_url = "/ro/persoane-fizice/produsele-noastre/credite/product-demo.html"
    article1_url = "/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale/article-1.html"
    article2_url = "/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale/article-2.html"

    html = f"""
    <html><body><main>
    <h1>Test Hub</h1>
    <h2>Products</h2>
    <article class="cmp-teaser">
        <h3>Button-only Card</h3>
        <p>Description</p>
        <div class="cmp-buttonbar"><a href="{product_url}">View</a></div>
    </article>
    <h2>Articles</h2>
    <article class="cmp-teaser">
        <header class="cmp-teaser__header">
            <a class="cmp-image__link" href="{product_url}"><img src="img.jpg"/></a>
        </header>
        <h3>Article 1</h3>
        <p>Text</p>
        <div class="cmp-buttonbar"><a href="{article1_url}">Citește articolul</a></div>
    </article>
    <article class="cmp-teaser">
        <header class="cmp-teaser__header">
            <a class="cmp-image__link" href="{product_url}"><img src="img.jpg"/></a>
        </header>
        <h3>Article 2</h3>
        <p>Text</p>
        <div class="cmp-buttonbar"><a href="{article2_url}">Citește articolul</a></div>
    </article>
    </main></body></html>
    """

    doc = parse_category_hub(html.encode(), BASE + "test.html", CFG)

    # The card should still have its link (not stripped as chip)
    cards = [c for c in doc.chunks if c.kind == ChunkKind.hub_card]
    assert len(cards) == 1
    assert len(cards[0].links) == 1  # Card link should be present

    # The article teasers block should not have product_url (it's a chip)
    teasers = [c for c in doc.chunks if c.kind == ChunkKind.hub_teasers]
    assert len(teasers) == 1
    assert all("product-demo.html" not in l.target_url for l in teasers[0].links)
