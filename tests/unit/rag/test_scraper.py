"""Tests for polite incremental scraper."""
from datetime import datetime, date
from pathlib import Path

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


def make_fake_time():
    """Create fake time functions for testing."""
    state = {"time": 0.0, "sleeps": []}

    def now():
        return state["time"]

    def sleep(seconds):
        state["sleeps"].append(seconds)
        state["time"] += seconds

    return now, sleep, state


def test_discovers_pages_with_lastmod(tmp_path, source_config):
    """Scraper discovers sitemap pages and parses lastmod dates."""
    robots_txt = b"User-agent: *\nDisallow: /admin/"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.raiffeisen.ro/persoane-fizice/credite/page1</loc>
    <lastmod>2026-10-15</lastmod>
  </url>
  <url>
    <loc>https://www.raiffeisen.ro/persoane-fizice/credite/page2</loc>
    <lastmod>2026-10-16T10:30:00Z</lastmod>
  </url>
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
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep)
    report = scraper.run([])

    assert len(report.entries) == 2
    page1 = next(e for e in report.entries if "page1" in e.url)
    page2 = next(e for e in report.entries if "page2" in e.url)
    assert page1.sitemap_lastmod == date(2026, 10, 15)
    assert page2.sitemap_lastmod == date(2026, 10, 16)


def test_robots_404_allows_all(tmp_path, source_config):
    """404 robots.txt means allow everything."""
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page1</loc></url>
</urlset>"""
    page_html = b"<html><body>Test</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        else:
            return httpx.Response(200, content=page_html)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep)
    report = scraper.run([])

    assert len(report.entries) == 1
    assert report.completed is True


def test_robots_500_fails_run(tmp_path, source_config):
    """robots.txt 500 error marks run as incomplete and no pages requested."""
    request_log = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(str(request.url.path))
        if request.url.path == "/robots.txt":
            return httpx.Response(503)
        else:
            return httpx.Response(200, content=b"should not be reached")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, max_retries=1, now=now, sleep=sleep)
    report = scraper.run([])

    assert report.completed is False
    assert "/sitemap.xml" not in request_log
    assert any("robots.txt" in k for k in report.failed.keys())


def test_sitemap_500_fails_run(tmp_path, source_config):
    """Sitemap 500 error marks run as incomplete, no withdrawals."""
    robots_txt = b"User-agent: *\nAllow: /"
    previous = [ManifestEntry(
        url="https://www.raiffeisen.ro/persoane-fizice/credite/old",
        final_url="https://www.raiffeisen.ro/persoane-fizice/credite/old",
        fetched_at=datetime(2026, 10, 1),
        status_code=200,
        content_type="text/html",
        sitemap_lastmod=None,
        sha256="abc123",
        raw_path="raw/abc123.html",
        index=True,
        withdrawn=False
    )]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(503)
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep)
    report = scraper.run(previous)

    assert report.completed is False
    assert len(report.withdrawn) == 0
    assert any("sitemap.xml" in k for k in report.failed.keys())


def test_robots_on_pdf_links(tmp_path, source_config):
    """PDF links disallowed by robots are never requested (M2)."""
    robots_txt = b"User-agent: *\nDisallow: /secret/"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page1</loc></url>
</urlset>"""
    page_html = b'<html><body><a href="/documents/cgb.pdf">OK</a><a href="/secret/bad.pdf">Bad</a></body></html>'
    pdf_content = b"%PDF"
    request_log = []
    source_config.pdf_allow = [r"/documents/.*\.pdf", r"/secret/.*\.pdf"]

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(str(request.url.path))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        elif request.url.path == "/persoane-fizice/credite/page1":
            return httpx.Response(200, content=page_html)
        elif request.url.path == "/documents/cgb.pdf":
            return httpx.Response(200, content=pdf_content, headers={"content-type": "application/pdf"})
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep)
    report = scraper.run([])

    assert "/secret/bad.pdf" not in request_log
    assert len([e for e in report.entries if "secret" in e.url]) == 0


