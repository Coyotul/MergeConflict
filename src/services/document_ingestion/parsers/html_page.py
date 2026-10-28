"""HTML page parser for product pages, guides, FAQs, and articles."""
import re
from bs4 import BeautifulSoup, Tag

from src.services.document_ingestion.chunking import (
    ChunkDraft,
    ParsedDocument,
    ExtractedLink,
    CHUNKER_VERSION,
    pack_lines,
)
from src.services.document_ingestion.parsers.links import absolutize, filter_chunk_links
from src.services.document_ingestion.sources import SourceConfig
from src.services.document_ingestion.normalize import normalize_text
from src.models.knowledge import ChunkKind, LinkKind


def clean_html(data: bytes) -> BeautifulSoup:
    """Parse and clean HTML.

    Removes script, style, form, noscript, and removes header, footer, nav
    only when they are not inside a .cmp-teaser (content-component headers
    and footers keep their links).
    """
    soup = BeautifulSoup(data, 'html.parser')

    # Remove unwanted tags unconditionally
    for tag in soup.select('script, style, form, noscript'):
        tag.decompose()

    # Remove header, footer, nav only if not inside .cmp-teaser
    for tag in soup.select('header, footer, nav'):
        # Check if any parent is a .cmp-teaser
        if not tag.find_parent('article', class_='cmp-teaser'):
            tag.decompose()

    return soup


def content_root(soup: BeautifulSoup) -> Tag:
    """Get content root element (<main> or <body>)."""
    main = soup.find('main')
    if main:
        return main
    return soup.find('body')


def accordion_chunk(item: Tag, path_prefix: list[str], page_url: str) -> ChunkDraft:
    """Parse an accordion item into a FAQ chunk.

    Format: "Întrebare: {q}\\nRăspuns: {a}"
    Section path: [path_prefix..., q]
    """
    # Extract question
    title_elem = item.select_one('.cmp-accordion__title')
    question = title_elem.get_text(strip=True) if title_elem else ""

    # Extract answer from panel
    panel = item.select_one('.cmp-accordion__panel')
    answer_parts = []
    links = []

    if panel:
        for elem in panel.select('p, li'):
            text = elem.get_text(strip=True)
            if text:
                # Add prefix for list items
                if elem.name == 'li':
                    text = "- " + text
                answer_parts.append(text)

            # Extract links
            for a in elem.select('a[href]'):
                href = a.get('href', '')
                absolute_url = absolutize(href, page_url)
                if absolute_url:
                    anchor_text = a.get_text(strip=True)
                    links.append(ExtractedLink(
                        target_url=absolute_url,
                        anchor_text=anchor_text,
                        link_kind=LinkKind.inline
                    ))

    answer = "\n".join(answer_parts)

    # Build text
    text = f"Întrebare: {question}\nRăspuns: {answer}"
    text = normalize_text(text)

    return ChunkDraft(
        kind=ChunkKind.faq,
        section_path=path_prefix + [question],
        text=text,
        links=links
    )


