"""Link extraction and filtering utilities."""
from urllib.parse import urljoin, urlparse

from src.services.document_ingestion.chunking import ChunkDraft
from src.services.document_ingestion.sources import SourceConfig, is_allowed_url
from src.services.document_ingestion.metadata import canonical_key


def absolutize(href: str, page_url: str) -> str | None:
    """Convert relative href to absolute URL.

    Joins href with page_url, strips query and fragment, returns None for
    mailto:, tel:, javascript:, empty and fragment-only hrefs.

    A raiffeisen.ro host with or without www, over http or https, normalizes
    to https://www.raiffeisen.ro.
    """
    # Handle empty or junk hrefs
    if not href or href.startswith('#'):
        return None

    # Handle javascript:, tel:, mailto:
    if href.startswith(('javascript:', 'tel:', 'mailto:')):
        return None

    # Join with page URL
    absolute = urljoin(page_url, href)

    # Parse and strip query and fragment
    parsed = urlparse(absolute)

    # Normalize raiffeisen.ro host
    if parsed.netloc in ('raiffeisen.ro', 'www.raiffeisen.ro'):
        normalized_host = 'www.raiffeisen.ro'
        scheme = 'https'
    else:
        normalized_host = parsed.netloc
        scheme = parsed.scheme

    # Build clean URL
    clean_url = f"{scheme}://{normalized_host}{parsed.path}"

    return clean_url


def filter_chunk_links(
    chunks: list[ChunkDraft],
    page_url: str,
    cfg: SourceConfig,
    chip_targets: frozenset[str] = frozenset()
) -> None:
    """Filter chunk links in place.

    Mutates each chunk's links list, keeping only links that pass all of:
    - is_allowed_url
    - target not a self-link (canonical_key(target) == canonical_key(page_url))
    - target not in chip_targets
    - first occurrence of that canonical_key within the chunk
    """
    page_key = canonical_key(page_url)

    for chunk in chunks:
        seen_keys = set()
        filtered = []

        for link in chunk.links:
            target_key = canonical_key(link.target_url)

            # Check all filter conditions
            if not is_allowed_url(link.target_url, cfg):
                continue

            if target_key == page_key:
                continue

            if link.target_url in chip_targets:
                continue

            if target_key in seen_keys:
                continue

            # Passed all filters
            seen_keys.add(target_key)
            filtered.append(link)

        chunk.links = filtered
