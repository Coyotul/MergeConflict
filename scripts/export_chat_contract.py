"""Export the chat API contract for the frontend.

Writes contracts/http/chat.openapi.yaml and, by running the mock-mode happy
path for cust-001, one example TurnResponse per progress stage
(examples/chat/NN-<stage>.json) plus error-503.json and error-422.json.
Volatile values (ids, timestamps) are replaced by fixed placeholders so a
re-run doesn't change the files.

Usage: python scripts/export_chat_contract.py
"""
import io
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from datetime import datetime
from uuid import uuid4

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api.app import create_app  # noqa: E402
from src.core.composition import build_orchestrator  # noqa: E402
from src.core.settings import OrchestratorSettings  # noqa: E402
from src.integrations.llm.chat import FakeChatModel  # noqa: E402
from tests.fixtures.documents import document_bytes  # noqa: E402

CUSTOMER_ID = "cust-001"
FIXED_TIME = "2026-10-28T09:00:00Z"
NO_STAGE = "start"

# The happy path: (kind, argument). Offer and confirmation values come from the previous response.
HAPPY_PATH: list[tuple[str, str | None]] = [
    ("say", "Vreau un credit"),
    ("say", "pentru renovare"),
    ("say", "30000 lei"),
    ("say", "60 luni"),
    ("say", "employed"),
    ("say", "48"),
    ("say", "7000"),
    ("say", "TechCorp SRL"),
    ("say", "400"),
    ("upload", "id_card"),
    ("upload", "payslip"),
    ("upload", "bank_statement"),
    ("say", "da"),
    ("select_offer", None),
    ("say", "Da, trimite cererea"),
]


def run_happy_path(client: TestClient, customer_id: str = CUSTOMER_ID) -> list[dict]:
    """Walk the mock-mode happy path; return every TurnResponse in order."""
    headers = {"X-Customer-Id": customer_id}
    client.app.state.orchestrator._clock = lambda: datetime.fromisoformat(FIXED_TIME.replace("Z", "+00:00"))

    def ok(response, status: int = 200) -> dict:
        if response.status_code != status:
            raise RuntimeError(f"{response.request.url}: {response.status_code} {response.text}")
        return response.json()

    responses = [ok(client.post("/chat/sessions", json={}, headers=headers), 201)]
    base = f"/chat/sessions/{responses[0]['session_id']}"
    for kind, arg in HAPPY_PATH:
        last = responses[-1]
        if kind == "say":
            r = client.post(f"{base}/messages", json={"text": arg}, headers=headers)
        elif kind == "upload":
            files = {"file": (f"{arg}.pdf", io.BytesIO(document_bytes(arg)), "application/pdf")}
            r = client.post(f"{base}/documents", data={"doc_type": arg}, files=files, headers=headers)
        elif kind == "select_offer":
            offers = next(b for b in last["blocks"] if b["type"] == "offers")["offers"]
            r = client.post(f"{base}/offer-selection", json={"offer_id": offers[0]["offer_id"]}, headers=headers)
        else:
            raise ValueError(f"unknown happy-path step {kind}")
        responses.append(ok(r))
    return responses


def error_examples(settings: OrchestratorSettings) -> dict[str, dict]:
    """Real error bodies: 503 from an unavailable model, 422 from a blank message."""
    down = build_orchestrator(settings, model=FakeChatModel(lambda messages: "!unavailable"))
    client = TestClient(create_app(settings, orchestrator=down))
    headers = {"X-Customer-Id": CUSTOMER_ID}
    session_id = client.post("/chat/sessions", json={}, headers=headers).json()["session_id"]
    r503 = client.post(f"/chat/sessions/{session_id}/messages", json={"text": "Vreau un credit"}, headers=headers)
    r422 = client.post(f"/chat/sessions/{session_id}/messages", json={"text": "   "}, headers=headers)
    assert r503.status_code == 503 and r422.status_code == 422, (r503.text, r422.text)
    return {"error-503.json": r503.json(), "error-422.json": r422.json()}


