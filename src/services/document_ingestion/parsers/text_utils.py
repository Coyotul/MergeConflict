"""Text extraction utilities for parsers."""
import re
from bs4 import Tag


def extract_text(elem: Tag) -> str:
    """Extract and clean text from a BeautifulSoup element.

    Uses space separator to avoid gluing words at tag boundaries,
    then collapses whitespace and fixes punctuation spacing.
    """
    text = elem.get_text(" ", strip=True)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    # Remove space before punctuation
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text