def parse_html_page(data: bytes, page_url: str, cfg: SourceConfig) -> ParsedDocument:
    """Parse a generic HTML page (product pages, guides, FAQs, articles).

    Returns ParsedDocument with parser_name="html_page".
    """
    soup = clean_html(data)
    root = content_root(soup)

    # Extract title
    h1 = root.find('h1')
    if h1:
        title = h1.get_text(strip=True)
    else:
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text()
            # Take text before |
            title = title_text.split('|')[0].strip()
        else:
            title = "Untitled"

    # Track section path and current buffer
    section_path = []
    current_buffer = []
    current_buffer_links = []
    chunks = []
    all_text_parts = []
    seen_texts = set()
    drop_until_heading = None

    # Track elements for worked example detection
    all_elements = list(root.select('h1, h2, h3, p, li, table, div.cmp-accordion__item'))
    processed_elements = set()

    def flush_buffer():
        """Flush current buffer to chunks."""
        nonlocal current_buffer, current_buffer_links
        if not current_buffer:
            return

        # Join and normalize
        text = "\n".join(current_buffer)
        text = normalize_text(text)

        # Check for duplicates
        if text in seen_texts:
            current_buffer = []
            current_buffer_links = []
            return
        seen_texts.add(text)

        # Pack lines
        lines = text.split('\n')
        packed = pack_lines(lines)

        # Create chunks
        for piece in packed:
            chunk = ChunkDraft(
                kind=ChunkKind.section,
                section_path=section_path.copy(),
                text=piece,
                links=current_buffer_links.copy()
            )
            chunks.append(chunk)

        current_buffer = []
        current_buffer_links = []

    def extract_inline_links(elem: Tag) -> list[ExtractedLink]:
        """Extract inline links from an element."""
        links = []
        for a in elem.select('a[href]'):
            href = a.get('href', '')
            absolute_url = absolutize(href, page_url)
            if absolute_url:
                anchor_text = a.get_text(strip=True)
                links.append(ExtractedLink(
                    target_url=absolute_url,
                    anchor_text=anchor_text,
                    link_kind=LinkKind.inline
                ))
        return links

    def get_heading_level(tag_name: str) -> int:
        """Get numeric heading level."""
        if tag_name == 'h1':
            return 1
        elif tag_name == 'h2':
            return 2
        elif tag_name == 'h3':
            return 3
        return 0

    def should_drop_heading(text: str) -> bool:
        """Check if heading text should be dropped."""
        for pattern in cfg.drop_headings:
            if pattern in text:
                return True
        return False

    # First pass: mark worked examples
    i = 0
    while i < len(all_elements):
        elem = all_elements[i]
        if elem.name == 'p':
            text = elem.get_text(strip=True)
            if text.startswith("Exemplu de calcul"):
                # Mark this as start of worked example
                processed_elements.add(elem)

                # Collect example paragraphs
                example_parts = [text]
                example_links = extract_inline_links(elem)

                # Look ahead for "Pentru un credit" paragraphs
                j = i + 1
                while j < len(all_elements):
                    next_elem = all_elements[j]
                    if next_elem.name == 'p':
                        next_text = next_elem.get_text(strip=True)
                        if next_text.startswith("Pentru un credit"):
                            example_parts.append(next_text)
                            example_links.extend(extract_inline_links(next_elem))
                            processed_elements.add(next_elem)
                            j += 1
                        else:
                            # Non-example paragraph, stop
                            break
                    elif next_elem.name in ('h1', 'h2', 'h3'):
                        # Heading, stop
                        break
                    elif next_elem.name == 'p' and next_elem.get_text(strip=True).startswith("Exemplu de calcul"):
                        # Another example, stop
                        break
                    else:
                        j += 1

                # Create worked example chunk
                example_text = "\n".join(example_parts)
                example_text = normalize_text(example_text)

                chunks.append(ChunkDraft(
                    kind=ChunkKind.worked_example,
                    section_path=section_path.copy(),
                    text=example_text,
                    links=example_links
                ))
                all_text_parts.append(example_text)
        i += 1

    # Second pass: process remaining elements
    pending_h3s = []  # Track h3s with no content

    for i, elem in enumerate(all_elements):
        # Skip if already processed
        if elem in processed_elements:
            continue

        # Skip if inside accordion (handled separately)
        if elem.name != 'div' and elem.find_parent('div', class_='cmp-accordion__item'):
            continue

        # Skip nested p/li
        if elem.name in ('p', 'li'):
            if elem.find_parent(['li', 'table']):
                continue

        # Handle accordion items
        if elem.name == 'div' and 'cmp-accordion__item' in elem.get('class', []):
            # Flush any pending h3s
            if pending_h3s:
                for h3_text in pending_h3s:
                    current_buffer.append(f"- {h3_text}")
                pending_h3s = []

            flush_buffer()
            # Get group heading (last h2 or h3 before this accordion)
            group_heading = section_path[0] if section_path else ""
            chunk = accordion_chunk(elem, [title, group_heading], page_url)
            chunks.append(chunk)
            continue

        # Handle headings
        if elem.name in ('h1', 'h2', 'h3'):
            heading_text = elem.get_text(strip=True)
            heading_level = get_heading_level(elem.name)

            # Check if we should drop this section
            if should_drop_heading(heading_text):
                # Flush any pending h3s first
                if pending_h3s:
                    for h3_text in pending_h3s:
                        current_buffer.append(f"- {h3_text}")
                    pending_h3s = []

                flush_buffer()
                drop_until_heading = heading_level
                section_path = []
                continue

            # If we were dropping, check if this heading ends it
            if drop_until_heading is not None:
                if heading_level <= drop_until_heading:
                    drop_until_heading = None
                else:
                    continue  # Still in dropped section

            # Check if h3 with no content (next element is heading)
            if heading_level == 3:
                # Look ahead to see if next non-processed element is a heading
                has_content = False
                for j in range(i + 1, len(all_elements)):
                    next_elem = all_elements[j]
                    if next_elem in processed_elements:
                        continue
                    if next_elem.name in ('h1', 'h2', 'h3'):
                        # Next heading found, no content
                        break
                    if next_elem.name in ('p', 'li', 'table') or (next_elem.name == 'div' and 'cmp-accordion__item' in next_elem.get('class', [])):
                        # Content found
                        has_content = True
                        break

                if not has_content:
                    # This h3 has no content, track it
                    pending_h3s.append(heading_text)
                    all_text_parts.append(heading_text)
                    continue

            # Flush any pending h3s before updating section path
            if pending_h3s:
                for h3_text in pending_h3s:
                    current_buffer.append(f"- {h3_text}")
                pending_h3s = []

            # Update section path
            flush_buffer()

            if heading_level == 2:
                section_path = [heading_text]
            elif heading_level == 3:
                if len(section_path) == 0:
                    section_path = [heading_text]
                else:
                    section_path = [section_path[0], heading_text]

            all_text_parts.append(heading_text)
            continue

        # Skip content in dropped sections
        if drop_until_heading is not None:
            continue

        # Flush any pending h3s before adding content
        if pending_h3s:
            for h3_text in pending_h3s:
                current_buffer.append(f"- {h3_text}")
            pending_h3s = []

        # Handle p, li, table
        if elem.name == 'p':
            text = elem.get_text(strip=True)
            if text:
                # Fix whitespace before punctuation (but not inside numbers)
                # Only remove space before standalone punctuation
                text = re.sub(r" ([.,;:!?])(?!\d)", r"\1", text)
                current_buffer.append(text)
                all_text_parts.append(text)

                # Extract and store links
                links = extract_inline_links(elem)
                current_buffer_links.extend(links)

        elif elem.name == 'li':
            text = elem.get_text(strip=True)
            if text:
                text = "- " + text
                text = re.sub(r" ([.,;:!?])(?!\d)", r"\1", text)
                current_buffer.append(text)
                all_text_parts.append(text)

                # Extract and store links
                links = extract_inline_links(elem)
                current_buffer_links.extend(links)

        elif elem.name == 'table':
            # Convert table to | -joined rows
            rows = []
            for row in elem.select('tr'):
                cells = [cell.get_text(strip=True) for cell in row.select('td, th')]
                if cells:
                    row_text = " | ".join(cells)
                    rows.append(row_text)
            if rows:
                table_text = "\n".join(rows)
                current_buffer.append(table_text)
                all_text_parts.append(table_text)

    # Flush any remaining pending h3s
    if pending_h3s:
        for h3_text in pending_h3s:
            current_buffer.append(f"- {h3_text}")

    # Flush remaining buffer
    flush_buffer()

    # Filter chunk links
    filter_chunk_links(chunks, page_url, cfg)

    # Build metadata text
    metadata_text = "\n".join(all_text_parts)
    metadata_text = normalize_text(metadata_text)

    return ParsedDocument(
        title=title,
        chunks=chunks,
        metadata_text=metadata_text,
        parser_name="html_page"
    )
