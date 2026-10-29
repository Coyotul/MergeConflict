import os
from pathlib import Path
from typing import Literal, Mapping
from pydantic import BaseModel, Field, SecretStr
from dotenv import load_dotenv


class RagSettings(BaseModel):
    database_url: str = "postgresql://rag:rag@127.0.0.1:5433/rag"
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    raw_dir: Path = Path("data/local/rag/raw")
    manifest_path: Path = Path("data/local/rag/manifest.jsonl")
    sources_path: Path = Path("config/rag/sources.yaml")
    candidate_k: int = 30
    rrf_k: int = 60
    dense_floor: float = 0.55
    keyword_floor: float = 0.10
    secondary_dense_floor: float = 0.40
    authority_weights: dict[str, float] = Field(
        default_factory=lambda: {"high": 1.0, "medium": 0.9, "low": 0.75}
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
    for field in ["candidate_k", "rrf_k"]:
        key = f"RAG_{field.upper()}"
        if key in env:
            kwargs[field] = int(env[key])

    # Float fields
    for field in ["dense_floor", "keyword_floor", "secondary_dense_floor"]:
        key = f"RAG_{field.upper()}"
        if key in env:
            kwargs[field] = float(env[key])

    # Authority weights (JSON string)
    if "RAG_AUTHORITY_WEIGHTS" in env:
        import json
        kwargs["authority_weights"] = json.loads(env["RAG_AUTHORITY_WEIGHTS"])

    return RagSettings(**kwargs)


class OrchestratorSettings(BaseModel):
    featherless_api_key: SecretStr | None = None
    featherless_base_url: str = "https://api.featherless.ai/v1"
    model: str = "openai/gpt-oss-120b"
    temperature: float = 0.2
    request_timeout_s: float = 60.0
    json_mode: bool = True
    max_steps: int = 4
    history_window: int = 30
    session_store: Literal["memory", "file", "postgres"] = "file"
    sessions_dir: Path = Path("data/local/sessions")
    uploads_dir: Path = Path("data/local/uploads")
    max_upload_bytes: int = Field(default=10485760, gt=0)
    config_dir: Path = Path("config/orchestrator")
    retrieval: Literal["stub", "rag"] = "stub"
    database_url: str = "postgresql://rag:rag@127.0.0.1:5433/rag"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://localhost:3000",
            "http://localhost:3001",
        ]
    )


def load_orchestrator_settings(env: Mapping[str, str] | None = None) -> OrchestratorSettings:
    """Load orchestrator settings from environment variables.

    When env is passed, read ONLY that mapping (no .env file, no os.environ).
    When env is None, load .env via python-dotenv and then read os.environ.
    """
    if env is None:
        load_dotenv()
        env = os.environ

    kwargs = {}

    # SecretStr field
    if "FEATHERLESS_API_KEY" in env:
        kwargs["featherless_api_key"] = env["FEATHERLESS_API_KEY"]

    # Featherless base URL
    if "FEATHERLESS_BASE_URL" in env:
        kwargs["featherless_base_url"] = env["FEATHERLESS_BASE_URL"]

    # Simple string fields
    for field in ["model", "session_store", "retrieval", "database_url"]:
        key = f"ORCHESTRATOR_{field.upper()}"
        if key in env:
            kwargs[field] = env[key]

    # Float fields
    for field in ["temperature", "request_timeout_s"]:
        key = f"ORCHESTRATOR_{field.upper()}"
        if key in env:
            kwargs[field] = float(env[key])

    # Integer fields
    for field in ["max_steps", "history_window", "max_upload_bytes"]:
        key = f"ORCHESTRATOR_{field.upper()}"
        if key in env:
            kwargs[field] = int(env[key])

    # Boolean field
    if "ORCHESTRATOR_JSON_MODE" in env:
        val = env["ORCHESTRATOR_JSON_MODE"].lower()
        kwargs["json_mode"] = val in ("true", "1")

    # Path fields
    for field in ["sessions_dir", "uploads_dir", "config_dir"]:
        key = f"ORCHESTRATOR_{field.upper()}"
        if key in env:
            kwargs[field] = Path(env[key])

    # CORS origins (comma-separated, strip whitespace, drop empty)
    if "ORCHESTRATOR_CORS_ORIGINS" in env:
        origins = [
            origin.strip()
            for origin in env["ORCHESTRATOR_CORS_ORIGINS"].split(",")
            if origin.strip()
        ]
        kwargs["cors_origins"] = origins

    return OrchestratorSettings(**kwargs)
