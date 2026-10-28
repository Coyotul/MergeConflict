"""Category hub parser for product overview pages."""
from collections import defaultdict
from bs4 import BeautifulSoup, Tag

from src.services.document_ingestion.chunking import (
    ChunkDraft,
    ParsedDocument,
    ExtractedLink,
    CHUNKER_VERSION,
    pack_lines,
)
from src.services.document_ingestion.parsers.html_page import clean_html, accordion_chunk
from src.services.document_ingestion.parsers.links import absolutize, filter_chunk_links
from src.services.document_ingestion.parsers.text_utils import extract_text
from src.services.document_ingestion.sources import SourceConfig, products_for_url
from src.services.document_ingestion.normalize import normalize_text
from src.models.knowledge import ChunkKind, Product, LinkKind


COMPONENT_CLASSES = ("cmp-teaser", "cmp-package__content", "cmp-accordion__item")


def _prose_chunks(h2_elem: Tag, h2_text: str, cfg: SourceConfig) -> list[ChunkDraft]:
    """Plain prose under the h3 subsections of an h2 that holds no cards, teasers or FAQs.

    Text directly under the h2 is dropped like the page intro; so are subsections
    whose heading matches drop_headings.
    """
    chunks: list[ChunkDraft] = []
    heading: str | None = None
    lines: list[str] = []

    def flush() -> None:
        if heading is not None and lines and not any(p in heading for p in cfg.drop_headings):
            for piece in pack_lines([normalize_text(line) for line in lines]):
                chunks.append(ChunkDraft(kind=ChunkKind.section, section_path=[h2_text, heading], text=piece))

    for elem in h2_elem.find_all_next(["h2", "h3", "p", "li"]):
        if elem.name == "h2":
            break
        if any(elem.find_parent(class_=c) for c in COMPONENT_CLASSES) or elem.find_parent(["li", "table"]):
            continue
        if elem.name == "h3":
            flush()
            heading, lines = extract_text(elem), []
        elif text := extract_text(elem):
            lines.append(f"- {text}" if elem.name == "li" else text)
    flush()
    return chunks


def _package_card(package: Tag, h2_text: str, page_url: str, cfg: SourceConfig) -> ChunkDraft:
    """A package tile as a hub card: its title, then one line per listed fact."""
    h3 = package.find('h3')
    card_title = extract_text(h3) if h3 else ""
    facts = [f"- {text}" for li in package.select('li') if (text := extract_text(li))]
    button = package.select_one('.cmp-buttonbar a')
    target = absolutize(button.get('href', ''), page_url) if button else None
    return ChunkDraft(
        kind=ChunkKind.hub_card,
        section_path=[h2_text, card_title],
        text=normalize_text("\n".join([card_title] + facts)),
        products_override=products_for_url(target, cfg) if target else None,
        links=[ExtractedLink(target_url=target, anchor_text=card_title, link_kind=LinkKind.card)] if target else [],
    )


