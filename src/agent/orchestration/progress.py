"""Progress calculation and stage derivation for orchestrator sessions."""
import hashlib
from enum import StrEnum
from typing import Iterable

from pydantic import BaseModel

from src.agent.orchestration.fields import DISCOVERY_FIELDS
from src.agent.orchestration.state import (
    ApplicationState,
    SessionState,
    DocumentStatus,
    FieldSource,
)
from src.models.credit import EligibilityStatus, FieldSpec


class Stage(StrEnum):
    """Application stage."""
    discovery = "discovery"
    collecting_information = "collecting_information"
    eligibility = "eligibility"
    documents = "documents"
    offer_selection = "offer_selection"
    awaiting_confirmation = "awaiting_confirmation"
    submitted = "submitted"
    not_eligible = "not_eligible"
    manual_review = "manual_review"
    escalated = "escalated"


# Main stages in order (for progress display)
MAIN_STAGES = [
    Stage.discovery,
    Stage.collecting_information,
    Stage.eligibility,
    Stage.documents,
    Stage.offer_selection,
    Stage.awaiting_confirmation,
    Stage.submitted,
]


class NeedKind(StrEnum):
    """Kind of need blocking progress."""
    missing_field = "missing_field"
    choose_product = "choose_product"
    run_eligibility = "run_eligibility"
    document = "document"
    confirm_extracted = "confirm_extracted"
    resolve_conflict = "resolve_conflict"
    run_offers = "run_offers"
    choose_offer = "choose_offer"
    confirm_submission = "confirm_submission"
    not_eligible = "not_eligible"
    manual_review = "manual_review"
    escalated = "escalated"


class Need(BaseModel):
    """A need blocking progress."""
    kind: NeedKind
    target: str | None = None
    detail: str | None = None


def fingerprint(app: ApplicationState, names: Iterable[str]) -> str:
    """Compute fingerprint of fields and product.

    Args:
        app: Application state
        names: Field names to include in fingerprint

    Returns:
        SHA256 hex digest (first 16 chars)
    """
    items = []

    # Include each field
    for name in sorted(names):
        if name in app.fields:
            field = app.fields[name]
            items.append((name, str(field.value), field.source.value, field.confirmed))
        else:
            items.append((name, None, None, None))

    # Include product code
    items.append(("product_code", str(app.product_code) if app.product_code else None, None, None))

    # Hash it
    h = hashlib.sha256()
    h.update(repr(items).encode('utf-8'))
    return h.hexdigest()[:16]


def eligibility_input_names(app: ApplicationState) -> list[str]:
    """Return list of field names required for eligibility.

    Args:
        app: Application state

    Returns:
        List of required field names from requirements
    """
    if app.requirements is None:
        return []

    return [spec.name for spec in app.requirements.fields if spec.required]


def offer_input_names(app: ApplicationState) -> list[str]:
    """Return list of field names required for offers.

    Args:
        app: Application state

    Returns:
        List containing 'amount', 'term_months' plus eligibility inputs
    """
    names = ["amount", "term_months"]
    names.extend(eligibility_input_names(app))
    return names


def is_verified(app: ApplicationState, spec: FieldSpec) -> bool:
    """Check if a field is verified according to its spec.

    A field is verified if:
    - It doesn't require verification (must_verify = False), OR
    - It is document-sourced, confirmed, and its document is accepted, OR
    - It is an identity field sourced from profile

    Args:
        app: Application state
        spec: Field specification

    Returns:
        True if field is verified
    """
    # Field must exist
    if spec.name not in app.fields:
        return False

    field = app.fields[spec.name]

    # If doesn't require verification, just needs to exist
    if not spec.must_verify:
        return True

    # Identity fields from profile count as verified
    if spec.identity and field.source == FieldSource.profile:
        return True

    # Must be document-sourced and confirmed
    if field.source != FieldSource.document or not field.confirmed:
        return False

    # Document must be accepted
    if field.document_id is None:
        return False

    doc = next((d for d in app.documents if d.document_id == field.document_id), None)
    if doc is None or doc.status != DocumentStatus.accepted or doc.human_review_required:
        return False

    return True


def all_verified(app: ApplicationState) -> bool:
    """Check if all required fields are verified.

    Args:
        app: Application state

    Returns:
        True if all required fields are verified
    """
    if app.requirements is None:
        return False

    if documents_require_review(app):
        return False
    if app.document_verification is not None and not app.document_verification_complete:
        return False

    for spec in app.requirements.fields:
        if spec.required and not is_verified(app, spec):
            return False

    return True


