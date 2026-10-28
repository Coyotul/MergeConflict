"""Tests for polite incremental scraper."""
from datetime import datetime, date
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from src.services.document_ingestion.scraper import Scraper, ScrapeReport, USER_AGENT
from src.services.document_ingestion.sources import SourceConfig
from src.services.document_ingestion.manifest import ManifestEntry


@pytest.fixture
def source_config():
    """Minimal source config for testing."""
    return SourceConfig(
        sitemap_url="https://www.raiffeisen.ro/sitemap.xml",
        page_allow=[r"/persoane-fizice/credite/"],
        pdf_allow=[r"/documents/cgb\.pdf"],
        discovery_seeds=[],
        extra_urls=[],
        drop_headings=[],
        category_hubs=[],
        link_drop_patterns=[],
        doc_kind_rules=[],
        product_rules=[],
        topic_keyword_rules=[],
        general_terms_sections={},
        fee_list_sections=[],
        default_topic_by_doc_kind={},
    )


def test_discovers_pages_and_allowlisted_pdfs(tmp_path, source_config):
    """Scraper discovers sitemap pages and linked PDFs, respects robots and allowlists."""

    robots_txt = b"""User-agent: *
Disallow: /admin/
"""

    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.raiffeisen.ro/persoane-fizice/credite/nevoi-personale</loc>
    <lastmod>2026-10-15</lastmod>
  </url>
  <url>
    <loc>https://www.raiffeisen.ro/admin/secret</loc>
    <lastmod>2026-10-16</lastmod>
  </url>
  <url>
    <loc>https://www.raiffeisen.ro/despre-noi</loc>
    <lastmod>2026-10-17</lastmod>
  </url>
</urlset>"""

    page_html = b"""<!DOCTYPE html>
<html>
<body>
<h1>Credit Nevoi Personale</h1>
<a href="/documents/cgb.pdf">Conditii Generale</a>
<a href="/documents/marketing.pdf">Marketing PDF</a>
<a href="/other/file.pdf">Other PDF</a>
</body>
</html>"""

    pdf_content = b"%PDF-1.4\n%fake pdf content"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt, headers={"content-type": "text/plain"})
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml, headers={"content-type": "application/xml"})
        elif request.url.path == "/persoane-fizice/credite/nevoi-personale":
            return httpx.Response(200, content=page_html, headers={"content-type": "text/html"})
        elif request.url.path == "/documents/cgb.pdf":
            return httpx.Response(200, content=pdf_content, headers={"content-type": "application/pdf"})
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)

    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.1)
    report = scraper.run([])

    # Should have discovered the allowlisted page and PDF
    assert len(report.entries) == 2
    urls = {e.url for e in report.entries}
    assert "https://www.raiffeisen.ro/persoane-fizice/credite/nevoi-personale" in urls
    assert "https://www.raiffeisen.ro/documents/cgb.pdf" in urls

    # Disallowed URL should not have been requested
    assert "https://www.raiffeisen.ro/admin/secret" not in urls

    # Non-allowlisted page should not be included
    assert "https://www.raiffeisen.ro/despre-noi" not in urls

    # Non-allowlisted PDF should not be included
    assert "https://www.raiffeisen.ro/documents/marketing.pdf" not in urls

    # All should be new
    assert len(report.new) == 2
    assert len(report.changed) == 0
    assert len(report.unchanged) == 0
    assert report.completed is True


def test_rate_limit_spacing(tmp_path, source_config):
    """Scraper respects minimum interval between requests."""

    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page1</loc></url>
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page2</loc></url>
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page3</loc></url>
</urlset>"""

    page_html = b"<html><body>Test</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        else:
            return httpx.Response(200, content=page_html)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)

    # Mock time to track intervals
    fake_time = 0.0
    sleep_calls = []

    def mock_now():
        return fake_time

    def mock_sleep(seconds):
        nonlocal fake_time
        sleep_calls.append(seconds)
        fake_time += seconds

    scraper = Scraper(
        client, source_config, tmp_path / "raw",
        min_interval_s=2.0, now=mock_now, sleep=mock_sleep
    )

    report = scraper.run([])

    # Should have made requests for: robots, sitemap, page1, page2, page3 (5 total)
    # Intervals should ensure at least 2.0s between starts
    # After first request at t=0, need to wait before each subsequent request
    assert len(sleep_calls) >= 4  # At least 4 waits after the first request

    # Verify spacing: simulate request times
    request_times = [0.0]  # First request at t=0
    t = 0.0
    for sleep_duration in sleep_calls[:4]:  # First 4 sleeps for 5 requests
        t += sleep_duration
        request_times.append(t)

    # Check that consecutive requests are at least 2.0s apart
    for i in range(1, len(request_times)):
        interval = request_times[i] - request_times[i-1]
        assert interval >= 2.0, f"Request {i} started {interval}s after request {i-1}, expected >= 2.0s"


def test_retries_then_succeeds_on_timeout(tmp_path, source_config):
    """Scraper retries on timeout with exponential backoff."""

    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/flaky-page</loc></url>
