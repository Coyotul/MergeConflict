"""Build the TurnResponse (awaiting, progress, blocks) purely from session state."""
import hashlib
import json

from src.agent.orchestration.fields import DISCOVERY_FIELDS
from src.agent.orchestration.progress import (
    MAIN_STAGES,
    NeedKind,
    Stage,
    derive_stage,
    next_needs,
)
from src.agent.orchestration.state import (
    ApplicationState,
    DocumentStatus,
    FieldSource,
    SessionState,
    StoredMessage,
)
from src.models.chat import (
    ApplicationSubmittedBlock,
    ApplicationSummary,
    ApplicationSummaryBlock,
    Awaiting,
    AwaitingKind,
    Block,
    ChatMessageView,
    DocumentChecklistBlock,
    DocumentChecklistItem,
    EligibilityResultBlock,
    EscalationBlock,
    ExtractedFieldView,
    ExtractedFieldsBlock,
    OffersBlock,
    Progress,
    ProgressStep,
    SummaryField,
    TurnResponse,
)
from src.models.credit import FieldSpec, LoanOffer

SUBMITTED_STATUS = "PENDING_HUMAN_REVIEW"

ESCALATION_MESSAGE = {
    "en": "A human advisor will review your case and contact you.",
    "ro": "Un consultant va analiza cazul tău și te va contacta.",
}

# Main stage a side stage branches from (it takes that slot in progress.steps).
_SIDE_STAGE_BRANCH = {
    Stage.not_eligible: Stage.eligibility,
    Stage.manual_review: Stage.eligibility,
}


def build_turn_response(
    state: SessionState, new_messages: list[StoredMessage], turn_id: str
) -> TurnResponse:
    """Build the response for a turn. Only assistant messages are returned."""
    return TurnResponse(
        session_id=state.session_id,
        turn_id=turn_id,
        session_version=state.version,
        messages=[
            ChatMessageView(role="assistant", text=m.content, citations=m.citations, created_at=m.created_at)
            for m in new_messages
            if m.role == "assistant"
        ],
        awaiting=build_awaiting(state),
        progress=build_progress(state),
        blocks=build_blocks(state),
        simulated=state.used_stubs,
    )


def all_specs(app: ApplicationState) -> dict[str, FieldSpec]:
    """Discovery specs plus the product's requirement specs, by name."""
    specs = {spec.name: spec for spec in DISCOVERY_FIELDS}
    if app.requirements is not None:
        specs.update({spec.name: spec for spec in app.requirements.fields})
    return specs


def document_checklist(app: ApplicationState) -> list[DocumentChecklistItem]:
    """One item per required document with the status of its latest record."""
    if app.requirements is None:
        return []
    items = []
    for req in app.requirements.documents:
        records = [d for d in app.documents if d.doc_type == req.doc_type]
        if records:
            latest = max(records, key=lambda d: d.uploaded_at)
            status, reason = latest.status.value, latest.rejection_reason
        else:
            status, reason = DocumentStatus.requested.value, None
        items.append(DocumentChecklistItem(
            doc_type=req.doc_type, label=req.label, status=status, rejection_reason=reason
        ))
    return items


def build_awaiting(state: SessionState) -> Awaiting:
    app = state.application
    if app is not None and app.application_id is not None:
        return Awaiting(kind=AwaitingKind.none)
    needs = next_needs(state)
    if not needs:
        return Awaiting(kind=AwaitingKind.text)
    first = needs[0]
    if first.kind == NeedKind.document:
        types: list[str] = []
        for need in needs:
            if need.kind == NeedKind.document and need.target and need.target not in types:
                types.append(need.target)
        return Awaiting(kind=AwaitingKind.document, document_types=types)
    if first.kind == NeedKind.choose_offer:
        return Awaiting(kind=AwaitingKind.offer_choice)
    if first.kind == NeedKind.confirm_submission:
        version = app.summary.summary_version if app.summary is not None else None
        return Awaiting(kind=AwaitingKind.confirmation, summary_version=version)
    return Awaiting(kind=AwaitingKind.text)


