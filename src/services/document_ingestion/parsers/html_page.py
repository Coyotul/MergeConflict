"""HTML page parser for product pages, guides, FAQs, and articles."""
from bs4 import BeautifulSoup, Tag
from dataclasses import dataclass, field

from src.services.document_ingestion.chunking import (
    ChunkDraft,
    ParsedDocument,
    ExtractedLink,
    CHUNKER_VERSION,
    pack_lines,
    estimate_tokens,
    MAX_TOKENS,
)
from src.services.document_ingestion.parsers.links import absolutize, filter_chunk_links
from src.services.document_ingestion.parsers.text_utils import extract_text
from src.services.document_ingestion.sources import SourceConfig
from src.services.document_ingestion.normalize import normalize_text
from src.models.knowledge import ChunkKind, LinkKind


@dataclass
class BufferedLine:
    """A line of text with associated links."""
    text: str
    links: list[ExtractedLink] = field(default_factory=list)


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
    question = extract_text(title_elem) if title_elem else ""

    # Extract answer from panel
    panel = item.select_one('.cmp-accordion__panel')
    answer_parts = []
    links = []

    if panel:
        for elem in panel.select('p, li'):
            text = extract_text(elem)
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
                    anchor_text = extract_text(a)
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
        title = extract_text(h1)
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
    current_buffer = []  # list of BufferedLine
    chunks = []
    all_text_parts = []
    seen_block_texts = set()  # For dedupe across whole page
    drop_until_heading = None

    # Get all elements for walking
    all_elements = list(root.select('h1, h2, h3, p, li, table, div.cmp-accordion__item'))

    def flush_buffer():
        """Flush current buffer to chunks."""
        nonlocal current_buffer
        if not current_buffer:
            return

        # Normalize each line text first
        for line in current_buffer:
            line.text = normalize_text(line.text)

        # Pack lines and split links accordingly
        line_texts = [line.text for line in current_buffer]
        packed = pack_lines(line_texts)

        # Attach links to the correct piece
        for piece in packed:
            piece_lines = piece.split('\n')
            piece_links = []

            # Find which original lines are in this piece
            for line in current_buffer:
                if line.text in piece_lines:
                    piece_links.extend(line.links)

            chunk = ChunkDraft(
                kind=ChunkKind.section,
                section_path=section_path.copy(),
                text=piece,
                links=piece_links
            )
            chunks.append(chunk)

        current_buffer = []

    def extract_inline_links(elem: Tag) -> list[ExtractedLink]:
        """Extract inline links from an element."""
        links = []
        for a in elem.select('a[href]'):
            href = a.get('href', '')
            absolute_url = absolutize(href, page_url)
            if absolute_url:
                anchor_text = extract_text(a)
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

    def find_nearest_group_heading(start_elem: Tag) -> str:
        """Find nearest preceding h2 or h3 for group heading."""
        # Look for h2 or h3 in reverse document order
        prev = start_elem.find_previous(['h2', 'h3'])
        if prev:
            return extract_text(prev)
        # Fall back to h1 if no h2/h3
        h1 = root.find('h1')
        if h1:
            return extract_text(h1)
        return ""

    # Track pending h3s (heading-only content)
    pending_h3s = []

    # Main walk
    i = 0
    while i < len(all_elements):
        elem = all_elements[i]

        # Skip if inside accordion (handled separately)
        if elem.name != 'div' and elem.find_parent('div', class_='cmp-accordion__item'):
            i += 1
            continue

        # Skip nested p/li
        if elem.name in ('p', 'li'):
            if elem.find_parent(['li', 'table']):
                i += 1
                continue

        # Handle accordion items
        if elem.name == 'div' and 'cmp-accordion__item' in elem.get('class', []):
            # Skip if in dropped section
            if drop_until_heading is not None:
                i += 1
                continue

            # Flush any pending h3s
            if pending_h3s:
                for h3_text in pending_h3s:
                    current_buffer.append(BufferedLine(text=f"- {h3_text}"))
                pending_h3s = []

            flush_buffer()
            # Get group heading (nearest h2 or h3)
            group_heading = find_nearest_group_heading(elem)
            chunk = accordion_chunk(elem, [title, group_heading], page_url)
            # Ensure no empty parts in section_path
            chunk.section_path = [p for p in chunk.section_path if p]
            chunks.append(chunk)
            all_text_parts.append(chunk.text)
            i += 1
            continue

        # Handle headings
        if elem.name in ('h1', 'h2', 'h3'):
            heading_text = extract_text(elem)
            heading_level = get_heading_level(elem.name)

            # Check if we should drop this section
            if should_drop_heading(heading_text):
                # Flush any pending h3s first
                if pending_h3s:
                    for h3_text in pending_h3s:
                        current_buffer.append(BufferedLine(text=f"- {h3_text}"))
                    pending_h3s = []

                flush_buffer()
                drop_until_heading = heading_level
                section_path = []
                i += 1
                continue

            # If we were dropping, check if this heading ends it
            if drop_until_heading is not None:
                if heading_level <= drop_until_heading:
                    drop_until_heading = None
                else:
                    i += 1
                    continue  # Still in dropped section

            # Check if h3 with no content (next element is heading)
            if heading_level == 3:
                # Look ahead to see if next element is a heading
                has_content = False
                for j in range(i + 1, len(all_elements)):
                    next_elem = all_elements[j]
                    # Skip nested elements
                    if next_elem.name in ('p', 'li') and next_elem.find_parent(['li', 'table']):
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
                    i += 1
                    continue

            # Flush any pending h3s before updating section path
            if pending_h3s:
                for h3_text in pending_h3s:
                    current_buffer.append(BufferedLine(text=f"- {h3_text}"))
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
            i += 1
            continue

        # Skip content in dropped sections
        if drop_until_heading is not None:
            i += 1
            continue

        # Check for worked example (in main walk, not separate pass)
        if elem.name == 'p':
            text = extract_text(elem)

            if text.startswith("Exemplu de calcul"):
                # Check for duplicate BEFORE processing as worked example
                if text in seen_block_texts:
                    i += 1
                    continue
                seen_block_texts.add(text)
                # Flush any pending h3s
                if pending_h3s:
                    for h3_text in pending_h3s:
                        current_buffer.append(BufferedLine(text=f"- {h3_text}"))
                    pending_h3s = []

                # Flush current buffer
                flush_buffer()

                # Collect example paragraphs
                example_parts = [text]
                example_links = extract_inline_links(elem)

                # Look ahead for "Pentru un credit" paragraphs
                j = i + 1
                while j < len(all_elements):
                    next_elem = all_elements[j]
                    if next_elem.name == 'p':
                        next_text = extract_text(next_elem)

                        # Check for duplicate
                        if next_text in seen_block_texts:
                            j += 1
                            continue

                        if next_text.startswith("Pentru un credit"):
                            example_parts.append(next_text)
                            example_links.extend(extract_inline_links(next_elem))
                            seen_block_texts.add(next_text)
                            j += 1
                        else:
                            # Non-example paragraph, stop
                            break
                    elif next_elem.name in ('h1', 'h2', 'h3'):
                        # Heading, stop
                        break
                    else:
                        j += 1

                # Create worked example chunk with proper section_path
                example_text = "\n".join(example_parts)
                example_text = normalize_text(example_text)

                # Build section path: [title, current h2, first 80 chars of example]
                example_section_path = [title]
                if section_path:
                    example_section_path.extend(section_path)
                # Add first 80 chars of title as identifier
                example_title = text[:80] if len(text) > 80 else text
                example_section_path.append(example_title)

                chunks.append(ChunkDraft(
                    kind=ChunkKind.worked_example,
                    section_path=example_section_path,
                    text=example_text,
                    links=example_links
                ))
                all_text_parts.append(example_text)
                i += 1
                continue

        # Flush any pending h3s before adding content
        if pending_h3s:
            for h3_text in pending_h3s:
                current_buffer.append(BufferedLine(text=f"- {h3_text}"))
            pending_h3s = []

        # Handle p, li, table
        if elem.name == 'p':
            text = extract_text(elem)
            if text:
                # Check for duplicate
                if text in seen_block_texts:
                    i += 1
                    continue
                seen_block_texts.add(text)

                links = extract_inline_links(elem)
                current_buffer.append(BufferedLine(text=text, links=links))
                all_text_parts.append(text)

        elif elem.name == 'li':
            text = extract_text(elem)
            if text:
                text = "- " + text

                # Check for duplicate
                if text in seen_block_texts:
                    i += 1
                    continue
                seen_block_texts.add(text)

                links = extract_inline_links(elem)
                current_buffer.append(BufferedLine(text=text, links=links))
                all_text_parts.append(text)

        elif elem.name == 'table':
            # Convert table to | -joined rows and extract links from cells
            rows = []
            table_links = []
            for row in elem.select('tr'):
                cells = [extract_text(cell) for cell in row.select('td, th')]
                if cells:
                    row_text = " | ".join(cells)
                    rows.append(row_text)
                # Extract links from all cells in this row
                for cell in row.select('td, th'):
                    table_links.extend(extract_inline_links(cell))
            if rows:
                table_text = "\n".join(rows)

                # Check for duplicate
                if table_text in seen_block_texts:
                    i += 1
                    continue
                seen_block_texts.add(table_text)

                current_buffer.append(BufferedLine(text=table_text, links=table_links))
                all_text_parts.append(table_text)

        i += 1

    # Flush any remaining pending h3s
    if pending_h3s:
        for h3_text in pending_h3s:
            current_buffer.append(BufferedLine(text=f"- {h3_text}"))

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
