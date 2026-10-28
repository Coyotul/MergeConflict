"""Command-line entry points for the local RAG knowledge base."""
import sys
from collections.abc import Callable

from src.core.errors import EmbeddingModelUnavailable, KnowledgeStoreUnavailable

# A refused local connection can hang instead of failing fast; bound it.
CONNECT_TIMEOUT_S = 10


def run_cli(main: Callable[[], int]) -> None:
    """Run a CLI main; typed infrastructure errors become a one-line message and exit code 2."""
    try:
        code = main()
    except (KnowledgeStoreUnavailable, EmbeddingModelUnavailable) as exc:
        message = " ".join(str(exc).split())
        print(f"error: {type(exc).__name__}: {message}", file=sys.stderr)
        sys.exit(2)
    sys.exit(code)