def test_robots_on_extra_urls(tmp_path, source_config):
    """extra_urls disallowed by robots are never requested (M3)."""
    robots_txt = b"User-agent: *\nDisallow: /forbidden/"
    sitemap_xml = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    request_log = []
    source_config.extra_urls = [
        "https://www.raiffeisen.ro/persoane-fizice/credite/ok",
        "https://www.raiffeisen.ro/forbidden/bad"
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(str(request.url.path))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        else:
            return httpx.Response(200, content=b"<html><body>Test</body></html>")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep)
    report = scraper.run([])

    assert "/forbidden/bad" not in request_log


def test_suffix_detection(tmp_path, source_config):
    """PDFs saved with .pdf, HTML with .html, handles uppercase (M4)."""
    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    page_html = b"<html><body>Test</body></html>"
    pdf_content = b"%PDF"
    source_config.extra_urls = [
        "https://www.raiffeisen.ro/persoane-fizice/credite/page.html",
        "https://www.raiffeisen.ro/documents/file.PDF",
        "https://www.raiffeisen.ro/documents/x.pdf.download.pdf"
    ]
    source_config.pdf_allow = [r"/documents/.*"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        elif ".html" in request.url.path:
            return httpx.Response(200, content=page_html, headers={"content-type": "text/html"})
        else:
            return httpx.Response(200, content=pdf_content, headers={"content-type": "application/pdf"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep)
    report = scraper.run([])

    raw_dir = tmp_path / "raw"
    for entry in report.entries:
        if entry.raw_path:
            raw_file = raw_dir.parent / entry.raw_path
            if ".html" in entry.url:
                assert raw_file.suffix == ".html"
            elif ".pdf" in entry.url.lower():
                assert raw_file.suffix == ".pdf"


def test_seed_has_index_false(tmp_path, source_config):
    """Discovery seeds have index=False."""
    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    page_html = b"<html><body>Seed</body></html>"
    source_config.discovery_seeds = ["https://www.raiffeisen.ro/persoane-fizice/credite/seed"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        else:
            return httpx.Response(200, content=page_html)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep)
    report = scraper.run([])

    entry = report.entries[0]
    assert entry.index is False


def test_withdrawn_scenario_2_incomplete_run(tmp_path, source_config):
    """Incomplete run: old.pdf returns 404 but not marked withdrawn."""
    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/p1</loc></url>
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/p2</loc></url>
</urlset>"""
    page_html = b"<html><body>OK</body></html>"
    previous = [ManifestEntry(
        url="https://www.raiffeisen.ro/documents/cgb.pdf",
        final_url="https://www.raiffeisen.ro/documents/cgb.pdf",
        fetched_at=datetime(2026, 10, 1),
        status_code=200,
        content_type="application/pdf",
        sitemap_lastmod=None,
        sha256="oldpdf",
        raw_path="raw/oldpdf.pdf",
        index=True,
        withdrawn=False
    )]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        elif request.url.path == "/persoane-fizice/credite/p1":
            raise httpx.TimeoutException("Timeout")
        elif request.url.path == "/documents/cgb.pdf":
            return httpx.Response(404)
        else:
            return httpx.Response(200, content=page_html)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, max_retries=1, now=now, sleep=sleep)
    report = scraper.run(previous)

    assert report.completed is False
    assert len(report.withdrawn) == 0
    old_entry = next(e for e in report.entries if "cgb.pdf" in e.url)
    assert old_entry.sha256 == "oldpdf"
    assert old_entry.withdrawn is False


def test_5xx_retry_then_exhausted(tmp_path, source_config):
    """5xx retried with backoff, exhausted retries in failed."""
    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/broken</loc></url>
</urlset>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        else:
            return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, state = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, max_retries=2, now=now, sleep=sleep)
    report = scraper.run([])

    assert any("broken" in k for k in report.failed.keys())
    backoff_sleeps = [s for s in state["sleeps"] if s in (2.0, 4.0)]
    assert len(backoff_sleeps) >= 2


def test_redirect_final_url(tmp_path, source_config):
    """final_url is recorded after a redirect."""
    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/old-path</loc></url>
</urlset>"""
    page_html = b"<html><body>Redirected</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        else:
            return httpx.Response(200, content=page_html)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep)
    report = scraper.run([])

    entry = report.entries[0]
    assert entry.url == "https://www.raiffeisen.ro/persoane-fizice/credite/old-path"
    assert entry.final_url is not None


def test_retry_then_succeeds(tmp_path, source_config):
    """Retries on timeout with exponential backoff, then succeeds."""
    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/flaky</loc></url>
</urlset>"""
    page_html = b"<html><body>Success</body></html>"
    attempt_count = {"flaky": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        elif request.url.path == "/persoane-fizice/credite/flaky":
            attempt_count["flaky"] += 1
            if attempt_count["flaky"] <= 2:
                raise httpx.TimeoutException("Timeout")
            return httpx.Response(200, content=page_html)
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, state = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, max_retries=3, now=now, sleep=sleep)
    report = scraper.run([])

    assert len(report.new) == 1
    assert attempt_count["flaky"] == 3
    backoff_sleeps = [s for s in state["sleeps"] if s in (2.0, 4.0)]
    assert 2.0 in backoff_sleeps
    assert 4.0 in backoff_sleeps


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
    request_times = []

    def handler(request: httpx.Request) -> httpx.Response:
        # Record time at request start using the fake clock
        request_times.append(state["time"])
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        else:
            return httpx.Response(200, content=page_html)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, state = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=2.0, now=now, sleep=sleep)
    report = scraper.run([])

    # Check that consecutive requests are at least 2.0s apart
    for i in range(1, len(request_times)):
        interval = request_times[i] - request_times[i-1]
        assert interval >= 2.0, f"Request {i} started {interval}s after request {i-1}, expected >= 2.0s"


def test_unchanged_by_hash(tmp_path, source_config):
    """Scraper detects unchanged and changed documents by hash."""
    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page1</loc></url>
</urlset>"""
    page_html_v1 = b"<html><body>Version 1</body></html>"
    page_html_v2 = b"<html><body>Version 2</body></html>"

    content_version = {"current": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        elif request.url.path == "/persoane-fizice/credite/page1":
            if content_version["current"] == 1:
                return httpx.Response(200, content=page_html_v1, headers={"content-type": "text/html"})
            else:
                return httpx.Response(200, content=page_html_v2, headers={"content-type": "text/html"})
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)

    # Run 1: First fetch
    now1, sleep1, _ = make_fake_time()
    scraper1 = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now1, sleep=sleep1)
    report1 = scraper1.run([])
    assert len(report1.new) == 1
    assert len(report1.unchanged) == 0
    assert len(report1.changed) == 0

    # Run 2: Same content, should be unchanged
    now2, sleep2, _ = make_fake_time()
    scraper2 = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now2, sleep=sleep2)
    report2 = scraper2.run(report1.entries)
    assert len(report2.new) == 0
    assert len(report2.unchanged) == 1
    assert len(report2.changed) == 0

    # Run 3: Changed content
    content_version["current"] = 2
    now3, sleep3, _ = make_fake_time()
    scraper3 = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now3, sleep=sleep3)
    report3 = scraper3.run(report2.entries)
    assert len(report3.new) == 0
    assert len(report3.unchanged) == 0
    assert len(report3.changed) == 1


