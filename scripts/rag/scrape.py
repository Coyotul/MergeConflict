"""Scrape the allowlisted Raiffeisen pages and PDFs into data/local and write the manifest."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402

from scripts.rag import run_cli  # noqa: E402
from src.core.settings import load_rag_settings  # noqa: E402
from src.services.document_ingestion.manifest import read_manifest, write_manifest  # noqa: E402
from src.services.document_ingestion.scraper import USER_AGENT, Scraper  # noqa: E402
from src.services.document_ingestion.sources import load_source_config  # noqa: E402


def main() -> int:
    settings = load_rag_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=settings.manifest_path)
    args = parser.parse_args()

    cfg = load_source_config(settings.sources_path)
    previous = read_manifest(args.manifest) if args.manifest.exists() else []
    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        report = Scraper(client, cfg, settings.raw_dir).run(previous)

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(args.manifest, report.entries)
    pdfs = sum(1 for e in report.entries if e.raw_path and e.raw_path.endswith(".pdf"))
    pages = sum(1 for e in report.entries if e.raw_path and e.raw_path.endswith(".html"))
    print(f"entries={len(report.entries)} pages={pages} pdfs={pdfs} new={len(report.new)} "
          f"changed={len(report.changed)} unchanged={len(report.unchanged)} failed={len(report.failed)} "
          f"withdrawn={len(report.withdrawn)} completed={report.completed}")
    for url, error in sorted(report.failed.items()):
        print(f"failed: {url}: {error}")
    return 0 if report.completed else 1


if __name__ == "__main__":
    run_cli(main)
