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

    # The article teasers block should not have product_url (filtered as chip)
    teasers = [c for c in doc.chunks if c.kind == ChunkKind.hub_teasers]
    assert len(teasers) == 1
    assert all("product-demo.html" not in l.target_url for l in teasers[0].links)


PACKAGE_HUB = """<html><head><title>Credite Demo | Banca</title></head><body><main>
<h1>Credite Demo</h1>
<h2>Descoperă și cardurile demo:</h2>
<div class="cmp-package__content">
  <div class="cmp-package__info"><h3 class="cmp-title__text"> Card Demo Standard </h3>
    <div class="cmp-package__description"></div></div>
  <div class="cmp-buttonbar-container">
    <div class="cmp-buttonbar"><a href="/ro/persoane-fizice/produsele-noastre/carduri/card-de-credit-demo.html">Detalii</a></div>
  </div>
  <div class="cmp-package__list"><div class="cmp-text"><ul><li>Limita demo: 500 și 9.000 RON</li>
    <li>Venit minim demo: 300 Eur</li></ul><p> </p></div></div>
</div>
<div class="cmp-package__content">
  <div class="cmp-package__info"><h3 class="cmp-title__text">Card Demo Plus</h3></div>
  <div class="cmp-package__list"><div class="cmp-text"><ul><li>Limita demo: 1.000 și 20.000 RON</li></ul></div></div>
</div>
</main></body></html>""".encode("utf-8")


def test_hub_package_tiles_become_cards():
    """A real hub lists credit cards as package tiles (title and a fact list), not as teasers."""
    cards = [c for c in parse_category_hub(PACKAGE_HUB, BASE[:-1] + ".html", CFG).chunks if c.kind is ChunkKind.hub_card]
    assert [c.section_path for c in cards] == [["Descoperă și cardurile demo:", "Card Demo Standard"],
                                               ["Descoperă și cardurile demo:", "Card Demo Plus"]]
    assert cards[0].text == "Card Demo Standard\n- Limita demo: 500 și 9.000 RON\n- Venit minim demo: 300 Eur"
    assert cards[1].text == "Card Demo Plus\n- Limita demo: 1.000 și 20.000 RON"
    assert cards[0].products_override == [Product.credit_card]
    assert [(l.link_kind, l.anchor_text) for l in cards[0].links] == [(LinkKind.card, "Card Demo Standard")]
    assert cards[1].links == [] and cards[1].products_override is None


PROSE_HUB = """<html><head><title>Refinantare Demo | Banca</title></head><body><main>
<h1>Refinantare Demo</h1><p>Intro demo.</p>
<h2>Mai multe despre refinanțarea demo</h2>
<h3>Cum funcționează refinanțarea demo?</h3><p>Stingi creditele demo vechi.</p><p>Plătești o singură rată demo.</p>
<h3>Cine poate beneficia?</h3><ul><li>Orice client demo cu mai multe credite.</li></ul>
<h3>Calculează rata demo</h3><p>Folosește calculatorul demo.</p>
<h2>Aplicația demo</h2><p>Descarcă aplicația demo.</p>
</main></body></html>""".encode("utf-8")


def test_hub_prose_subsections_are_kept():
    """A real hub explains refinancing in h3 subsections of plain prose, with no teasers or accordions."""
    chunks = parse_category_hub(PROSE_HUB, BASE + "credite-de-refinantare.html", CFG).chunks
    assert [(c.kind, c.section_path, c.text) for c in chunks] == [
        (ChunkKind.section, ["Mai multe despre refinanțarea demo", "Cum funcționează refinanțarea demo?"],
         "Stingi creditele demo vechi.\nPlătești o singură rată demo."),
        (ChunkKind.section, ["Mai multe despre refinanțarea demo", "Cine poate beneficia?"],
         "- Orice client demo cu mai multe credite."),
    ]
