"""Polite incremental web scraper with withdrawal detection."""
import re
import time
from datetime import datetime, date
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from src.services.document_ingestion.sources import SourceConfig
from src.services.document_ingestion.manifest import ManifestEntry
from src.storage.document_store.raw_store import save_raw
from src.services.document_ingestion.parsers.links import absolutize


USER_AGENT = "MergeConflict-RAG-Prototype/0.1 (local hackathon research)"


class ScrapeReport(BaseModel):
    """Report of a scrape run."""
    entries: list[ManifestEntry]
    new: list[str]
    changed: list[str]
    unchanged: list[str]
    failed: dict[str, str]
    withdrawn: list[str]
    completed: bool


def _make_entry(
    url: str,
    final_url: str,
    status_code: int | None,
    content_type: str | None,
    sitemap_lastmod: date | None,
    sha256: str | None,
    raw_path: str | None,
    error: str | None,
    index: bool,
    withdrawn: bool = False,
) -> ManifestEntry:
    """Helper to build ManifestEntry with common fields."""
    return ManifestEntry(
        url=url,
        final_url=final_url,
        fetched_at=datetime.now(),
        status_code=status_code,
        content_type=content_type,
        sitemap_lastmod=sitemap_lastmod,
        sha256=sha256,
        raw_path=raw_path,
        error=error,
        index=index,
        withdrawn=withdrawn,
    )


