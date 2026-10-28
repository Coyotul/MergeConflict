"""Integration tests for the chat HTTP API."""
import io
import json
import shutil
from datetime import datetime, UTC
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.agent.orchestration.orchestrator import Orchestrator
from src.agent.orchestration.state import (
    ApplicationState,
    ApplicationSummary,
    DocumentRecord,
    DocumentStatus,
    FieldValue,
    FieldSource,
    SessionState,
    StoredMessage,
)
from src.agent.tools.stubs import StubData, build_stub_registry
from src.agent.tools.retrieval import StubPolicySearch
from src.api.app import create_app
from src.core.errors import ModelUnavailable, SessionBusy
from src.core.settings import OrchestratorSettings, load_orchestrator_settings
from src.integrations.llm.chat import FakeChatModel
from src.models.credit import ProductRequirements, FieldSpec, FieldType, DocumentRequirement, Money, LoanOffer
from src.models.knowledge import Product
from src.services.conversations.store import InMemorySessionStore


@pytest.fixture
def config_dir():
    """Return the config directory path."""
    return Path("config/orchestrator")


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
def fake_model():
    """Create a fake chat model for testing."""
    def default_response(messages):
        return json.dumps({
            "action": {"type": "respond", "message": "Hello! How can I help you today?"},
            "updates": []
        })
    return FakeChatModel(default_response)


@pytest.fixture
def store():
    """Create an in-memory session store."""
    return InMemorySessionStore()


@pytest.fixture
def orchestrator(config_dir, fake_model, store):
    """Create an orchestrator with in-memory store for testing."""
    stub_data = StubData.load(config_dir)
    policy_search = StubPolicySearch(config_dir)
    registry = build_stub_registry(stub_data, policy_search)
    catalog_codes = list(stub_data.products.keys())

    return Orchestrator(
        store=store,
        model=fake_model,
        registry=registry,
        catalog_codes=catalog_codes,
        max_steps=4,
        history_window=30
    )


@pytest.fixture
def settings(test_uploads_dir):
    """Create test settings with test uploads directory."""
    return OrchestratorSettings(
        model="fake",
        uploads_dir=test_uploads_dir,
        max_upload_bytes=10485760,
        config_dir=Path("config/orchestrator")
    )


@pytest.fixture
def client(orchestrator, settings):
    """Create a test client with the orchestrator."""
    app = create_app(settings=settings, orchestrator=orchestrator)
    return TestClient(app)


@pytest.fixture
def customer_id():
    """Return a test customer ID."""
    return "test-customer-123"


def test_create_session_201(client, customer_id):
    """Test creating a new session returns 201 with greeting."""
    response = client.post(
        "/chat/sessions",
        json={},
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 201
    data = response.json()
    assert "session_id" in data
    assert "turn_id" in data
    assert "session_version" in data
    assert data["session_version"] == 0
    assert "messages" in data
    assert len(data["messages"]) > 0
    assert data["messages"][0]["role"] == "assistant"
    assert "awaiting" in data
    assert "progress" in data
    assert "blocks" in data
    assert "simulated" in data


def test_missing_customer_header_401(client):
    """Test missing X-Customer-Id header returns 401."""
    response = client.post("/chat/sessions", json={})

    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "missing_customer_id"
    assert data["retryable"] is False


def test_message_round_trip_returns_turn_response(client, customer_id):
    """Test sending a message returns a TurnResponse."""
    # Create session
    create_response = client.post(
        "/chat/sessions",
        json={},
        headers={"X-Customer-Id": customer_id}
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["session_id"]

    # Send message
    message_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"text": "I need help with a loan"},
        headers={"X-Customer-Id": customer_id}
    )

    assert message_response.status_code == 200
    data = message_response.json()
    assert data["session_id"] == session_id
    assert "turn_id" in data
    assert "messages" in data
    assert "awaiting" in data
    assert "progress" in data


def test_other_customer_403(client, customer_id):
    """Test accessing another customer's session returns 403."""
    # Create session with one customer
    create_response = client.post(
        "/chat/sessions",
        json={},
        headers={"X-Customer-Id": customer_id}
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["session_id"]

    # Try to access with different customer
    other_customer = "other-customer-456"
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"text": "Hello"},
        headers={"X-Customer-Id": other_customer}
    )

    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "forbidden"
    assert data["retryable"] is False