</urlset>"""

    page_html = b"<html><body>Success!</body></html>"

    attempt_count = {"flaky": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        elif request.url.path == "/persoane-fizice/credite/flaky-page":
            attempt_count["flaky"] += 1
            if attempt_count["flaky"] <= 2:
                raise httpx.TimeoutException("Timeout")
            return httpx.Response(200, content=page_html)
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)

    sleep_calls = []

    def mock_sleep(seconds):
        sleep_calls.append(seconds)

    scraper = Scraper(
        client, source_config, tmp_path / "raw",
        max_retries=3, sleep=mock_sleep, min_interval_s=0.1
    )

    report = scraper.run([])

    # Should eventually succeed
    assert len(report.entries) == 1
    assert len(report.new) == 1
    assert report.entries[0].url == "https://www.raiffeisen.ro/persoane-fizice/credite/flaky-page"

    # Should have made 3 attempts (2 timeouts + 1 success)
    assert attempt_count["flaky"] == 3

    # Should have backoff sleeps: 2^1=2 and 2^2=4 seconds for retries
    backoff_sleeps = [s for s in sleep_calls if s in (2.0, 4.0)]
    assert 2.0 in backoff_sleeps
    assert 4.0 in backoff_sleeps


def test_unchanged_by_hash(tmp_path, source_config):
    """Scraper detects unchanged documents by hash."""

    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page1</loc></url>
</urlset>"""

    page_html = b"<html><body>Same content</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        elif request.url.path == "/persoane-fizice/credite/page1":
            return httpx.Response(200, content=page_html, headers={"content-type": "text/html"})
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)

    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.1)

    # First run
    report1 = scraper.run([])
    assert len(report1.new) == 1
    assert len(report1.unchanged) == 0

    # Second run with previous entries
    report2 = scraper.run(report1.entries)
    assert len(report2.new) == 0
    assert len(report2.changed) == 0
    assert len(report2.unchanged) == 1
    assert report2.entries[0].url == "https://www.raiffeisen.ro/persoane-fizice/credite/page1"


def test_withdrawn_only_when_run_completed(tmp_path, source_config):
    """Scraper detects withdrawals only when run completes successfully."""

    # Scenario 1: Previous URL returns 404, run succeeds -> withdrawn
    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/new-page</loc></url>
</urlset>"""

    page_html = b"<html><body>New page</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        elif request.url.path == "/persoane-fizice/credite/new-page":
            return httpx.Response(200, content=page_html)
        elif request.url.path == "/persoane-fizice/credite/old-page":
            return httpx.Response(404)
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)

    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.1)

    # Create a previous entry for a page that will be withdrawn
    previous = [ManifestEntry(
        url="https://www.raiffeisen.ro/persoane-fizice/credite/old-page",
        final_url="https://www.raiffeisen.ro/persoane-fizice/credite/old-page",
        fetched_at=datetime(2026, 10, 1),
        status_code=200,
        content_type="text/html",
        sitemap_lastmod=None,
        sha256="abc123",
        raw_path="raw/abc123.html",
        index=True,
        withdrawn=False
    )]

    report = scraper.run(previous)

    # Should have new page + withdrawn old page
    assert len(report.entries) == 2
    assert len(report.withdrawn) == 1
    assert report.withdrawn[0] == "https://www.raiffeisen.ro/persoane-fizice/credite/old-page"

    withdrawn_entry = next(e for e in report.entries if e.url == report.withdrawn[0])
    assert withdrawn_entry.withdrawn is True
    assert report.completed is True

    # Scenario 2: Many URLs fail -> run incomplete -> no withdrawals
    def handler_with_failures(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            # Return sitemap with 5 URLs
            sitemap = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page1</loc></url>
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page2</loc></url>
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page3</loc></url>
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page4</loc></url>
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page5</loc></url>
</urlset>"""
            return httpx.Response(200, content=sitemap)
        elif "page1" in request.url.path or "page2" in request.url.path:
            # These will repeatedly timeout
            raise httpx.TimeoutException("Timeout")
        else:
            return httpx.Response(200, content=page_html)

    transport2 = httpx.MockTransport(handler_with_failures)
    client2 = httpx.Client(transport=transport2, timeout=30)

    scraper2 = Scraper(client2, source_config, tmp_path / "raw", min_interval_s=0.1, max_retries=2)

    report2 = scraper2.run(previous)

    # Should fail on 2 of 5 URLs (40% failure rate > 10% threshold)
    assert report2.completed is False

    # Old page should not be marked withdrawn, previous entry should be carried over
    assert len(report2.withdrawn) == 0
    old_page_entry = next((e for e in report2.entries if e.url == previous[0].url), None)
    assert old_page_entry is not None
    assert old_page_entry.withdrawn is False
    assert old_page_entry.sha256 == "abc123"  # Original entry preserved


def test_404_not_retried(tmp_path, source_config):
    """Scraper does not retry 404 or 410 responses."""

    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/missing</loc></url>
</urlset>"""

    attempt_count = {"missing": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        elif request.url.path == "/persoane-fizice/credite/missing":
            attempt_count["missing"] += 1
            return httpx.Response(404)
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)

    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.1, max_retries=3)

    report = scraper.run([])

    # Should have tried only once (no retries for 404)
    assert attempt_count["missing"] == 1

    # Should have an entry with 404 status
    assert len(report.entries) == 1
    assert report.entries[0].status_code == 404
    assert report.entries[0].sha256 is None
    assert report.entries[0].raw_path is None