def parse_category_hub(data: bytes, page_url: str, cfg: SourceConfig) -> ParsedDocument:
    """Parse a category hub page.

    Returns ParsedDocument with parser_name="category_hub".
    """
    soup = clean_html(data)

    # Extract title from <title> before |
    title_tag = soup.find('title')
    if title_tag:
        title_text = title_tag.get_text()
        title = title_text.split('|')[0].strip()
    else:
        title = "Untitled"

    chunks = []
    all_text_parts = []

    # Drop h1 and intro paragraphs (before first h2)
    main = soup.find('main') or soup.find('body')

    # Find all h2s in document order
    all_h2s = main.select('h2')

    # Collect all teasers and accordions
    all_teasers = main.select('article.cmp-teaser')
    all_accordions = main.select('div.cmp-accordion__item')

    # Group teasers and accordions by their nearest preceding h2
    teasers_by_h2 = defaultdict(list)
    for teaser in all_teasers:
        # Find nearest preceding h2 in document order
        prev_h2 = teaser.find_previous('h2')
        if prev_h2:
            h2_text = extract_text(prev_h2)
            teasers_by_h2[h2_text].append(teaser)

    # Package tiles (title plus a fact list, e.g. credit cards) are product cards too
    packages_by_h2 = defaultdict(list)
    for package in main.select('div.cmp-package__content'):
        prev_h2 = package.find_previous('h2')
        if prev_h2:
            packages_by_h2[extract_text(prev_h2)].append(package)

    accordions_by_h2 = defaultdict(list)
    for accordion in all_accordions:
        # Find nearest preceding h2 in document order
        prev_h2 = accordion.find_previous('h2')
        if prev_h2:
            h2_text = extract_text(prev_h2)
            accordions_by_h2[h2_text].append(accordion)

    # Collect all button targets (for chip detection)
    all_button_targets = set()
    for teaser in all_teasers:
        button = teaser.select_one('.cmp-buttonbar a')
        button_href = button.get('href', '') if button else None
        button_url = absolutize(button_href, page_url) if button_href else None
        if button_url:
            all_button_targets.add(button_url)

    # Count distinct teasers per target URL
    target_teaser_count = defaultdict(set)  # URL -> set of teaser indices
    for idx, teaser in enumerate(all_teasers):
        # Get button link
        button = teaser.select_one('.cmp-buttonbar a')
        button_href = button.get('href', '') if button else None
        button_url = absolutize(button_href, page_url) if button_href else None

        # Get image link
        image_link = teaser.select_one('a.cmp-image__link')
        image_href = image_link.get('href', '') if image_link else None
        image_url = absolutize(image_href, page_url) if image_href else None

        # Track this teaser for each of its URLs
        if button_url:
            target_teaser_count[button_url].add(idx)
        if image_url:
            target_teaser_count[image_url].add(idx)

    # Chip targets: appears in ≥2 distinct teasers AND not a button target
    chip_targets = frozenset(
        url for url, teaser_set in target_teaser_count.items()
        if len(teaser_set) >= 2 and url not in all_button_targets
    )

    # Process each h2 section in document order
    for h2_elem in all_h2s:
        h2_text = extract_text(h2_elem)

        teasers = teasers_by_h2.get(h2_text, [])
        accordions = accordions_by_h2.get(h2_text, [])

        # Classify teasers as product cards or article teasers
        product_cards = []
        article_teasers = []

        for teaser in teasers:
            # Get button text
            button = teaser.select_one('.cmp-buttonbar a')
            button_text = extract_text(button) if button else ""

            if button_text.startswith("Citește"):
                article_teasers.append(teaser)
            else:
                product_cards.append(teaser)

        # Process product cards (one chunk each)
        for card in product_cards:
            # Extract title
            h3 = card.find('h3')
            card_title = extract_text(h3) if h3 else ""

            # Extract description
            desc_elem = card.find('p')
            description = ""
            if desc_elem:
                description = extract_text(desc_elem)

            # Get links
            button = card.select_one('.cmp-buttonbar a')
            button_href = button.get('href', '') if button else None
            button_url = absolutize(button_href, page_url) if button_href else None

            image_link = card.select_one('a.cmp-image__link')
            image_href = image_link.get('href', '') if image_link else None
            image_url = absolutize(image_href, page_url) if image_href else None

            # Primary target: button else image
            primary_target = button_url or image_url

            # Build chunk
            text = f"{card_title}\n{description}" if description else card_title
            text = normalize_text(text)

            links = []
            if primary_target:
                links.append(ExtractedLink(
                    target_url=primary_target,
                    anchor_text=card_title,
                    link_kind=LinkKind.card
                ))

            # Get products from primary target
            products_override = None
            if primary_target:
                products_override = products_for_url(primary_target, cfg)

            chunks.append(ChunkDraft(
                kind=ChunkKind.hub_card,
                section_path=[h2_text, card_title],
                text=text,
                products_override=products_override,
                links=links
            ))
            all_text_parts.append(text)

        for package in packages_by_h2.get(h2_text, []):
            chunk = _package_card(package, h2_text, page_url, cfg)
            chunks.append(chunk)
            all_text_parts.append(chunk.text)

        # Process article teasers (one combined chunk)
        if article_teasers:
            teaser_titles = []
            teaser_links = []

            for teaser in article_teasers:
                # Extract title
                h3 = teaser.find('h3')
                teaser_title = extract_text(h3) if h3 else ""
                teaser_titles.append(teaser_title)

                # Get button link
                button = teaser.select_one('.cmp-buttonbar a')
                button_href = button.get('href', '') if button else None
                button_url = absolutize(button_href, page_url) if button_href else None

                if button_url:
                    teaser_links.append(ExtractedLink(
                        target_url=button_url,
                        anchor_text=teaser_title,
                        link_kind=LinkKind.teaser
                    ))

            # Build combined chunk
            text_lines = [h2_text] + [f"- {t}" for t in teaser_titles]
            text = "\n".join(text_lines)
            text = normalize_text(text)

            chunks.append(ChunkDraft(
                kind=ChunkKind.hub_teasers,
                section_path=[h2_text],
                text=text,
                links=teaser_links
            ))
            all_text_parts.append(text)

        # Process FAQ accordions
        for accordion in accordions:
            chunk = accordion_chunk(accordion, [h2_text], page_url)
            chunks.append(chunk)
            all_text_parts.append(chunk.text)

        if not (teasers or accordions or packages_by_h2.get(h2_text)):
            for chunk in _prose_chunks(h2_elem, h2_text, cfg):
                chunks.append(chunk)
                all_text_parts.append(chunk.text)

    # Filter chunk links with chip_targets
    filter_chunk_links(chunks, page_url, cfg, chip_targets)

    # Build metadata text
    metadata_text = "\n".join(all_text_parts)
    metadata_text = normalize_text(metadata_text)

    return ParsedDocument(
        title=title,
        chunks=chunks,
        metadata_text=metadata_text,
        parser_name="category_hub"
    )
