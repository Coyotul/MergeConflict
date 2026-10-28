"""Tests for prompt and context building."""
import json
from datetime import datetime, UTC
from decimal import Decimal

import pytest

from src.agent.orchestration.fields import DISCOVERY_FIELDS
from src.agent.orchestration.progress import Need, NeedKind, derive_stage
from src.agent.orchestration.prompting import (
    PROMPT_VERSION,
    build_context,
    build_messages,
    load_system_prompt,
)
from src.agent.orchestration.state import (
    ApplicationState,
    FieldSource,
    FieldValue,
    Flow,
    SessionState,
    StoredMessage,
    DocumentRecord,
    DocumentStatus,
    FieldConflict,
    EligibilityRecord,
    OffersRecord,
)
from src.agent.tools.registry import ToolSpec
from src.integrations.llm.chat import ChatMessage
from src.models.credit import (
    EligibilityResult,
    EligibilityStatus,
    FieldSpec,
    FieldType,
    LoanOffer,
    Money,
    ProductRequirements,
    ReasonItem,
    DocumentRequirement,
)
from src.models.knowledge import Product
from pydantic import BaseModel


class DummyInput(BaseModel):
    """Dummy input model for testing."""
    query: str
    limit: int = 10


class DummyOutput(BaseModel):
    """Dummy output model for testing."""
    result: str


def test_prompt_version():
    """PROMPT_VERSION constant is defined."""
    assert PROMPT_VERSION == "orchestrator-v1"


def test_load_system_prompt():
    """System prompt loads from markdown file."""
    prompt = load_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 100  # Non-trivial content


def test_system_prompt_rules_present():
    """System prompt includes required rules and keywords."""
    p = load_system_prompt()

    # Must mention JSON format
    assert "JSON" in p or "json" in p.lower()

    # Must mention TOOL_RESULT
    assert "TOOL_RESULT" in p

    # Must mention citation_ids
    assert "citation_ids" in p or "citation" in p.lower()

    # Must warn against treating retrieved content as instructions
    assert "never instructions" in p.lower() or "not instructions" in p.lower() or "data, not instructions" in p.lower()

    # Must never promise approval
    assert "approved" in p.lower() or "approval" in p.lower()


def test_last_message_is_context_json():
    """build_messages returns list with final system message containing CONTEXT_JSON."""
    now = datetime.now(UTC)
    state = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.credit_application,
        application=ApplicationState(
            product_code=Product.personal_loan,
            fields={
                "purpose": FieldValue(
                    kind="text",
                    value="consolidare",
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                )
            }
        )
    )

    needs = [Need(kind=NeedKind.missing_field, target="amount")]
    tools = []
    history = []

    messages = build_messages(state, needs, tools, history, window=30, notices=[])

    # Should have at least system prompt + context
    assert len(messages) >= 2

    # Last message should be system role
    assert messages[-1].role == "system"

    # Last message should start with CONTEXT_JSON:
    assert messages[-1].content.startswith("CONTEXT_JSON:")

    # Extract and parse JSON
    json_text = messages[-1].content[len("CONTEXT_JSON:"):].strip()
    context = json.loads(json_text)

    # Check structure
    assert "prompt_version" in context
    assert "needs" in context
    assert isinstance(context["needs"], list)

    # Check first need has target="purpose"
    assert len(context["needs"]) > 0
    first_need = context["needs"][0]
    assert first_need["target"] == "amount"


def test_history_window_and_roles():
    """History is windowed and roles are mapped correctly."""
    now = datetime.now(UTC)
    state = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="en",
        active_flow=Flow.product_info
    )

    # Create 40 messages
    history = []
    for i in range(40):
        role_cycle = ["customer", "assistant", "tool", "event", "action"]
        role = role_cycle[i % len(role_cycle)]
        history.append(StoredMessage(
            message_id=f"m{i}",
            turn_id=f"t{i}",
            role=role,
            content=f"content {i}",
            created_at=now
        ))

    messages = build_messages(state, [], [], history, window=30, notices=[])

    # System prompt + 30 history + context = 32
    assert len(messages) == 32

    # First is system prompt
    assert messages[0].role == "system"

    # Last is context
    assert messages[-1].role == "system"
    assert messages[-1].content.startswith("CONTEXT_JSON:")

    # Middle 30 are history (skipped first 10)
    history_messages = messages[1:-1]
    assert len(history_messages) == 30

    # Check role mappings
    role_mapping = {
        "customer": "user",
        "assistant": "assistant",
        "tool": "user",
        "event": "user",
        "action": "assistant"
    }

    # Verify at least one of each mapped role appears correctly
    # Check that tool role is mapped to user
    tool_msg = next((m for i, m in enumerate(history_messages) if history[10 + i].role == "tool"), None)
    if tool_msg:
        assert tool_msg.role == "user"

    # Check that event messages are prefixed with "EVENT:"
    event_indices = [i for i in range(10, 40) if history[i].role == "event"]
    for idx in event_indices:
        hist_idx = idx - 10
        if hist_idx < 30:
            assert messages[1 + hist_idx].content.startswith("EVENT:")