def build_progress(state: SessionState) -> Progress:
    stage = derive_stage(state)
    if stage is None:
        return Progress(flow=state.active_flow.value, stage=None, steps=[])

    if stage in MAIN_STAGES:
        slot, shown = MAIN_STAGES.index(stage), stage
    else:
        branch = _SIDE_STAGE_BRANCH.get(stage)
        if branch is None:
            # escalated: it takes the slot of the stage the application was in
            underlying = derive_stage(state.model_copy(update={"escalation": None}))
            branch = underlying if underlying in MAIN_STAGES else Stage.discovery
        slot, shown = MAIN_STAGES.index(branch), stage

    steps = []
    for i, main in enumerate(MAIN_STAGES):
        if i < slot:
            steps.append(ProgressStep(stage=main.value, status="done"))
        elif i == slot:
            steps.append(ProgressStep(stage=shown.value, status="current"))
        else:
            steps.append(ProgressStep(stage=main.value, status="todo"))
    return Progress(flow=state.active_flow.value, stage=stage.value, steps=steps)


def build_blocks(state: SessionState) -> list[Block]:
    blocks: list[Block] = []
    app = state.application
    if app is not None:
        if app.requirements is not None:
            blocks.append(DocumentChecklistBlock(items=document_checklist(app)))

        extracted = _extracted_fields(app)
        if extracted:
            blocks.append(ExtractedFieldsBlock(fields=extracted))

        if app.eligibility is not None:
            blocks.append(EligibilityResultBlock(result=app.eligibility.result))

        if app.offers is not None:
            blocks.append(OffersBlock(offers=app.offers.offers, selected_offer_id=app.selected_offer_id))

        if app.summary is not None and derive_stage(state) == Stage.awaiting_confirmation:
            blocks.append(ApplicationSummaryBlock(summary=app.summary))

        if app.application_id is not None:
            blocks.append(ApplicationSubmittedBlock(application_id=app.application_id, status=SUBMITTED_STATUS))

    if state.escalation is not None:
        blocks.append(EscalationBlock(
            ticket_id=state.escalation.ticket_id,
            message=ESCALATION_MESSAGE[state.language],
        ))
    return blocks


def build_summary(
    app: ApplicationState, offer: LoanOffer, product_name: str, application_id: str
) -> ApplicationSummary:
    """Build the application summary for the selected offer.

    summary_version is sha256[:16] of the summary's canonical JSON without
    summary_version, so it changes whenever the shown content changes.
    """
    specs = all_specs(app)
    fields = [
        SummaryField(label=spec.label, value=str(app.fields[name].value), source=app.fields[name].source.value)
        for name, spec in specs.items()
        if name in app.fields
    ]
    draft = ApplicationSummary(
        summary_version="",
        application_id=application_id,
        product_code=offer.product_code,
        product_name=product_name,
        amount=offer.amount,
        term_months=offer.term_months,
        offer=offer,
        fields=fields,
        documents=document_checklist(app),
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"summary_version"}), sort_keys=True, separators=(",", ":")
    )
    version = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return draft.model_copy(update={"summary_version": version})


def _extracted_fields(app: ApplicationState) -> list[ExtractedFieldView]:
    specs = all_specs(app)
    conflicts = {c.field: c for c in app.conflicts}
    views = []
    for name, value in app.fields.items():
        if value.source != FieldSource.document:
            continue
        document = next((doc for doc in app.documents if doc.document_id == value.document_id), None)
        if document is not None and (document.status != DocumentStatus.accepted or document.human_review_required):
            continue
        spec = specs.get(name)
        conflict = conflicts.get(name)
        views.append(ExtractedFieldView(
            field=name,
            label=spec.label if spec is not None else name,
            value=str(value.value),
            source=value.source.value,
            confidence=value.confidence,
            needs_confirmation=not value.confirmed,
            conflict_with=conflict.customer_value if conflict is not None else None,
        ))
    return views
