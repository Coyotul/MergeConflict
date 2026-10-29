"""Metadata extraction: canonical keys, effective dates, campaign windows."""
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlparse

from src.models.knowledge import DocKind

EffectiveDateSource = Literal["document_text", "filename", "sitemap_lastmod", "fetched_at"]

# Romanian month names with and without diacritics
ROMANIAN_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
    # Variants without diacritics
    "ianuarie": 1, "febrvarie": 2,
}


def canonical_key(url: str, shared_folders: frozenset[str] = frozenset()) -> str:
    """Compute canonical key from URL.

    Rules (in order):
    1. Dated file (8 digits + '-' prefix):
       - If parent folder NOT in shared_folders: key = parent folder path
       - If parent folder IS in shared_folders: key = parent folder path + '/' + stem
    2. Ends with '.sv.pdf': strip it
    3. Otherwise: strip '.coredownload.pdf' / '.coredownload.inline.pdf' and '.pdf'
    4. HTML: keep path as-is

    Returns lowercased path with no host or query.
    """
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Check if it's a dated file (starts with 8 digits and -)
    filename = path.split("/")[-1]
    is_dated = bool(re.match(r'^\d{8}-', filename))

    if is_dated:
        # Get parent folder path
        parent = "/".join(path.split("/")[:-1])

        if parent in shared_folders:
            # Shared folder: include stem (filename without date prefix and PDF suffix)
            stem = re.sub(r'^\d{8}-', '', filename)
            # Remove .pdf.coredownload.inline.pdf, .pdf.coredownload.pdf, or .pdf
            stem = re.sub(r'\.pdf\.coredownload\.inline\.pdf$', '', stem)
            stem = re.sub(r'\.pdf\.coredownload\.pdf$', '', stem)
            stem = re.sub(r'\.pdf$', '', stem)
            return f"{parent}/{stem}"
        else:
            # Not shared: use parent folder path
            return parent

    # Rule 2: .sv.pdf
    if path.endswith('.sv.pdf'):
        return path[:-len('.sv.pdf')]

    # Rule 3: .coredownload variants and .pdf
    path = re.sub(r'\.coredownload\.inline\.pdf$', '', path)
    path = re.sub(r'\.coredownload\.pdf$', '', path)
    path = re.sub(r'\.pdf$', '', path)

    # Rule 4: HTML keeps path as-is (already processed above if PDF)
    return path


def alternate_canonical_key(url: str, shared_folders: frozenset[str]) -> str | None:
    """For a dated file, its key under the opposite sharing decision for its folder; None otherwise.

    A folder's shared status depends on the manifest (a second stem appearing or disappearing),
    so a document stored under this key may be the same document as `canonical_key(url, shared_folders)`.
    """
    path = urlparse(url).path.lower()
    if not re.match(r'^\d{8}-', path.split("/")[-1]):
        return None
    parent = "/".join(path.split("/")[:-1])
    return canonical_key(url, shared_folders ^ {parent})


def shared_dated_folders(urls: list[str] | frozenset[str]) -> frozenset[str]:
    """Find folders containing two or more distinct dated file stems.

    Groups dated files by parent folder, returns folders with 2+ distinct stems.
    Multiple dates of the same stem don't make a folder shared.
    """
    folders: dict[str, set[str]] = defaultdict(set)

    for url in urls:
        parsed = urlparse(url)
        path = parsed.path.lower()
        filename = path.split("/")[-1]

        # Check if dated
        if re.match(r'^\d{8}-', filename):
            parent = "/".join(path.split("/")[:-1])
            # Extract stem (without date prefix and PDF suffix)
            stem = re.sub(r'^\d{8}-', '', filename)
            stem = re.sub(r'\.pdf\.coredownload\.inline\.pdf$', '', stem)
            stem = re.sub(r'\.pdf\.coredownload\.pdf$', '', stem)
            stem = re.sub(r'\.pdf$', '', stem)
            folders[parent].add(stem)

    # Return folders with 2+ distinct stems
    return frozenset(parent for parent, stems in folders.items() if len(stems) >= 2)


def extract_effective_date(
    doc_kind: DocKind,
    text: str,
    url: str,
    sitemap_lastmod: date | None,
    fetched_at: datetime
) -> tuple[date, EffectiveDateSource]:
    """Extract effective date with precedence: document_text > filename > sitemap_lastmod > fetched_at.

    For PDF doc_kinds (fee_list, general_terms, cost_sheet, pdf_generic), searches first 600 chars for:
    - Ediția/Editia DD.MM.YYYY
    - <day> <Romanian month name> <YYYY>
    - A line that is exactly DD.MM.YYYY

    Filename: YYYYMMDD prefix, rejected if invalid calendar date.
    """
    # Try document text for PDF kinds
    pdf_kinds = {DocKind.fee_list, DocKind.general_terms, DocKind.cost_sheet, DocKind.pdf_generic}
    if doc_kind in pdf_kinds:
        search_text = text[:600]

        # Pattern 1: Ediția/Editia DD.MM.YYYY
        match = re.search(r'Edi[țt]ia\s+(\d{1,2})\.(\d{1,2})\.(\d{4})', search_text, re.IGNORECASE)
        if match:
            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            try:
                return (date(year, month, day), "document_text")
            except ValueError:
                pass

        # Pattern 2: <day> <Romanian month name> <YYYY>
        for month_name, month_num in ROMANIAN_MONTHS.items():
            pattern = rf'(\d{{1,2}})\s+{re.escape(month_name)}\s+(\d{{4}})'
            match = re.search(pattern, search_text, re.IGNORECASE)
            if match:
                day, year = int(match.group(1)), int(match.group(2))
                try:
                    return (date(year, month_num, day), "document_text")
                except ValueError:
                    pass

        # Pattern 3: line that is exactly DD.MM.YYYY
        for line in search_text.split('\n'):
            line = line.strip()
            match = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', line)
            if match:
                day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                try:
                    return (date(year, month, day), "document_text")
                except ValueError:
                    pass

    # Try filename (8-digit YYYYMMDD prefix)
    filename = urlparse(url).path.split("/")[-1]
    match = re.match(r'^(\d{8})-', filename)
    if match:
        date_str = match.group(1)
        try:
            year = int(date_str[0:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])
            return (date(year, month, day), "filename")
        except ValueError:
            pass  # Invalid date, fall through

    # Try sitemap_lastmod
    if sitemap_lastmod is not None:
        return (sitemap_lastmod, "sitemap_lastmod")

    # Fall back to fetched_at
    return (fetched_at.date(), "fetched_at")


def extract_campaign_window(text: str, reference: date) -> date | None:
    """Extract campaign end date from text.

    Recognises:
    - Perioada campaniei: DD.MM[.YYYY] - DD.MM.YYYY
    - campania (este valabilă|se desfășoară): DD.MM - DD.MM

    Returns the latest end date found. If year missing, uses reference.year.
    """
    # Pattern for campaign phrases
    patterns = [
        r'Perioada campaniei[:\s]+(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\s*-\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?',
        r'campania\s+(?:este\s+valabil[ăa]|se\s+desf[ăa][șs]oar[ăa])(?:\s+[îi]n\s+perioada)?[:\s]+(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\s*-\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?',
    ]

    latest_end: date | None = None

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            # Extract end date (groups 4, 5, 6)
            end_day = int(match.group(4))
            end_month = int(match.group(5))
            end_year_str = match.group(6)
            end_year = int(end_year_str) if end_year_str else reference.year

            try:
                end_date = date(end_year, end_month, end_day)
                if latest_end is None or end_date > latest_end:
                    latest_end = end_date
            except ValueError:
                pass

    return latest_end