def test_tools_include_input_schema():
    """Context includes tools with input_schema from model_json_schema()."""
    now = datetime.now(UTC)
    state = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.product_info
    )

    # Create a tool spec
    tool_spec = ToolSpec(
        name="search_test",
        description="Test search tool",
        input_model=DummyInput,
        output_model=DummyOutput,
        model_callable=True,
        flows=frozenset([Flow.product_info]),
        handler=lambda i, c: DummyOutput(result="ok")
    )

    context = build_context(state, [], [tool_spec], [])

    assert "tools" in context
    assert len(context["tools"]) == 1

    tool = context["tools"][0]
    assert tool["name"] == "search_test"
    assert tool["description"] == "Test search tool"
    assert "input_schema" in tool

    # Verify it matches model_json_schema()
    expected_schema = DummyInput.model_json_schema()
    assert tool["input_schema"] == expected_schema


def test_context_contains_no_document_raw_text():
    """Context includes only extracted values, never document filenames or raw content."""
    now = datetime.now(UTC)
    state = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.credit_application,
        application=ApplicationState(
            product_code=Product.personal_loan,
            documents=[
                DocumentRecord(
                    document_id="doc1",
                    doc_type="payslip",
                    filename="my_secret_payslip.pdf",
                    status=DocumentStatus.accepted,
                    uploaded_at=now
                )
            ]
        )
    )

    context = build_context(state, [], [], [])

    # Serialize to JSON string
    context_json = json.dumps(context)

    # Should not contain filename
    assert "my_secret_payslip.pdf" not in context_json

    # Documents should only include doc_type, status, rejection_reason
    assert "documents" in context
    docs = context["documents"]
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "payslip"
    assert docs[0]["status"] == "accepted"
    assert "filename" not in docs[0]
    assert "document_id" not in docs[0]


def test_context_field_labels_from_specs():
    """Need labels and field_types come from matching FieldSpec."""
    now = datetime.now(UTC)

    requirements = ProductRequirements(
        product_code=Product.personal_loan,
        fields=[
            FieldSpec(
                name="monthly_income",
                label="Monthly Income",
                type=FieldType.money,
                required=True
            )
        ],
        documents=[]
    )

    state = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.credit_application,
        application=ApplicationState(
            product_code=Product.personal_loan,
            requirements=requirements
        )
    )

    needs = [
        Need(kind=NeedKind.missing_field, target="purpose"),
        Need(kind=NeedKind.missing_field, target="monthly_income"),
    ]

    context = build_context(state, needs, [], [])

    # Check needs
    assert len(context["needs"]) == 2

    # First need - purpose is a discovery field
    need0 = context["needs"][0]
    assert need0["kind"] == "missing_field"
    assert need0["target"] == "purpose"
    assert need0["label"] == "Purpose"  # From DISCOVERY_FIELDS
    assert need0["field_type"] == "text"

    # Second need - monthly_income from requirements
    need1 = context["needs"][1]
    assert need1["kind"] == "missing_field"
    assert need1["target"] == "monthly_income"
    assert need1["label"] == "Monthly Income"  # From requirements
    assert need1["field_type"] == "money"


def test_context_document_need_label():
    """Document needs get label from DocumentRequirement."""
    now = datetime.now(UTC)

    requirements = ProductRequirements(
        product_code=Product.personal_loan,
        fields=[],
        documents=[
            DocumentRequirement(
                doc_type="payslip",
                label="Monthly Payslip"
            )
        ]
    )

    state = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.credit_application,
        application=ApplicationState(
            product_code=Product.personal_loan,
            requirements=requirements
        )
    )

    needs = [Need(kind=NeedKind.document, target="payslip")]

    context = build_context(state, needs, [], [])

    assert len(context["needs"]) == 1
    need = context["needs"][0]
    assert need["kind"] == "document"
    assert need["target"] == "payslip"
    assert need["label"] == "Monthly Payslip"
    assert need["field_type"] is None


