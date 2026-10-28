"""Integration tests for CORS middleware configuration."""
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.settings import OrchestratorSettings, load_orchestrator_settings


@pytest.fixture
def test_uploads_dir():
    """Create a temporary uploads directory under .test_tmp."""
    test_dir = Path(f"tests/integration/orchestrator/.test_tmp/{uuid4().hex}")
    test_dir.mkdir(parents=True, exist_ok=True)
    yield test_dir
    # Cleanup
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)


@pytest.fixture
def client(test_uploads_dir):
    """Create test client with CORS-enabled app."""
    settings = OrchestratorSettings(
        model="fake",
        session_store="memory",
        uploads_dir=test_uploads_dir,
    )
    app = create_app(settings)
    return TestClient(app)


def test_preflight_allowed_origin(client):
    """Test that preflight requests from allowed origins are accepted."""
    r = client.options(
        "/chat/sessions",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-customer-id,content-type"
        }
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert "x-customer-id" in r.headers["access-control-allow-headers"].lower()


def test_disallowed_origin_gets_no_cors_header(client):
    """Test that requests from disallowed origins don't get CORS headers."""
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_origins_env_parsing():
    """Test that ORCHESTRATOR_CORS_ORIGINS env var is parsed correctly."""
    s = load_orchestrator_settings({"ORCHESTRATOR_CORS_ORIGINS": "http://a:1, http://b:2,"})
    assert s.cors_origins == ["http://a:1", "http://b:2"]


def test_cors_default_origins():
    """Test that default CORS origins are set correctly."""
    assert load_orchestrator_settings({}).cors_origins == [
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3000",
        "http://localhost:3001",
    ]


def test_unhandled_exception_response_carries_cors_headers(test_uploads_dir):
    """A 500 from the catch-all handler must still be readable by the browser."""
    settings = OrchestratorSettings(
        model="fake",
        session_store="memory",
        uploads_dir=test_uploads_dir,
    )
    app = create_app(settings)

    def boom():
        raise RuntimeError("unexpected")

    app.add_api_route("/boom", boom, methods=["GET"])
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/boom", headers={"Origin": "http://127.0.0.1:3000"})
    assert r.status_code == 500
    assert r.json()["code"] == "internal_error"
    assert r.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"

    r = client.get("/boom", headers={"Origin": "https://evil.example"})
    assert r.status_code == 500
    assert "access-control-allow-origin" not in r.headers
