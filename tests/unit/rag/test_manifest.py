"""Tests for the crawl manifest (JSON lines)."""
from datetime import date, datetime, timezone

from src.services.document_ingestion.manifest import ManifestEntry, read_manifest, write_manifest


def test_manifest_round_trip_with_defaults(tmp_path):
    path = tmp_path / "manifest.jsonl"
    fetched = datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)
    entries = [
        ManifestEntry(
            url="https://www.raiffeisen.ro/ro/demo.html",
            final_url="https://www.raiffeisen.ro/ro/demo.html",
            fetched_at=fetched,
            status_code=200,
            content_type="text/html",
            sitemap_lastmod=date(2026, 9, 30),
            sha256="abc",
            raw_path="abc.html",
        ),
        ManifestEntry(
            url="https://www.raiffeisen.ro/ro/lipsa.html",
            final_url="https://www.raiffeisen.ro/ro/lipsa.html",
            fetched_at=fetched,
            status_code=None,
            content_type=None,
            sitemap_lastmod=None,
            sha256=None,
            raw_path=None,
            error="timeout",
        ),
    ]
    write_manifest(path, entries)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    loaded = read_manifest(path)
    assert loaded == entries
    assert loaded[0].index is True and loaded[0].withdrawn is False and loaded[0].error is None
    assert loaded[1].error == "timeout" and loaded[1].sitemap_lastmod is None


def test_write_manifest_rewrites_whole_file(tmp_path):
    path = tmp_path / "manifest.jsonl"
    fetched = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def make(url):
        return ManifestEntry(url=url, final_url=url, fetched_at=fetched, status_code=200, content_type=None,
                             sitemap_lastmod=None, sha256=None, raw_path=None)

    write_manifest(path, [make("https://a.invalid/1"), make("https://a.invalid/2")])
    write_manifest(path, [make("https://a.invalid/3")])
    assert [e.url for e in read_manifest(path)] == ["https://a.invalid/3"]