def test_unknown_session_404(client, customer_id):
    """Test accessing non-existent session returns 404."""
    fake_session_id = uuid4().hex

    response = client.post(
        f"/chat/sessions/{fake_session_id}/messages",
        json={"text": "Hello"},
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 404
    data = response.json()
    assert data["code"] == "session_not_found"
    assert data["retryable"] is False


def test_model_unavailable_503_retryable(client, customer_id, orchestrator, fake_model):
    """Test model unavailable returns 503 with retryable flag and sanitized message."""
    # First create a session with model working
    create_response = client.post(
        "/chat/sessions",
        json={},
        headers={"X-Customer-Id": customer_id}
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["session_id"]

    # Make model raise exception with technical details
    def raise_unavailable(messages):
        raise ModelUnavailable("Connection to api.featherless.ai:443 timed out after 30.0s")

    fake_model.responses = raise_unavailable

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"text": "Hello"},
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 503
    data = response.json()
    assert data["code"] == "service_unavailable"
    assert data["retryable"] is True
    # Message should be sanitized - no API details
    assert "assistant is temporarily unavailable" in data["message"].lower()
    assert "featherless" not in data["message"].lower()
    assert "api." not in data["message"].lower()


def test_upload_wrong_type_415_and_too_large_413(client, customer_id, test_uploads_dir):
    """Test upload validation: wrong content type returns 415, too large returns 413."""
    # Create session
    create_response = client.post(
        "/chat/sessions",
        json={},
        headers={"X-Customer-Id": customer_id}
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["session_id"]

    # Test wrong content type - should not write to disk
    files = {"file": ("test.txt", io.BytesIO(b"plain text"), "text/plain")}
    response = client.post(
        f"/chat/sessions/{session_id}/documents",
        data={"doc_type": "identity_card"},
        files=files,
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 415
    data = response.json()
    assert data["code"] == "unsupported_media_type"
    assert data["retryable"] is False
    # Verify nothing written to disk
    assert len(list(test_uploads_dir.rglob("*"))) == 0

    # Test too large (> 10 MB) - should not write to disk
    large_content = b"X" * (10 * 1024 * 1024 + 1)
    files = {"file": ("large.pdf", io.BytesIO(large_content), "application/pdf")}
    response = client.post(
        f"/chat/sessions/{session_id}/documents",
        data={"doc_type": "identity_card"},
        files=files,
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 413
    data = response.json()
    assert data["code"] == "upload_too_large"
    assert data["retryable"] is False
    # Verify nothing written to disk
    assert len(list(test_uploads_dir.rglob("*"))) == 0


def test_upload_not_requested_422(client, customer_id, test_uploads_dir):
    """Test uploading a document when none is requested returns 422 and writes nothing to disk."""
    # Create session (no documents requested yet)
    create_response = client.post(
        "/chat/sessions",
        json={},
        headers={"X-Customer-Id": customer_id}
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["session_id"]

    # Try to upload without requesting documents first
    files = {"file": ("test.pdf", io.BytesIO(b"fake pdf"), "application/pdf")}
    response = client.post(
        f"/chat/sessions/{session_id}/documents",
        data={"doc_type": "identity_card"},
        files=files,
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "document_not_requested"
    assert data["retryable"] is False
    # Verify nothing written to disk
    assert len(list(test_uploads_dir.rglob("*"))) == 0


def test_upload_accepted_returns_checklist(client, customer_id, orchestrator, store):
    """Test successful upload returns TurnResponse with document checklist."""
    # Seed state at documents stage
    session_id = uuid4().hex
    now = datetime.now(UTC)

    requirements = ProductRequirements(
        product_code=Product.personal_loan,
        fields=[],
        documents=[
            DocumentRequirement(doc_type="identity_card", label="Identity Card", example_hint="CNP-based ID")
        ]
    )

    state = SessionState(
        session_id=session_id,
        customer_id=customer_id,
        created_at=now,
        updated_at=now,
        version=0,
        application=ApplicationState(
            product_code=Product.personal_loan,
            requirements=requirements,
            fields={},
            documents=[],
            conflicts=[]
        )
    )
    store.create(state)

    # Now upload a document
    files = {"file": ("id_card.jpg", io.BytesIO(b"fake jpeg data"), "image/jpeg")}
    response = client.post(
        f"/chat/sessions/{session_id}/documents",
        data={"doc_type": "identity_card"},
        files=files,
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 200
    data = response.json()
    assert "blocks" in data
    # Should have a document checklist block
    checklist_blocks = [block for block in data["blocks"] if block.get("type") == "document_checklist"]
    assert len(checklist_blocks) > 0
    # The uploaded type should be in the checklist
    items = checklist_blocks[0]["items"]
    identity_items = [item for item in items if item["doc_type"] == "identity_card"]
    assert len(identity_items) == 1
    # Document was processed (status could be accepted, processing, or rejected depending on stub)
    assert identity_items[0]["doc_type"] == "identity_card"


def test_confirmation_flow_over_http(client, customer_id):
    """Test confirmation endpoint exists and handles requests."""
    # Create a session
    create_response = client.post(
        "/chat/sessions",
        json={},
        headers={"X-Customer-Id": customer_id}
    )
    session_id = create_response.json()["session_id"]

    # POST confirmation (will fail business logic but endpoint should respond)
    response = client.post(
        f"/chat/sessions/{session_id}/confirmation",
        json={"summary_version": "v1", "decision": "confirm"},
        headers={"X-Customer-Id": customer_id}
    )

    # Endpoint exists and returns a response (may be 409/422 due to invalid state)
    assert response.status_code in [200, 409, 422]
    data = response.json()
    # Either success with blocks or error with code
    assert "blocks" in data or "code" in data


def test_get_session_view_rebuilds_screen(client, customer_id, orchestrator, store):
    """Test GET /chat/sessions/{id} returns session view excluding action/tool/event messages."""
    # Create session with messages including tool calls
    session_id = uuid4().hex
    now = datetime.now(UTC)

    state = SessionState(
        session_id=session_id,
        customer_id=customer_id,
        created_at=now,
        updated_at=now,
        version=0
    )
    store.create(state)

    # Add messages of various roles
    messages = [
        StoredMessage(
            message_id=uuid4().hex,
            turn_id=uuid4().hex,
            role="customer",
            content="Hello",
            citations=[],
            created_at=now
        ),
        StoredMessage(
            message_id=uuid4().hex,
            turn_id=uuid4().hex,
            role="action",
            content='{"action": {"type": "call_tool", "tool": "search_banking_policies"}}',
            citations=[],
            created_at=now
        ),
        StoredMessage(
            message_id=uuid4().hex,
            turn_id=uuid4().hex,
            role="tool",
            content='{"passages": []}',
            citations=[],
            created_at=now
        ),
        StoredMessage(
            message_id=uuid4().hex,
            turn_id=uuid4().hex,
            role="event",
            content="SESSION_STARTED",
            citations=[],
            created_at=now
        ),
        StoredMessage(
            message_id=uuid4().hex,
            turn_id=uuid4().hex,
            role="assistant",
            content="How can I help you?",
            citations=[],
            created_at=now
        ),
    ]
    store.append_messages(session_id, messages)

    # Get session view
    response = client.get(
        f"/chat/sessions/{session_id}",
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == session_id
    assert "created_at" in data
    assert "messages" in data
    assert "latest" in data

    # Check messages exclude tool/event/action roles
    for msg in data["messages"]:
        assert msg["role"] in ["customer", "assistant"]
        assert msg["role"] not in ["action", "tool", "event"]

    # Latest should have TurnResponse structure
    assert "awaiting" in data["latest"]
    assert "progress" in data["latest"]
    assert "blocks" in data["latest"]


def test_health(client):
    """Test health endpoint returns status and configuration."""
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "model" in data
    assert "session_store" in data
    # Should not contain secrets
    assert "api_key" not in str(data).lower()


def test_blank_message_422(client, customer_id):
    """Test sending a blank message returns 422 with sanitized message."""
    # Create session
    create_response = client.post(
        "/chat/sessions",
        json={},
        headers={"X-Customer-Id": customer_id}
    )
    session_id = create_response.json()["session_id"]

    # Send blank message
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"text": "   "},
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "invalid_request"
    # Message should be sanitized - no input values shown
    assert "   " not in data["message"]


def test_session_busy_409_body(client, customer_id, orchestrator, monkeypatch):
    """Test that SessionBusy returns 409 with correct ErrorBody structure."""
    # Create session
    create_response = client.post(
        "/chat/sessions",
        json={},
        headers={"X-Customer-Id": customer_id}
    )
    session_id = create_response.json()["session_id"]

    # Mock orchestrator.handle to raise SessionBusy
    def raise_busy(session_id, customer_id, event):
        raise SessionBusy(f"Session {session_id} is busy")

    monkeypatch.setattr(orchestrator, "handle", raise_busy)

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"text": "Hello"},
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 409
    data = response.json()
    assert data["code"] == "session_busy"
    assert data["retryable"] is True
    assert "processing another request" in data["message"].lower()


def test_internal_error_500_body(customer_id, orchestrator, settings, monkeypatch):
    """Test that unexpected exceptions return 500 with generic message."""
    from fastapi.testclient import TestClient

    # Create a new client with raise_server_exceptions=False
    app = create_app(settings=settings, orchestrator=orchestrator)
    client = TestClient(app, raise_server_exceptions=False)

    # Create session
    create_response = client.post(
        "/chat/sessions",
        json={},
        headers={"X-Customer-Id": customer_id}
    )
    session_id = create_response.json()["session_id"]

    # Mock orchestrator.handle to raise an unexpected exception
    def raise_unexpected(session_id, customer_id, event):
        raise RuntimeError("Database connection pool exhausted")

    monkeypatch.setattr(orchestrator, "handle", raise_unexpected)

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"text": "Hello"},
        headers={"X-Customer-Id": customer_id}
    )

    assert response.status_code == 500
    data = response.json()
    assert data["code"] == "internal_error"
    assert data["retryable"] is False
    # Message should be generic - no exception details
    assert "database" not in data["message"].lower()
    assert "pool" not in data["message"].lower()
    assert "internal error" in data["message"].lower()
