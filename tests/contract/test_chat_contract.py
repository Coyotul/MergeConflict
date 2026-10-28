"""The committed frontend contract matches the running app."""
import json
import shutil
from pathlib import Path
from uuid import uuid4

import yaml

from src.api.app import create_app
from src.core.settings import OrchestratorSettings
from src.models.chat import ErrorBody, TurnResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = REPO_ROOT / "contracts" / "http"
EXAMPLES_DIR = CONTRACT_DIR / "examples" / "chat"

MAIN_STAGES = [
    "discovery",
    "collecting_information",
    "eligibility",
    "documents",
    "offer_selection",
    "awaiting_confirmation",
    "submitted",
]


def build_app():
    # Explicit settings: never read .env here.
    settings = OrchestratorSettings(
        model="fake", session_store="memory", config_dir=REPO_ROOT / "config" / "orchestrator"
    )
    return create_app(settings)


def test_committed_openapi_matches_app():
    committed = yaml.safe_load((CONTRACT_DIR / "chat.openapi.yaml").read_text(encoding="utf-8"))
    assert committed == build_app().openapi()


def test_openapi_is_deterministic():
    assert build_app().openapi() == build_app().openapi()


def test_examples_validate():
    files = sorted(EXAMPLES_DIR.glob("*.json"))
    assert files
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if path.name.startswith("error-"):
            ErrorBody.model_validate(data)
        else:
            TurnResponse.model_validate(data)


def test_examples_cover_main_stages():
    stages = set()
    for path in EXAMPLES_DIR.glob("[0-9][0-9]-*.json"):
        stages.add(json.loads(path.read_text(encoding="utf-8"))["progress"]["stage"])
    assert set(MAIN_STAGES) <= stages
    assert (EXAMPLES_DIR / "error-503.json").exists()
    assert (EXAMPLES_DIR / "error-422.json").exists()


def test_error_examples_have_expected_codes():
    e503 = ErrorBody.model_validate_json((EXAMPLES_DIR / "error-503.json").read_text(encoding="utf-8"))
    e422 = ErrorBody.model_validate_json((EXAMPLES_DIR / "error-422.json").read_text(encoding="utf-8"))
    assert e503.retryable is True
    assert e422.code == "invalid_request" and e422.retryable is False


def test_export_reproduces_committed_files():
    """Re-running the export gives byte-identical files (no churn, examples are current)."""
    from scripts.export_chat_contract import export_contract, mock_settings

    out = Path(__file__).parent / ".test_tmp" / uuid4().hex
    try:
        export_contract(create_app(mock_settings(out / "uploads")), out)
        produced = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file() and "uploads" not in p.parts)
        # Only the chat contract is exported here; other contracts share contracts/http/.
        committed = sorted(
            p.relative_to(CONTRACT_DIR) for p in CONTRACT_DIR.rglob("*")
            if p.is_file() and p.suffix in (".json", ".yaml")
            and (p.name == "chat.openapi.yaml" or "chat" in p.relative_to(CONTRACT_DIR).parts[:-1])
        )
        assert produced == committed
        for rel in produced:
            assert _lf(out / rel) == _lf(CONTRACT_DIR / rel), rel
    finally:
        shutil.rmtree(out, ignore_errors=True)


def _lf(path: Path) -> bytes:
    """File bytes with line endings normalised (git may check files out with CRLF)."""
    return path.read_bytes().replace(b"\r\n", b"\n")