def test_404_not_retried(tmp_path, source_config):
    """Scraper does not retry 404 or 410 responses."""
    robots_txt = b"User-agent: *\nAllow: /"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/missing404</loc></url>
  <url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/gone410</loc></url>
</urlset>"""
    attempt_count = {"missing404": 0, "gone410": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_txt)
        elif request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        elif request.url.path == "/persoane-fizice/credite/missing404":
            attempt_count["missing404"] += 1
            return httpx.Response(404)
        elif request.url.path == "/persoane-fizice/credite/gone410":
            attempt_count["gone410"] += 1
            return httpx.Response(410)
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, state = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, max_retries=3, now=now, sleep=sleep)
    report = scraper.run([])

    # Each should have been tried exactly once
    assert attempt_count["missing404"] == 1
    assert attempt_count["gone410"] == 1

    # No backoff sleeps for 404/410
    backoff_sleeps = [s for s in state["sleeps"] if s in (2.0, 4.0, 8.0)]
    assert len(backoff_sleeps) == 0


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
</body>
</html>"""
    pdf_content = b"%PDF-1.4\nfake pdf content"
    request_log = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(str(request.url.path))
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
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep)
    report = scraper.run([])

    # Exactly these URLs should be requested (no more, no less, no duplicates)
    assert sorted(request_log) == sorted([
        "/robots.txt",
        "/sitemap.xml",
        "/persoane-fizice/credite/nevoi-personale",
        "/documents/cgb.pdf"
    ])

    # Should have exactly the page and PDF in entries
    assert len(report.entries) == 2
    urls = {e.url for e in report.entries}
    assert "https://www.raiffeisen.ro/persoane-fizice/credite/nevoi-personale" in urls
    assert "https://www.raiffeisen.ro/documents/cgb.pdf" in urls

    # Both should be new
    assert len(report.new) == 2


