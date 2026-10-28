"""Explicit local-demo settings; no cloud accounts or secrets are required."""

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_path: Path = ROOT / "data" / "local" / "backend-demo.sqlite3"
    config_root: Path = ROOT
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    session_hours: int = Field(default=8, ge=1, le=24)
    max_body_bytes: int = Field(default=32768, ge=1024, le=1048576)
    requests_per_minute: int = Field(default=300, ge=1)
    logins_per_minute: int = Field(default=20, ge=1)
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    )

    @classmethod
    def from_environment(cls) -> "Settings":
        default_path = ROOT / "data" / "local" / "backend-demo.sqlite3"
        return cls(
            database_path=Path(os.environ.get("BACKEND_DB_PATH", str(default_path))),
            host=os.environ.get("BACKEND_HOST", "127.0.0.1"),
            port=os.environ.get("BACKEND_PORT", "8000"),
        )