def documents_require_review(app: ApplicationState) -> bool:
    return any(doc.human_review_required for doc in app.documents) or bool(
        app.document_verification and app.document_verification.human_review_required
    )


def eligibility_current(app: ApplicationState) -> bool:
    """Check if eligibility result is current (fingerprint matches).

    Args:
        app: Application state

    Returns:
        True if eligibility exists and its fingerprint matches current fields
    """
    if app.eligibility is None:
        return False

    input_names = eligibility_input_names(app)
    current_fp = fingerprint(app, input_names)

    return app.eligibility.input_fingerprint == current_fp


def offers_current(app: ApplicationState) -> bool:
    """Check if offers are current (fingerprint matches).

    Args:
        app: Application state

    Returns:
        True if offers exist and their fingerprint matches current fields
    """
    if app.offers is None:
        return False

    input_names = offer_input_names(app)
    current_fp = fingerprint(app, input_names)

    return app.offers.input_fingerprint == current_fp


def next_needs(state: SessionState) -> list[Need]:
    """Compute ordered list of needs blocking progress.

    Args:
        state: Session state

    Returns:
        Ordered list of needs (empty if no application)
    """
    if state.application is None:
        return []

    app = state.application
    needs: list[Need] = []

    # Group 1: Escalation (not submitted)
    if state.escalation is not None and app.application_id is None:
        needs.append(Need(kind=NeedKind.escalated))
        return needs  # Stop here per brief

    if documents_require_review(app) and app.application_id is None:
        reasons = app.document_verification.reasons if app.document_verification else []
        return [Need(kind=NeedKind.manual_review, detail="; ".join(reasons) or "Document evidence requires human verification.")]

    # Group 2: Missing discovery fields
    for spec in DISCOVERY_FIELDS:
        if spec.name not in app.fields:
            needs.append(Need(kind=NeedKind.missing_field, target=spec.name))

    # Group 3: No product_code
    if app.product_code is None:
        needs.append(Need(kind=NeedKind.choose_product))

    # If no requirements, return what we have (discovery + choose_product)
    if app.requirements is None:
        return needs

    # Group 4: Missing required fields
    for spec in app.requirements.fields:
        if spec.required and spec.name not in app.fields:
            needs.append(Need(kind=NeedKind.missing_field, target=spec.name))

    # Group 5: Eligibility not current
    if not eligibility_current(app):
        needs.append(Need(kind=NeedKind.run_eligibility))

    # Group 6: Eligibility results
    if app.eligibility is not None:
        status = app.eligibility.result.status

        if status == EligibilityStatus.not_satisfied:
            needs.append(Need(kind=NeedKind.not_eligible))
            return needs  # Stop after not_eligible

        if status == EligibilityStatus.manual_review:
            needs.append(Need(kind=NeedKind.manual_review))
            return needs  # Stop after manual_review

        if status == EligibilityStatus.more_information_required:
            # Add missing_field for each missing field
            for field_name in app.eligibility.result.missing_fields:
                needs.append(Need(kind=NeedKind.missing_field, target=field_name))

    # Group 7: Required documents not accepted
    if app.requirements.documents:
        for doc_req in app.requirements.documents:
            # Find latest document of this type
            docs_of_type = [d for d in app.documents if d.doc_type == doc_req.doc_type]

            if not docs_of_type:
                # No document uploaded
                needs.append(Need(kind=NeedKind.document, target=doc_req.doc_type))
            else:
                latest = max(docs_of_type, key=lambda d: d.uploaded_at)
                if latest.status == DocumentStatus.rejected:
                    # Rejected with reason
                    needs.append(Need(
                        kind=NeedKind.document,
                        target=doc_req.doc_type,
                        detail=latest.rejection_reason
                    ))
                elif latest.status != DocumentStatus.accepted:
                    # Not accepted yet
                    needs.append(Need(kind=NeedKind.document, target=doc_req.doc_type))

    # Group 8: Unconfirmed document-sourced fields (no open conflict)
    conflicted_fields = {c.field for c in app.conflicts}
    for field_name, field in app.fields.items():
        if (field.source == FieldSource.document
                and not field.confirmed
                and field_name not in conflicted_fields):
            needs.append(Need(kind=NeedKind.confirm_extracted, target=field_name))

    # Group 9: Open conflicts
    for conflict in app.conflicts:
        needs.append(Need(kind=NeedKind.resolve_conflict, target=conflict.field))

    # If any needs from groups 2-9 exist, return them (don't add groups 10-13)
    if needs:
        return needs

    # Groups 10-13: Only when no group 2-9 needs exist

    # Group 10: Eligibility current but not verified
    if app.eligibility is not None and not app.eligibility.verified_inputs:
        needs.append(Need(kind=NeedKind.run_eligibility))
        return needs

    # Group 11: Offers not current
    if not offers_current(app):
        needs.append(Need(kind=NeedKind.run_offers))
        return needs

    # Group 12: No selected offer
    if app.selected_offer_id is None:
        needs.append(Need(kind=NeedKind.choose_offer))
        return needs

    # Group 13: Not submitted
    if app.application_id is None:
        needs.append(Need(kind=NeedKind.confirm_submission))
        return needs

    # All done
    return needs


