"""Category hub parser for product overview pages."""
from collections import defaultdict
from bs4 import BeautifulSoup, Tag

from src.services.document_ingestion.chunking import (
    ChunkDraft,
    ParsedDocument,
    ExtractedLink,
    CHUNKER_VERSION,
)
from src.services.document_ingestion.parsers.html_page import clean_html, accordion_chunk
from src.services.document_ingestion.parsers.links import absolutize, filter_chunk_links
from src.services.document_ingestion.sources import SourceConfig, products_for_url
from src.services.document_ingestion.normalize import normalize_text
from src.models.knowledge import ChunkKind, LinkKind
import re


def find_preceding_h2(elem: Tag) -> str | None:
    """Find the text of the closest preceding h2 element."""
    # Walk up the tree and at each level look for a preceding h2
    current = elem
    while current.parent and current.parent.name != 'body':
        parent = current.parent
        # Find all h2s in parent
        h2s_in_parent = parent.find_all('h2')
        if h2s_in_parent:
            # Return the last one (closest to our element)
            return h2s_in_parent[-1].get_text(strip=True)
        current = parent
    return None


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

    # Collect all teasers and accordions and group by their preceding h2
    all_teasers = main.select('article.cmp-teaser')
    all_accordions = main.select('div.cmp-accordion__item')

    # Group teasers by h2
    teasers_by_h2 = defaultdict(list)
    for teaser in all_teasers:
        h2_text = find_preceding_h2(teaser)
        if h2_text:
            teasers_by_h2[h2_text].append(teaser)

    # Group accordions by h2
    accordions_by_h2 = defaultdict(list)
    for accordion in all_accordions:
        h2_text = find_preceding_h2(accordion)
        if h2_text:
            accordions_by_h2[h2_text].append(accordion)

    # Collect all teaser targets to find chips
    teaser_targets = defaultdict(lambda: {'count': 0, 'button_targets': set()})

    for teaser in all_teasers:
        # Get button link
        button = teaser.select_one('.cmp-buttonbar a')
        button_href = button.get('href', '') if button else None
        button_url = absolutize(button_href, page_url) if button_href else None

        # Get image link
        image_link = teaser.select_one('a.cmp-image__link')
        image_href = image_link.get('href', '') if image_link else None
        image_url = absolutize(image_href, page_url) if image_href else None

        # Track occurrences
        if image_url:
            teaser_targets[image_url]['count'] += 1
            if button_url:
                teaser_targets[button_url]['button_targets'].add(button_url)

    # Find chip targets: appears in >= 2 teasers and never as button target
    chip_targets = frozenset(
        url for url, data in teaser_targets.items()
        if data['count'] >= 2 and url not in data['button_targets']
    )

    # Process each h2 section
    for h2_text in teasers_by_h2.keys() | accordions_by_h2.keys():
        teasers = teasers_by_h2.get(h2_text, [])
        accordions = accordions_by_h2.get(h2_text, [])

        # Classify teasers as product cards or article teasers
        product_cards = []
        article_teasers = []

        for teaser in teasers:
            # Get button text
            button = teaser.select_one('.cmp-buttonbar a')
            button_text = button.get_text(strip=True) if button else ""

            if button_text.startswith("Citește"):
                article_teasers.append(teaser)
            else:
                product_cards.append(teaser)

        # Process product cards (one chunk each)
        for card in product_cards:
            # Extract title
            h3 = card.find('h3')
            card_title = h3.get_text(strip=True) if h3 else ""

            # Extract description
            desc_elem = card.find('p')
            description = ""
            if desc_elem:
                # Get text and fix punctuation (but not inside numbers)
                description = desc_elem.get_text(' ', strip=True)
                description = re.sub(r" ([.,;:!?])(?!\d)", r"\1", description)

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

        # Process article teasers (one combined chunk)
        if article_teasers:
            teaser_titles = []
            teaser_links = []

            for teaser in article_teasers:
                # Extract title
                h3 = teaser.find('h3')
                teaser_title = h3.get_text(strip=True) if h3 else ""
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