def test_withdrawn_only_when_run_completed(tmp_path, source_config):
    """Scraper detects withdrawals when run completes successfully."""
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
        elif request.url.path == "/documents/cgb.pdf":
            return httpx.Response(404)
        else:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=30)
    now, sleep, _ = make_fake_time()
    scraper = Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep)

    # Create previous entry for old.pdf that will be withdrawn
    previous = [ManifestEntry(
        url="https://www.raiffeisen.ro/documents/cgb.pdf",
        final_url="https://www.raiffeisen.ro/documents/cgb.pdf",
        fetched_at=datetime(2026, 10, 1),
        status_code=200,
        content_type="application/pdf",
        sitemap_lastmod=None,
        sha256="abc123",
        raw_path="raw/abc123.pdf",
        index=True,
        withdrawn=False
    )]

    report = scraper.run(previous)

    # Should have new page + withdrawn old PDF
    assert len(report.entries) == 2
    assert len(report.withdrawn) == 1
    assert report.withdrawn[0] == "https://www.raiffeisen.ro/documents/cgb.pdf"

    withdrawn_entry = next(e for e in report.entries if e.url == report.withdrawn[0])
    assert withdrawn_entry.withdrawn is True
    assert report.completed is True


def _sitemap_run(tmp_path, source_config, sitemap_xml: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nDisallow: /admin/")
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, content=sitemap_xml)
        return httpx.Response(200, content=b"<html><body>Test</body></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=30)
    now, sleep, _ = make_fake_time()
    return Scraper(client, source_config, tmp_path / "raw", min_interval_s=0.01, now=now, sleep=sleep).run([])


def test_sitemap_with_invalid_utf8_bytes_is_parsed(tmp_path, source_config):
    """A real sitemap carried Latin-1 bytes in image captions; the URLs must still be discovered."""
    sitemap_xml = (
        b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        b'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
        b"<url><loc>https://www.raiffeisen.ro/persoane-fizice/credite/page1</loc><lastmod>2026-10-15</lastmod>"
        b"<image:image><image:caption>Familie bucur\xe2ndu-se</image:caption></image:image></url></urlset>"
    )
    report = _sitemap_run(tmp_path, source_config, sitemap_xml)

    assert report.completed
    assert [e.url for e in report.entries] == ["https://www.raiffeisen.ro/persoane-fizice/credite/page1"]
    assert report.entries[0].sitemap_lastmod == date(2026, 10, 15)


def test_malformed_sitemap_fails_run_without_crashing(tmp_path, source_config):
    report = _sitemap_run(tmp_path, source_config, b"<urlset><url><loc>broken")

    assert not report.completed
    assert any("sitemap" in url for url in report.failed)
    assert report.entries == []