class _Normaliser:
    """Replace volatile values with stable placeholders, numbered in order of appearance."""

    _ID_PATTERNS = [(re.compile(r"\bDRAFT-[0-9a-f]{8}\b"), "DRAFT-{n:08d}"), (re.compile(r"\bAPP-[0-9a-f]{8}\b"), "APP-{n:08d}")]

    def __init__(self):
        self.mapping: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def _placeholder(self, value: str, template: str) -> str:
        if value not in self.mapping:
            n = self._counters[template] = self._counters.get(template, 0) + 1
            self.mapping[value] = template.format(n=n)
        return self.mapping[value]

    def collect(self, response: dict) -> None:
        self._placeholder(response["session_id"], "example-session-{n}")
        self._placeholder(response["turn_id"], "example-turn-{n:02d}")
        version = response["awaiting"].get("summary_version")
        for b in response["blocks"]:
            if b["type"] == "application_summary":
                version = b["summary"]["summary_version"]
        if version:
            self._placeholder(version, "example-summary-v{n}")

    def apply(self, value):
        if isinstance(value, dict):
            return {k: (FIXED_TIME if k == "created_at" else self.apply(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [self.apply(v) for v in value]
        if isinstance(value, str):
            if value in self.mapping:
                return self.mapping[value]
            for pattern, template in self._ID_PATTERNS:
                value = pattern.sub(lambda m, t=template: self._placeholder(m.group(), t), value)
            return value
        return value


def stage_examples(responses: list[dict]) -> dict[str, dict]:
    """The last response of each stage, numbered in the order stages first appear."""
    normaliser = _Normaliser()
    for response in responses:
        normaliser.collect(response)
    order: list[str] = []
    last: dict[str, dict] = {}
    for response in responses:
        stage = response["progress"]["stage"] or NO_STAGE
        if stage not in order:
            order.append(stage)
        last[stage] = response
    return {f"{i:02d}-{stage}.json": normaliser.apply(last[stage]) for i, stage in enumerate(order)}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def export_contract(app: FastAPI, out_dir: Path) -> None:
    """Write the OpenAPI file and the example responses under out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "chat.openapi.yaml").write_text(
        yaml.safe_dump(app.openapi(), sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n"
    )

    examples_dir = out_dir / "examples" / "chat"
    if examples_dir.exists():
        shutil.rmtree(examples_dir)
    examples_dir.mkdir(parents=True)

    scratch = _scratch_dir()
    try:
        # Quote provenance/date affects amounts and IDs; freeze before execution,
        # not just after-the-fact timestamp normalization. Use isolated demo state.
        settings = mock_settings(scratch)
        orchestrator = build_orchestrator(settings, clock=lambda: datetime.fromisoformat(FIXED_TIME))
        with TestClient(create_app(settings, orchestrator=orchestrator)) as client:
            responses = run_happy_path(client)
        for name, data in stage_examples(responses).items():
            _write_json(examples_dir / name, data)
        for name, data in error_examples(mock_settings(scratch)).items():
            _write_json(examples_dir / name, data)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _scratch_dir() -> Path:
    """A throwaway uploads dir under the ignored data/local/."""
    return REPO_ROOT / "data" / "local" / f"contract-export-{uuid4().hex}"


def mock_settings(uploads_dir: Path) -> OrchestratorSettings:
    """Mock-mode settings built explicitly: the export never reads .env."""
    return OrchestratorSettings(
        model="fake", session_store="memory", uploads_dir=uploads_dir, config_dir=REPO_ROOT / "config" / "orchestrator",
        review_db_path=uploads_dir / "review" / "applications.sqlite3",
    )


def main() -> None:
    scratch = _scratch_dir()
    try:
        export_contract(create_app(mock_settings(scratch)), REPO_ROOT / "contracts" / "http")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"Wrote {REPO_ROOT / 'contracts' / 'http'}")


if __name__ == "__main__":
    main()
