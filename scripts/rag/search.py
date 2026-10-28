"""Search the local knowledge index and print the cited passages."""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402

from scripts.rag import CONNECT_TIMEOUT_S, run_cli  # noqa: E402
from src.core.settings import RagSettings, load_rag_settings  # noqa: E402
from src.integrations.llm.embeddings import BgeM3Embedder  # noqa: E402
from src.models.knowledge import SearchQuery, SearchResult, Topic  # noqa: E402
from src.services.retrieval.service import RetrievalService  # noqa: E402


def build_service(settings: RagSettings) -> RetrievalService:
    """A retrieval service over the configured database with the local BGE-M3 embedder."""
    embedder = BgeM3Embedder(settings.embedding_model, settings.embedding_device)
    return RetrievalService(lambda: psycopg.connect(settings.database_url, connect_timeout=CONNECT_TIMEOUT_S), embedder, settings)


def print_result(result: SearchResult) -> None:
    print(f"status: {result.status}  passages: {len(result.passages)}  content_trust: {result.content_trust}")
    for rank, p in enumerate(result.passages, start=1):
        s = p.scores
        dense = f"{s.dense:.3f}" if s.dense is not None else "-"
        keyword = f"{s.keyword:.3f}" if s.keyword is not None else "-"
        print(f"\n#{rank} [{p.chunk_id}] {p.header}")
        print(f"   {p.doc_kind}/{p.kind} topic={p.topic} products={','.join(p.products)} authority={p.authority}")
        print(f"   scores: fused={s.fused:.4f} dense={dense} keyword={keyword}")
        if p.flags:
            print(f"   flags: {', '.join(p.flags)}")
        for warning in p.warnings:
            print(f"   warning: {warning}")
        if p.defer_to is not None:
            print(f"   defer_to: {p.defer_to}")
        print(f"   url: {p.citation.url}")
        print(f"   {p.text[:300]}")
        for link in p.related_links:
            print(f"   read more ({link.link_kind}): {link.title} -> {link.url}")
    for c in result.conflicts:
        print(f"\nconflict: {c.doc_kind}/{c.topic}/{c.product} chunks={c.chunk_ids} "
              f"dates={[d.isoformat() for d in c.effective_dates]}")


def main() -> int:
    settings = load_rag_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--all-topics", action="store_true", help="search non-credit topics too")
    args = parser.parse_args()

    query = SearchQuery(text=args.question, top_k=args.top_k, as_of=args.as_of,
                        topics=list(Topic) if args.all_topics else None)
    print_result(build_service(settings).search(query))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run_cli(main)
