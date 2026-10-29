"""Ingest the scraped documents listed in the manifest into the local knowledge index."""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402

from scripts.rag import CONNECT_TIMEOUT_S, run_cli  # noqa: E402
from src.core.errors import KnowledgeStoreUnavailable  # noqa: E402
from src.core.settings import load_rag_settings  # noqa: E402
from src.integrations.llm.embeddings import BgeM3Embedder  # noqa: E402
from src.services.document_ingestion.manifest import read_manifest  # noqa: E402
from src.services.document_ingestion.pipeline import IngestionPipeline  # noqa: E402
from src.services.document_ingestion.sources import load_source_config  # noqa: E402
from src.storage.application_db.migrate import apply_migrations  # noqa: E402


def connect(url: str, autocommit: bool = False) -> psycopg.Connection:
    try:
        return psycopg.connect(url, autocommit=autocommit, connect_timeout=CONNECT_TIMEOUT_S)
    except psycopg.OperationalError as exc:
        raise KnowledgeStoreUnavailable(f"knowledge store unreachable: {exc}") from exc


def main() -> int:
    settings = load_rag_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=settings.manifest_path)
    parser.add_argument("--rebuild", action="store_true", help="empty the index first (after chunker changes)")
    args = parser.parse_args()

    if not args.manifest.is_file():
        print(f"error: manifest not found: {args.manifest} (run scripts/rag/scrape.py first)", file=sys.stderr)
        return 2
    entries = read_manifest(args.manifest)

    # The database and schema are checked before the model is loaded: loading BGE-M3 takes
    # minutes and gigabytes of memory, wasted if the database is down.
    with connect(settings.database_url) as conn:
        applied = apply_migrations(conn)
    if applied:
        print(f"migrations applied: {', '.join(applied)}")

    embedder = BgeM3Embedder(settings.embedding_model, settings.embedding_device)
    embedder.embed_documents(["Raiffeisen Bank"])  # load the model now so a missing model fails fast

    # The pipeline needs a connection with no open transaction; autocommit keeps it idle between documents.
    with connect(settings.database_url, autocommit=True) as conn:
        pipeline = IngestionPipeline(conn, embedder, load_source_config(settings.sources_path))
        # Manifest raw paths are relative to the parent of raw_dir (e.g. "raw/<sha>.pdf").
        run = pipeline.rebuild if args.rebuild else pipeline.ingest_entries
        report = run(entries, settings.raw_dir.parent)

    counts = Counter(str(o) for o in report.outcomes.values())
    print(f"run {report.run_id}: " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for url, messages in sorted(report.warnings.items()):
        for message in messages:
            print(f"warning: {url}: {message}")
    for url, error in sorted(report.errors.items()):
        print(f"error: {url}: {error}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    run_cli(main)
