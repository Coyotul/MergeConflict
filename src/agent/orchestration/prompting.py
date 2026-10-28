"""Prompt and context builder for the orchestrator."""
import json
from pathlib import Path
from typing import Any

from src.agent.orchestration.fields import DISCOVERY_FIELDS
from src.agent.orchestration.progress import Need, NeedKind, derive_stage
from src.agent.orchestration.state import SessionState, StoredMessage
from src.agent.tools.registry import ToolSpec
from src.integrations.llm.chat import ChatMessage
from src.models.credit import DocumentRequirement, FieldSpec, FieldType


PROMPT_VERSION = "orchestrator-v1"


def load_system_prompt() -> str:
    """Load the system prompt from the markdown file.

    Returns:
        System prompt text
    """
    # Get path to orchestrator_system.md relative to this module
    prompts_dir = Path(__file__).parent.parent / "prompts"
    prompt_file = prompts_dir / "orchestrator_system.md"

    if not prompt_file.exists():
        raise FileNotFoundError(f"System prompt not found: {prompt_file}")

    return prompt_file.read_text(encoding="utf-8")


def build_context(
    state: SessionState,
    needs: list[Need],
    tools: list[ToolSpec],
    notices: list[str],
    *,
    catalog_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Build the context dictionary for CONTEXT_JSON.

    Args:
        state: Session state
        needs: Ordered list of needs
        tools: Available tool specs
        notices: System notices
        catalog_codes: Product codes offered as options for choose_product

    Returns:
        Context dictionary with all required keys
    """
    context: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "language": state.language,
        "flow": state.active_flow,
        "stage": derive_stage(state) if state.application is not None else None,
        "needs": _serialize_needs(state, needs, catalog_codes),
        "fields": {},
        "conflicts": [],
        "documents": [],
        "eligibility": None,
        "offers": [],
        "selected_offer_id": None,
        "retrieved_citation_ids": list(state.retrieved_sources.keys()),
        "tools": [_serialize_tool(tool) for tool in tools],
        "notices": notices
    }

    # Add application-specific data
    if state.application is not None:
        app = state.application

        # Fields
        context["fields"] = {
            name: {
                "value": _serialize_field_value(field.value, field.kind),
                "source": field.source,
                "confirmed": field.confirmed
            }
            for name, field in app.fields.items()
        }

        # Conflicts
        context["conflicts"] = [
            {
                "field": c.field,
                "customer_value": c.customer_value,
                "document_value": c.document_value
            }
            for c in app.conflicts
        ]

        # Documents (only doc_type, status, rejection_reason - no filenames or IDs)
        context["documents"] = [
            {
                "doc_type": doc.doc_type,
                "status": doc.status,
                "rejection_reason": doc.rejection_reason
            }
            for doc in app.documents
        ]

        # Eligibility
        if app.eligibility is not None:
            context["eligibility"] = {
                "status": app.eligibility.result.status,
                "reasons": [
                    {"code": r.code, "message": r.message}
                    for r in app.eligibility.result.reasons
                ]
            }

        # Offers
        if app.offers is not None:
            context["offers"] = [
                {
                    "offer_id": offer.offer_id,
                    "term_months": offer.term_months,
                    "monthly_installment": str(offer.monthly_installment.amount),
                    "total_cost": str(offer.total_cost.amount)
                }
                for offer in app.offers.offers
            ]

        # Selected offer
        context["selected_offer_id"] = app.selected_offer_id

    return context


def build_messages(
    state: SessionState,
    needs: list[Need],
    tools: list[ToolSpec],
    history: list[StoredMessage],
    window: int,
    notices: list[str],
    *,
    catalog_codes: list[str] | None = None,
) -> list[ChatMessage]:
    """Build the complete message list for the LLM.

    Args:
        state: Session state
        needs: Ordered list of needs
        tools: Available tool specs
        history: Full message history
        window: Number of recent messages to include
        notices: System notices
        catalog_codes: Product codes offered as options for choose_product

    Returns:
        List of ChatMessage with system prompt, windowed history, and context JSON
    """
    messages = []

    # 1. System prompt
    system_prompt = load_system_prompt()
    messages.append(ChatMessage(role="system", content=system_prompt))

    # 2. Windowed history (last N messages)
    windowed_history = history[-window:] if len(history) > window else history

    for msg in windowed_history:
        chat_msg = _map_stored_to_chat(msg)
        messages.append(chat_msg)

    # 3. Context JSON as final system message
    context = build_context(state, needs, tools, notices, catalog_codes=catalog_codes)
    context_json = json.dumps(context, indent=2)
    context_message = ChatMessage(
        role="system",
        content=f"CONTEXT_JSON:\n{context_json}"
    )
    messages.append(context_message)

    return messages


def _serialize_needs(
    state: SessionState, needs: list[Need], catalog_codes: list[str] | None = None
) -> list[dict[str, Any]]:
    """Serialize needs with labels, field_types and options from specs.

    options: the enum FieldSpec's options, the catalog codes for choose_product,
    else None.

    Args:
        state: Session state (to get requirements)
        needs: List of needs

    Returns:
        List of serialized needs with kind, target, detail, label, field_type, options
    """
    # Build combined spec dict
    specs_dict: dict[str, FieldSpec] = {spec.name: spec for spec in DISCOVERY_FIELDS}

    # Add requirements fields if available
    if state.application is not None and state.application.requirements is not None:
        for spec in state.application.requirements.fields:
            specs_dict[spec.name] = spec

    # Build document requirements dict
    doc_reqs_dict: dict[str, DocumentRequirement] = {}
    if state.application is not None and state.application.requirements is not None:
        for doc_req in state.application.requirements.documents:
            doc_reqs_dict[doc_req.doc_type] = doc_req

    serialized = []
    for need in needs:
        need_dict: dict[str, Any] = {
            "kind": need.kind,
            "target": need.target,
            "detail": need.detail,
            "options": None,
        }

        # Determine label and field_type
        if need.target is not None:
            if need.kind == NeedKind.document:
                # Document need - get label from DocumentRequirement
                if need.target in doc_reqs_dict:
                    need_dict["label"] = doc_reqs_dict[need.target].label
                else:
                    need_dict["label"] = need.kind.value
                need_dict["field_type"] = None
            elif need.target in specs_dict:
                # Field need - get label and type from FieldSpec
                spec = specs_dict[need.target]
                need_dict["label"] = spec.label
                need_dict["field_type"] = spec.type.value
                if spec.type == FieldType.enum and spec.options:
                    need_dict["options"] = list(spec.options)
            else:
                # Fallback
                need_dict["label"] = need.kind.value
                need_dict["field_type"] = None
        else:
            # No target - use kind as label
            need_dict["label"] = need.kind.value
            need_dict["field_type"] = None
            if need.kind == NeedKind.choose_product and catalog_codes:
                need_dict["options"] = list(catalog_codes)

        serialized.append(need_dict)

    return serialized


def _serialize_field_value(value: Any, kind: str) -> Any:
    """Serialize a field value according to its kind.

    Args:
        value: The field value
        kind: The field kind (money, integer, text, boolean)

    Returns:
        Serialized value (string for money, appropriate type for others)
    """
    if kind == "money":
        # Serialize Decimal as string
        return str(value)
    elif kind == "integer":
        return int(value)
    elif kind == "text":
        return str(value)
    elif kind == "boolean":
        return bool(value)
    else:
        # Fallback
        return str(value)


def _serialize_tool(tool: ToolSpec) -> dict[str, Any]:
    """Serialize a tool spec for the context.

    Args:
        tool: Tool specification

    Returns:
        Dict with name, description, input_schema
    """
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_model.model_json_schema()
    }


def _map_stored_to_chat(msg: StoredMessage) -> ChatMessage:
    """Map a StoredMessage to a ChatMessage with role translation.

    Args:
        msg: Stored message from conversation history

    Returns:
        ChatMessage with mapped role
    """
    # Role mapping:
    # customer -> user
    # assistant -> assistant
    # action -> assistant (raw JSON from model)
    # tool -> user (tool result goes back as user message)
    # event -> user (with EVENT: prefix)

    if msg.role == "customer":
        return ChatMessage(role="user", content=msg.content)
    elif msg.role == "assistant":
        return ChatMessage(role="assistant", content=msg.content)
    elif msg.role == "action":
        return ChatMessage(role="assistant", content=msg.content)
    elif msg.role == "tool":
        return ChatMessage(role="user", content=msg.content)
    elif msg.role == "event":
        return ChatMessage(role="user", content=f"EVENT: {msg.content}")
    else:
        # Fallback
        return ChatMessage(role="user", content=msg.content)