class Scraper:
    """Polite incremental scraper with robots.txt and withdrawal detection."""

    def __init__(
        self,
        client: httpx.Client,
        cfg: SourceConfig,
        raw_dir: Path,
        min_interval_s: float = 2.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ):
        self.client = client
        self.cfg = cfg
        self.raw_dir = raw_dir
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self.sleep = sleep
        self.now = now
        self.last_request_time: float | None = None
        self.sitemap_lastmod_by_url: dict[str, date] = {}

    def run(self, previous: list[ManifestEntry]) -> ScrapeReport:
        """Run a scrape, discovering URLs and checking for withdrawals."""
        # Build previous lookup
        previous_by_url = {e.url: e for e in previous}

        # Fetch and parse robots.txt
        robots, robots_error = self._fetch_robots()
        failed: dict[str, str] = {}

        if robots_error:
            failed[urljoin(self.cfg.sitemap_url, "/robots.txt")] = robots_error
            # Critical failure - don't proceed
            return ScrapeReport(
                entries=list(previous),
                new=[],
                changed=[],
                unchanged=[],
                failed=failed,
                withdrawn=[],
                completed=False,
            )

        # Discover initial URLs
        discovered_urls, sitemap_error = self._discover_urls(robots)

        if sitemap_error:
            failed[self.cfg.sitemap_url] = sitemap_error
            # Carry over previous entries, no withdrawals
            return ScrapeReport(
                entries=list(previous),
                new=[],
                changed=[],
                unchanged=[],
                failed=failed,
                withdrawn=[],
                completed=False,
            )

        # Fetch all discovered URLs, extracting PDF links as we go
        entries_by_url: dict[str, ManifestEntry] = {}
        attempted = 0
        fetched_urls = set()
        urls_to_fetch = list(discovered_urls)

        while urls_to_fetch:
            url = urls_to_fetch.pop(0)
            if url in fetched_urls:
                continue

            fetched_urls.add(url)
            attempted += 1
            is_seed = url in self.cfg.discovery_seeds
            entry = self._fetch_url(url, robots, previous_by_url.get(url), is_seed)
            if entry.error:
                failed[url] = entry.error
            entries_by_url[url] = entry

            # Extract PDF links from successful HTML fetches
            if entry.status_code == 200 and entry.raw_path and ".html" in entry.raw_path:
                raw_path = self.raw_dir.parent / entry.raw_path
                html_content = raw_path.read_bytes()
                pdf_links = self._extract_pdf_links(html_content, url, robots)
                for pdf_url in pdf_links:
                    if pdf_url not in fetched_urls and pdf_url not in urls_to_fetch:
                        urls_to_fetch.append(pdf_url)

        # Calculate completion status (before checking withdrawals)
        failure_rate = len(failed) / max(1, attempted)
        completed = failure_rate < 0.10

        # Check for withdrawals only if run is completing successfully
        withdrawn_urls: list[str] = []
        if completed:
            for prev_entry in previous:
                if prev_entry.index and prev_entry.url not in fetched_urls and not prev_entry.withdrawn:
                    # Skip robots-disallowed withdrawals
                    if not robots.can_fetch(USER_AGENT, prev_entry.url):
                        entries_by_url[prev_entry.url] = prev_entry
                        continue

                    # Check if it's truly withdrawn
                    attempted += 1
                    check_entry = self._fetch_url(prev_entry.url, robots, prev_entry, is_seed=False)
                    if check_entry.status_code in (404, 410):
                        withdrawn_urls.append(prev_entry.url)
                    elif check_entry.error:
                        failed[prev_entry.url] = check_entry.error
                        # Carry over previous entry
                        entries_by_url[prev_entry.url] = prev_entry
                    else:
                        # Still exists, carry over
                        entries_by_url[prev_entry.url] = check_entry

            # Recalculate completion status after withdrawal checks
            failure_rate = len(failed) / max(1, attempted)
            completed = failure_rate < 0.10

        # Apply withdrawals only if completed
        if completed:
            for url in withdrawn_urls:
                withdrawn_entry = previous_by_url[url].model_copy()
                withdrawn_entry.withdrawn = True
                entries_by_url[url] = withdrawn_entry
        else:
            # Carry over all previous entries not in discovered
            for prev_entry in previous:
                if prev_entry.url not in entries_by_url:
                    entries_by_url[prev_entry.url] = prev_entry
            withdrawn_urls = []

        # Classify entries
        new: list[str] = []
        changed: list[str] = []
        unchanged: list[str] = []

        for url, entry in entries_by_url.items():
            if entry.withdrawn:
                continue
            if entry.error:
                continue
            if entry.status_code not in (200, 304):
                continue

            prev = previous_by_url.get(url)
            if not prev:
                new.append(url)
            elif entry.sha256 != prev.sha256:
                changed.append(url)
            else:
                unchanged.append(url)

        return ScrapeReport(
            entries=list(entries_by_url.values()),
            new=new,
            changed=changed,
            unchanged=unchanged,
            failed=failed,
            withdrawn=withdrawn_urls if completed else [],
            completed=completed,
        )

    def _fetch_robots(self) -> tuple[RobotFileParser, str | None]:
        """Fetch and parse robots.txt, returning (parser, error)."""
        robots = RobotFileParser()
        robots_url = urljoin(self.cfg.sitemap_url, "/robots.txt")

        for attempt in range(self.max_retries + 1):
            self._wait_for_rate_limit()
            try:
                response = self.client.get(robots_url, follow_redirects=True)
                if response.status_code == 200:
                    robots.parse(response.text.splitlines())
                    return robots, None
                elif response.status_code in (404, 410):
                    # No robots.txt means allow everything
                    robots.parse([])
                    return robots, None
                elif response.status_code >= 500:
                    if attempt < self.max_retries:
                        self.sleep(2 ** (attempt + 1))
                        continue
                    return robots, f"Server error: {response.status_code}"
                else:
                    return robots, f"Unexpected status: {response.status_code}"
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt < self.max_retries:
                    self.sleep(2 ** (attempt + 1))
                    continue
                return robots, f"Network error: {type(e).__name__}"

        return robots, "Max retries exceeded"

    def _discover_urls(self, robots: RobotFileParser) -> tuple[set[str], str | None]:
        """Discover URLs from sitemap, extra_urls, and discovery_seeds, returning (urls, error)."""
        urls = set()

        # Parse sitemap
        self._wait_for_rate_limit()
        try:
            response = self.client.get(self.cfg.sitemap_url, follow_redirects=True)
            if response.status_code == 200:
                urls.update(self._parse_sitemap(response.content, robots))
            else:
                return set(), f"Sitemap fetch failed: {response.status_code}"
        except (httpx.TimeoutException, httpx.TransportError) as e:
            return set(), f"Sitemap network error: {type(e).__name__}"
        except ET.ParseError as e:
            return set(), f"Sitemap is not valid XML: {e}"

        # Add extra_urls (not filtered by allowlist; robots check in _fetch_url)
        for url in self.cfg.extra_urls:
            urls.add(url)

        # Add discovery_seeds (not filtered by allowlist; robots check in _fetch_url)
        for url in self.cfg.discovery_seeds:
            urls.add(url)

        return urls, None

    def _parse_sitemap(self, content: bytes, robots: RobotFileParser) -> set[str]:
        """Parse sitemap XML and return allowed URLs, storing lastmod dates."""
        from src.services.document_ingestion.sources import is_allowed_url

        urls = set()
        # The live sitemap carries stray non-UTF-8 bytes in image captions; replace them rather than fail.
        root = ET.fromstring(content.decode("utf-8", errors="replace"))
        # Handle namespace
        ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        for url_elem in root.findall('.//sm:url', ns):
            loc_elem = url_elem.find('sm:loc', ns)
            if loc_elem is not None and loc_elem.text:
                url = loc_elem.text.strip()
                if robots.can_fetch(USER_AGENT, url) and is_allowed_url(url, self.cfg):
                    urls.add(url)

                    # Parse lastmod if present
                    lastmod_elem = url_elem.find('sm:lastmod', ns)
                    if lastmod_elem is not None and lastmod_elem.text:
                        lastmod_date = self._parse_date(lastmod_elem.text.strip())
                        if lastmod_date:
                            self.sitemap_lastmod_by_url[url] = lastmod_date
        return urls

    def _parse_date(self, date_str: str) -> date | None:
        """Parse ISO date or datetime string, returning date part or None."""
        try:
            # Handle dates like "2026-10-15" or "2026-10-15T10:30:00Z"
            # Extract just the date part (YYYY-MM-DD)
            date_part = date_str.split('T')[0]
            parts = date_part.split('-')
            if len(parts) == 3:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                return date(year, month, day)
        except (ValueError, IndexError):
            pass
        return None

    def _fetch_url(
        self,
        url: str,
        robots: RobotFileParser,
        previous_entry: ManifestEntry | None,
        is_seed: bool,
    ) -> ManifestEntry:
        """Fetch a URL with retries, returning a ManifestEntry."""
        index = not is_seed
        lastmod = self.sitemap_lastmod_by_url.get(url)

        if not robots.can_fetch(USER_AGENT, url):
            return _make_entry(
                url=url,
                final_url=url,
                status_code=None,
                content_type=None,
                sitemap_lastmod=lastmod,
                sha256=None,
                raw_path=None,
                error="Disallowed by robots.txt",
                index=index,
            )

        for attempt in range(self.max_retries + 1):
            self._wait_for_rate_limit()

            try:
                response = self.client.get(url, follow_redirects=True)

                # Handle 404/410 without retry
                if response.status_code in (404, 410):
                    return _make_entry(
                        url=url,
                        final_url=str(response.url),
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        sitemap_lastmod=lastmod,
                        sha256=None,
                        raw_path=None,
                        error=None,
                        index=index,
                    )

                # Handle success
                if response.status_code == 200:
                    return self._process_success(url, response, previous_entry, index, lastmod)

                # Handle 5xx - retry
                if response.status_code >= 500:
                    if attempt < self.max_retries:
                        self.sleep(2 ** (attempt + 1))
                        continue
                    else:
                        return _make_entry(
                            url=url,
                            final_url=str(response.url),
                            status_code=response.status_code,
                            content_type=response.headers.get("content-type"),
                            sitemap_lastmod=lastmod,
                            sha256=None,
                            raw_path=None,
                            error=f"Server error: {response.status_code}",
                            index=index,
                        )

                # Other status codes
                return _make_entry(
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    content_type=response.headers.get("content-type"),
                    sitemap_lastmod=lastmod,
                    sha256=None,
                    raw_path=None,
                    error=f"Unexpected status: {response.status_code}",
                    index=index,
                )

            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt < self.max_retries:
                    self.sleep(2 ** (attempt + 1))
                    continue
                else:
                    return _make_entry(
                        url=url,
                        final_url=url,
                        status_code=None,
                        content_type=None,
                        sitemap_lastmod=lastmod,
                        sha256=None,
                        raw_path=None,
                        error=f"Network error: {type(e).__name__}",
                        index=index,
                    )

        # Should never reach here
        return _make_entry(
            url=url,
            final_url=url,
            status_code=None,
            content_type=None,
            sitemap_lastmod=lastmod,
            sha256=None,
            raw_path=None,
            error="Max retries exceeded",
            index=index,
        )

    def _process_success(
        self,
        url: str,
        response: httpx.Response,
        previous_entry: ManifestEntry | None,
        index: bool,
        lastmod: date | None,
    ) -> ManifestEntry:
        """Process a successful 200 response."""
        content = response.content
        content_type = response.headers.get("content-type", "")

        # Determine suffix
        if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
            suffix = ".pdf"
        else:
            suffix = ".html"

        # Save raw content
        sha256, raw_path = save_raw(self.raw_dir, content, suffix)

        return _make_entry(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            content_type=content_type,
            sitemap_lastmod=lastmod,
            sha256=sha256,
            raw_path=str(raw_path.relative_to(self.raw_dir.parent)),
            error=None,
            index=index,
        )

    def _extract_pdf_links(
        self,
        html_content: bytes,
        page_url: str,
        robots: RobotFileParser,
    ) -> list[str]:
        """Extract PDF links from HTML that match pdf_allow patterns."""
        from urllib.parse import urlparse

        pdf_urls = []
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']

                # Use absolutize to convert to absolute URL
                absolute_url = absolutize(href, page_url)
                if not absolute_url:
                    continue

                # Check if it's a PDF URL
                if '.pdf' not in absolute_url.lower():
                    continue

                # Check if allowed by robots
                if not robots.can_fetch(USER_AGENT, absolute_url):
                    continue

                # Check pdf_allow patterns specifically
                parsed = urlparse(absolute_url)
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                # Check drop patterns first
                drop_match = any(re.search(pattern, clean_url) for pattern in self.cfg.link_drop_patterns)
                if drop_match:
                    continue

                # Check pdf_allow patterns
                pdf_allowed = any(re.search(pattern, clean_url) for pattern in self.cfg.pdf_allow)
                if not pdf_allowed:
                    continue

                pdf_urls.append(absolute_url)

        except Exception:
            pass

        return pdf_urls

    def _wait_for_rate_limit(self) -> None:
        """Wait to ensure minimum interval between requests."""
        if self.last_request_time is not None:
            elapsed = self.now() - self.last_request_time
            if elapsed < self.min_interval_s:
                self.sleep(self.min_interval_s - elapsed)

        self.last_request_time = self.now()
