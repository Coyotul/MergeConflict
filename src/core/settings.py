import os
from pathlib import Path
from typing import Mapping
from pydantic import BaseModel, Field
from dotenv import load_dotenv


class RagSettings(BaseModel):
    database_url: str = "postgresql://rag:rag@127.0.0.1:5433/rag"
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    raw_dir: Path = Path("data/local/rag/raw")
    manifest_path: Path = Path("data/local/rag/manifest.jsonl")
    sources_path: Path = Path("config/rag/sources.yaml")
    # Calibrated on config/rag/eval/tune.yaml (Task 11; see docs/decisions/0001-local-rag-pgvector.md).
    candidate_k: int = 30
    rrf_k: int = 20
    # Keyword candidates count less than dense ones in fusion: the OR-ed keyword query matches
    # generic terms broadly; at full weight it lowered recall on tune.
    keyword_weight: float = 0.3
    # Evidence threshold: best dense similarity + dense_margin_weight * (best - the dense_margin_rank-th
    # best) must reach dense_floor. A clear best match passes; a flat profile of near misses does not.
    dense_floor: float = 0.75
    dense_margin_weight: float = 3.0
    dense_margin_rank: int = 10
    # Authority multipliers on the fused score. Flat: any down-weighting lowered recall on tune;
    # authority is still reported per passage (low_authority flag).
    authority_weights: dict[str, float] = Field(
        default_factory=lambda: {"high": 1.0, "medium": 1.0, "low": 1.0}
    )


def load_rag_settings(env: Mapping[str, str] | None = None) -> RagSettings:
    """Load RAG settings from environment variables.

    When env is passed, read ONLY that mapping (no .env file, no os.environ).
    When env is None, load .env via python-dotenv and then read os.environ.
    """
    if env is None:
        load_dotenv()
        env = os.environ

    # Build kwargs from RAG_* environment variables
    kwargs = {}

    # Simple string fields
    for field in ["database_url", "embedding_model", "embedding_device"]:
        key = f"RAG_{field.upper()}"
        if key in env:
            kwargs[field] = env[key]

    # Path fields
    for field in ["raw_dir", "manifest_path", "sources_path"]:
        key = f"RAG_{field.upper()}"
        if key in env:
            kwargs[field] = Path(env[key])

    # Integer fields
    for field in ["candidate_k", "rrf_k", "dense_margin_rank"]:
        key = f"RAG_{field.upper()}"
        if key in env:
            kwargs[field] = int(env[key])

    # Float fields
    for field in ["dense_floor", "dense_margin_weight", "keyword_weight"]:
        key = f"RAG_{field.upper()}"
        if key in env:
            kwargs[field] = float(env[key])

    # Authority weights (JSON string)
    if "RAG_AUTHORITY_WEIGHTS" in env:
        import json
        kwargs["authority_weights"] = json.loads(env["RAG_AUTHORITY_WEIGHTS"])

    return RagSettings(**kwargs)
