"""Command-line entry points for the local RAG knowledge base."""
import sys
from collections.abc import Callable

from src.core.errors import EmbeddingModelUnavailable, KnowledgeStoreUnavailable
from src.services.retrieval.factory import CONNECT_TIMEOUT_S

__all__ = ["CONNECT_TIMEOUT_S", "run_cli"]


def run_cli(main: Callable[[], int]) -> None:
    """Run a CLI main; typed infrastructure errors become a one-line message and exit code 2."""
    try:
        code = main()
    except (KnowledgeStoreUnavailable, EmbeddingModelUnavailable) as exc:
        message = " ".join(str(exc).split())
        print(f"error: {type(exc).__name__}: {message}", file=sys.stderr)
        sys.exit(2)
    sys.exit(code)