def derive_stage(state: SessionState) -> Stage | None:
    """Derive the current stage from session state.

    Args:
        state: Session state

    Returns:
        Current stage, or None if no application
    """
    if state.application is None:
        return None

    app = state.application

    # Submitted
    if app.application_id is not None:
        return Stage.submitted

    # Escalated (not submitted)
    if state.escalation is not None:
        return Stage.escalated

    # Get first need to determine stage
    needs = next_needs(state)
    if not needs:
        # Should not happen (submitted would have been caught above)
        return Stage.awaiting_confirmation

    first_need = needs[0]

    # Map need to stage
    if first_need.kind == NeedKind.escalated:
        return Stage.escalated

    if first_need.kind == NeedKind.missing_field:
        # Check if we have product or not
        if app.product_code is None:
            return Stage.discovery
        else:
            return Stage.collecting_information

    if first_need.kind == NeedKind.choose_product:
        return Stage.discovery

    if first_need.kind == NeedKind.run_eligibility:
        return Stage.eligibility

    if first_need.kind == NeedKind.not_eligible:
        return Stage.not_eligible

    if first_need.kind == NeedKind.manual_review:
        return Stage.manual_review

    if first_need.kind in (NeedKind.document, NeedKind.confirm_extracted, NeedKind.resolve_conflict):
        return Stage.documents

    if first_need.kind in (NeedKind.run_offers, NeedKind.choose_offer):
        return Stage.offer_selection

    if first_need.kind == NeedKind.confirm_submission:
        return Stage.awaiting_confirmation

    # Default
    return Stage.discovery


def can_run_eligibility(state: SessionState) -> str | None:
    """Check if eligibility can be run.

    Args:
        state: Session state

    Returns:
        None if allowed, or a reason string if blocked
    """
    if state.application is None:
        return "no application"

    app = state.application

    if app.requirements is None:
        return "no product requirements"

    if documents_require_review(app):
        return "document evidence requires human review"

    # Check all required fields are present
    missing = []
    for spec in app.requirements.fields:
        if spec.required and spec.name not in app.fields:
            missing.append(spec.name)

    if missing:
        return f"missing required fields: {', '.join(missing)}"

    return None


def can_calculate_offers(state: SessionState) -> str | None:
    """Check if offers can be calculated.

    Args:
        state: Session state

    Returns:
        None if allowed, or a reason string if blocked
    """
    if state.application is None:
        return "no application"

    app = state.application

    # Must have current eligibility
    # Reasons are shown to the model (TOOL_REJECTED); name the tool that unblocks it.
    if not eligibility_current(app):
        return "eligibility not current; call run_eligibility_check first"

    if app.eligibility is None:
        return "no eligibility result"

    # Must be satisfied
    if app.eligibility.result.status != EligibilityStatus.satisfied:
        return f"eligibility status is {app.eligibility.result.status}"

    # Must have verified inputs
    if not app.eligibility.verified_inputs:
        return "eligibility not run with verified inputs; call run_eligibility_check first"

    if documents_require_review(app):
        return "document evidence requires human review"
    if not all_verified(app):
        return "document evidence is not fully verified and confirmed"
    if app.requirements and any(
        not any(doc.doc_type == req.doc_type and doc.status == DocumentStatus.accepted for doc in app.documents)
        for req in app.requirements.documents
    ):
        return "required documents are not accepted"

    return None