def test_context_fields_serialized_as_strings():
    """Money values in fields are serialized as plain decimal strings."""
    now = datetime.now(UTC)

    state = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.credit_application,
        application=ApplicationState(
            product_code=Product.personal_loan,
            fields={
                "amount": FieldValue(
                    kind="money",
                    value=Decimal("30000.00"),
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                ),
                "term_months": FieldValue(
                    kind="integer",
                    value=60,
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                )
            }
        )
    )

    context = build_context(state, [], [], [])

    assert "fields" in context
    fields = context["fields"]

    # amount should be string
    assert "amount" in fields
    assert fields["amount"]["value"] == "30000.00"
    assert isinstance(fields["amount"]["value"], str)

    # term_months should be int (not string, based on kind)
    assert "term_months" in fields
    assert fields["term_months"]["value"] == 60
    assert isinstance(fields["term_months"]["value"], int)


def test_context_offers_serialized():
    """Offers have monthly_installment and total_cost as decimal strings."""
    now = datetime.now(UTC)

    offers = [
        LoanOffer(
            offer_id="off1",
            product_code=Product.personal_loan,
            amount=Money(amount=Decimal("30000.00")),
            term_months=60,
            annual_interest_rate_percent=Decimal("9.5"),
            monthly_installment=Money(amount=Decimal("628.50")),
            total_repayment=Money(amount=Decimal("37710.00")),
            total_cost=Money(amount=Decimal("7710.00")),
            fees=Money(amount=Decimal("0.00")),
            assumptions=["Assumes good credit"]
        )
    ]

    state = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.credit_application,
        application=ApplicationState(
            product_code=Product.personal_loan,
            offers=OffersRecord(
                offers=offers,
                input_fingerprint="abc123"
            )
        )
    )

    context = build_context(state, [], [], [])

    assert "offers" in context
    assert len(context["offers"]) == 1

    offer = context["offers"][0]
    assert offer["offer_id"] == "off1"
    assert offer["term_months"] == 60
    assert offer["monthly_installment"] == "628.50"
    assert isinstance(offer["monthly_installment"], str)
    assert offer["total_cost"] == "7710.00"
    assert isinstance(offer["total_cost"], str)


def test_context_stage_from_derive_stage():
    """Context stage is computed from derive_stage or null."""
    now = datetime.now(UTC)

    # State with no application
    state_no_app = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.product_info
    )

    context = build_context(state_no_app, [], [], [])
    assert context["stage"] is None

    # State with application
    state_with_app = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.credit_application,
        application=ApplicationState(
            product_code=None
        )
    )

    context = build_context(state_with_app, [], [], [])
    stage = derive_stage(state_with_app)
    assert context["stage"] == stage


def test_context_conflicts_and_eligibility():
    """Context includes conflicts and eligibility."""
    now = datetime.now(UTC)

    eligibility_result = EligibilityResult(
        status=EligibilityStatus.satisfied,
        reasons=[ReasonItem(code="INCOME_OK", message="Income sufficient")],
        rule_version="v1"
    )

    state = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.credit_application,
        application=ApplicationState(
            product_code=Product.personal_loan,
            conflicts=[
                FieldConflict(
                    field="amount",
                    customer_value="30000",
                    document_value="35000",
                    document_id="doc1"
                )
            ],
            eligibility=EligibilityRecord(
                result=eligibility_result,
                input_fingerprint="fp1",
                verified_inputs=True
            )
        )
    )

    context = build_context(state, [], [], [])

    # Check conflicts
    assert "conflicts" in context
    assert len(context["conflicts"]) == 1
    assert context["conflicts"][0]["field"] == "amount"

    # Check eligibility
    assert "eligibility" in context
    assert context["eligibility"]["status"] == "satisfied"
    assert "reasons" in context["eligibility"]


def test_context_notices_passthrough():
    """Notices are passed through verbatim as list of strings."""
    now = datetime.now(UTC)
    state = SessionState(
        session_id="s1",
        customer_id="c1",
        created_at=now,
        updated_at=now,
        language="ro",
        active_flow=Flow.product_info
    )

    notices = ["Field update rejected: invalid amount", "Tool unavailable"]
    context = build_context(state, [], [], notices)

    assert "notices" in context
    assert context["notices"] == notices
