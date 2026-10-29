"""Tests for progress calculation and stage derivation."""
from datetime import datetime, UTC
from decimal import Decimal

import pytest

from src.agent.orchestration.progress import (
    Stage,
    NeedKind,
    Need,
    fingerprint,
    eligibility_input_names,
    offer_input_names,
    is_verified,
    all_verified,
    eligibility_current,
    offers_current,
    next_needs,
    derive_stage,
    can_run_eligibility,
    can_calculate_offers,
)
from src.agent.orchestration.state import (
    ApplicationState,
    SessionState,
    Flow,
    FieldValue,
    FieldSource,
    DocumentRecord,
    DocumentStatus,
    ExtractedField,
    EligibilityRecord,
    OffersRecord,
    FieldConflict,
    EscalationRecord,
)
from src.models.credit import (
    EligibilityResult,
    EligibilityStatus,
    LoanOffer,
    Money,
    ProductRequirements,
    DocumentRequirement,
)
from src.models.knowledge import Product
from tests.unit.orchestrator.factories import make_specs, make_app


def make_session(app: ApplicationState | None = None, **overrides) -> SessionState:
    """Build a SessionState with reasonable defaults."""
    defaults = {
        "session_id": "sess_test",
        "customer_id": "cust_test",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "version": 0,
        "language": "ro",
        "active_flow": Flow.credit_application if app else Flow.none,
        "application": app,
        "retrieved_sources": {},
        "escalation": None,
        "used_stubs": False,
    }
    defaults.update(overrides)
    return SessionState(**defaults)


def add_field(app: ApplicationState, name: str, value: Decimal | int | str | bool,
              source: FieldSource = FieldSource.customer,
              confirmed: bool = True,
              document_id: str | None = None) -> None:
    """Add a field to the application."""
    # Determine kind from value type
    if isinstance(value, Decimal):
        kind = "money"
    elif isinstance(value, int) and not isinstance(value, bool):
        kind = "integer"
    elif isinstance(value, bool):
        kind = "boolean"
    else:
        kind = "text"

    app.fields[name] = FieldValue(
        kind=kind,
        value=value,
        source=source,
        document_id=document_id,
        confirmed=confirmed,
        updated_at=datetime.now(UTC)
    )


def add_document(app: ApplicationState, doc_type: str,
                 status: DocumentStatus = DocumentStatus.accepted,
                 rejection_reason: str | None = None) -> DocumentRecord:
    """Add a document to the application."""
    doc = DocumentRecord(
        document_id=f"doc_{len(app.documents)}",
        doc_type=doc_type,
        filename=f"{doc_type}.pdf",
        status=status,
        rejection_reason=rejection_reason,
        uploaded_at=datetime.now(UTC)
    )
    app.documents.append(doc)
    return doc


def test_empty_application_needs_discovery():
    """Empty application needs discovery fields plus choose_product."""
    app = make_app()
    state = make_session(app)

    needs = next_needs(state)

    # Full list: discovery fields + choose_product
    assert len(needs) == 4
    assert needs[0].kind == NeedKind.missing_field
    assert needs[0].target == "purpose"
    assert needs[1].kind == NeedKind.missing_field
    assert needs[1].target == "amount"
    assert needs[2].kind == NeedKind.missing_field
    assert needs[2].target == "term_months"
    assert needs[3].kind == NeedKind.choose_product

    # Stage is discovery (from first need)
    assert derive_stage(state) == Stage.discovery


def test_requirements_fields_after_product():
    """After product selection, stage moves to collecting_information."""
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[make_specs()["monthly_net_income"], make_specs()["employer_name"]],
            documents=[]
        )
    )

    # Fill discovery fields
    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)

    state = make_session(app)
    needs = next_needs(state)

    # Should need requirement fields
    assert needs[0].kind == NeedKind.missing_field
    assert needs[0].target == "monthly_net_income"
    assert needs[1].kind == NeedKind.missing_field
    assert needs[1].target == "employer_name"

    # Stage is collecting_information
    assert derive_stage(state) == Stage.collecting_information


def test_eligibility_needed_when_fields_complete():
    """When all required fields present, need eligibility check."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"], specs["employer_name"], specs["dependents"]],
            documents=[]
        )
    )

    # Fill all required fields
    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    add_field(app, "monthly_net_income", Decimal("5000"))
    add_field(app, "employer_name", "Acme Corp")
    add_field(app, "dependents", 2)

    state = make_session(app)
    needs = next_needs(state)

    # First need is run_eligibility
    assert needs[0].kind == NeedKind.run_eligibility

    # Can run eligibility
    assert can_run_eligibility(state) is None

    # Stage is eligibility
    assert derive_stage(state) == Stage.eligibility


def test_can_run_eligibility_blocked_with_missing_fields():
    """can_run_eligibility returns reason when fields missing."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"], specs["employer_name"]],
            documents=[]
        )
    )

    # Only fill one field
    add_field(app, "monthly_net_income", Decimal("5000"))

    state = make_session(app)

    reason = can_run_eligibility(state)
    assert reason is not None
    assert "employer_name" in reason


def test_not_satisfied_stage():
    """When eligibility is not_satisfied, stage is not_eligible."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"]],
            documents=[]
        )
    )

    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    add_field(app, "monthly_net_income", Decimal("5000"))

    # Add not_satisfied eligibility
    fp = fingerprint(app, ["monthly_net_income"])
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(
            status=EligibilityStatus.not_satisfied,
            reasons=[],
            rule_version="v1"
        ),
        input_fingerprint=fp,
        verified_inputs=True
    )

    state = make_session(app)
    needs = next_needs(state)

    # First need is not_eligible
    assert needs[0].kind == NeedKind.not_eligible

    # Stage is not_eligible
    assert derive_stage(state) == Stage.not_eligible


def test_documents_stage_lists_rejected_with_reason():
    """Rejected documents appear in needs with rejection reason."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"]],
            documents=[DocumentRequirement(doc_type="payslip", label="Payslip")]
        )
    )

    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    add_field(app, "monthly_net_income", Decimal("5000"))

    # Eligibility satisfied
    fp = fingerprint(app, ["monthly_net_income"])
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(
            status=EligibilityStatus.satisfied,
            reasons=[],
            rule_version="v1"
        ),
        input_fingerprint=fp,
        verified_inputs=True
    )

    # Add rejected document
    add_document(app, "payslip", status=DocumentStatus.rejected,
                 rejection_reason="Document not legible")

    state = make_session(app)
    needs = next_needs(state)

    # Need document with rejection detail
    doc_need = next((n for n in needs if n.kind == NeedKind.document), None)
    assert doc_need is not None
    assert doc_need.target == "payslip"
    assert doc_need.detail == "Document not legible"

    # Stage is documents
    assert derive_stage(state) == Stage.documents


def test_eligibility_stale_after_field_change():
    """Changing a field makes eligibility stale."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"]],
            documents=[]
        )
    )

    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    add_field(app, "monthly_net_income", Decimal("5000"))

    # Add eligibility
    fp = fingerprint(app, ["monthly_net_income"])
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(
            status=EligibilityStatus.satisfied,
            reasons=[],
            rule_version="v1"
        ),
        input_fingerprint=fp,
        verified_inputs=True
    )

    # Eligibility is current
    assert eligibility_current(app) is True

    # Change income
    add_field(app, "monthly_net_income", Decimal("6000"))

    # Now stale
    assert eligibility_current(app) is False

    state = make_session(app)
    needs = next_needs(state)

    # Need to re-run eligibility
    assert needs[0].kind == NeedKind.run_eligibility


def test_verified_rerun_required_before_offers():
    """When verified_inputs is False, must re-run eligibility before offers."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"]],
            documents=[]
        )
    )

    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    add_field(app, "monthly_net_income", Decimal("5000"))

    # Eligibility current but not verified
    fp = fingerprint(app, ["monthly_net_income"])
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(
            status=EligibilityStatus.satisfied,
            reasons=[],
            rule_version="v1"
        ),
        input_fingerprint=fp,
        verified_inputs=False
    )

    state = make_session(app)
    needs = next_needs(state)

    # Need run_eligibility (group 10)
    assert needs[0].kind == NeedKind.run_eligibility

    # can_calculate_offers is blocked by the unverified evidence; re-running eligibility
    # cannot unblock it, so the reason must not tell the model to do that.
    reason = can_calculate_offers(state)
    assert reason == "document evidence is not fully verified and confirmed"


def test_stale_eligibility_rejection_names_the_tool_to_call():
    """A changed input makes eligibility stale; the rejection must say to re-run it."""
    specs = make_specs()
    app = make_app(product_code=Product.personal_loan, requirements=ProductRequirements(
        product_code=Product.personal_loan, fields=[specs["dependents"]], documents=[]))
    add_field(app, "dependents", 0)
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(status=EligibilityStatus.satisfied, reasons=[], rule_version="v1"),
        input_fingerprint="stale",
        verified_inputs=True,
    )
    reason = can_calculate_offers(make_session(app))
    assert reason == "eligibility not current; call run_eligibility_check first"


def test_stale_eligibility_without_runnable_inputs_gives_no_hint():
    """If the check itself cannot run (missing fields), pointing at it would loop."""
    specs = make_specs()
    app = make_app(product_code=Product.personal_loan, requirements=ProductRequirements(
        product_code=Product.personal_loan, fields=[specs["dependents"]], documents=[]))
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(status=EligibilityStatus.satisfied, reasons=[], rule_version="v1"),
        input_fingerprint="stale",
        verified_inputs=True,
    )
    assert can_calculate_offers(make_session(app)) == "eligibility not current"


def test_offer_then_confirmation_then_submitted():
    """Full flow: offers -> choose offer -> confirm -> submitted."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"]],
            documents=[]
        )
    )

    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    add_field(app, "monthly_net_income", Decimal("5000"))

    # Eligibility satisfied and verified
    fp_elig = fingerprint(app, ["monthly_net_income"])
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(
            status=EligibilityStatus.satisfied,
            reasons=[],
            rule_version="v1"
        ),
        input_fingerprint=fp_elig,
        verified_inputs=True
    )

    state = make_session(app)

    # Stage: offer_selection, need run_offers
    assert derive_stage(state) == Stage.offer_selection
    needs = next_needs(state)
    assert needs[0].kind == NeedKind.run_offers

    # Add offers
    fp_offers = fingerprint(app, ["monthly_net_income", "amount", "term_months"])
    app.offers = OffersRecord(
        offers=[
            LoanOffer(
                offer_id="offer_1",
                product_code=Product.personal_loan,
                amount=Money(amount=Decimal("50000")),
                term_months=48,
                annual_interest_rate_percent=Decimal("10.5"),
                monthly_installment=Money(amount=Decimal("1280")),
                total_repayment=Money(amount=Decimal("61440")),
                total_cost=Money(amount=Decimal("11440")),
                fees=Money(amount=Decimal("0")),
                assumptions=[]
            )
        ],
        input_fingerprint=fp_offers
    )

    # Stage: offer_selection, need choose_offer
    state = make_session(app)
    assert derive_stage(state) == Stage.offer_selection
    needs = next_needs(state)
    assert needs[0].kind == NeedKind.choose_offer

    # Select offer
    app.selected_offer_id = "offer_1"

    # Stage: awaiting_confirmation, need confirm_submission
    state = make_session(app)
    assert derive_stage(state) == Stage.awaiting_confirmation
    needs = next_needs(state)
    assert needs[0].kind == NeedKind.confirm_submission

    # Submit
    app.application_id = "APP123"
    app.submitted_at = datetime.now(UTC)

    # Stage: submitted, no needs
    state = make_session(app)
    assert derive_stage(state) == Stage.submitted
    needs = next_needs(state)
    assert needs == []


def test_escalation_overrides_stage():
    """Escalation sets stage to escalated."""
    app = make_app()
    add_field(app, "purpose", "debt consolidation")

    state = make_session(
        app,
        escalation=EscalationRecord(
            reason="Customer request",
            created_at=datetime.now(UTC)
        )
    )

    # Stage is escalated
    assert derive_stage(state) == Stage.escalated

    # Need is escalated
    needs = next_needs(state)
    assert needs[0].kind == NeedKind.escalated


def test_fingerprint_stable_and_sensitive():
    """Fingerprint is stable for same app, changes when values change."""
    app1 = make_app()
    add_field(app1, "income", Decimal("5000"))
    add_field(app1, "name", "John Doe")
    app1.product_code = Product.personal_loan

    fp1 = fingerprint(app1, ["income", "name"])

    # Same values -> same fingerprint
    app2 = make_app()
    add_field(app2, "income", Decimal("5000"))
    add_field(app2, "name", "John Doe")
    app2.product_code = Product.personal_loan

    fp2 = fingerprint(app2, ["income", "name"])
    assert fp1 == fp2

    # Change value -> different fingerprint
    add_field(app2, "income", Decimal("6000"))
    fp3 = fingerprint(app2, ["income", "name"])
    assert fp3 != fp1

    # Change product -> different fingerprint
    app2 = make_app()
    add_field(app2, "income", Decimal("5000"))
    add_field(app2, "name", "John Doe")
    app2.product_code = Product.mortgage_casa_ta
    fp4 = fingerprint(app2, ["income", "name"])
    assert fp4 != fp1


def test_no_application_returns_none():
    """State without application returns None for stage."""
    state = make_session(None)
    assert derive_stage(state) is None
    assert next_needs(state) == []


def test_manual_review_status():
    """Manual review status sets stage to manual_review."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"]],
            documents=[]
        )
    )

    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    add_field(app, "monthly_net_income", Decimal("5000"))

    # Manual review eligibility
    fp = fingerprint(app, ["monthly_net_income"])
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(
            status=EligibilityStatus.manual_review,
            reasons=[],
            rule_version="v1"
        ),
        input_fingerprint=fp,
        verified_inputs=True
    )

    state = make_session(app)

    # Stage is manual_review
    assert derive_stage(state) == Stage.manual_review

    # Need is manual_review
    needs = next_needs(state)
    assert needs[0].kind == NeedKind.manual_review


def test_more_information_required_status():
    """more_information_required creates missing_field needs."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"], specs["employer_name"]],
            documents=[]
        )
    )

    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    add_field(app, "monthly_net_income", Decimal("5000"))
    add_field(app, "employer_name", "Acme Corp")

    # Eligibility needs more information
    fp = fingerprint(app, ["monthly_net_income", "employer_name"])
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(
            status=EligibilityStatus.more_information_required,
            reasons=[],
            rule_version="v1",
            missing_fields=["employment_type", "dependents"]
        ),
        input_fingerprint=fp,
        verified_inputs=True
    )

    state = make_session(app)
    needs = next_needs(state)

    # Should have missing_field needs
    missing_needs = [n for n in needs if n.kind == NeedKind.missing_field]
    assert len(missing_needs) == 2
    assert set(n.target for n in missing_needs) == {"employment_type", "dependents"}

    # Stage is collecting_information
    assert derive_stage(state) == Stage.collecting_information


def test_unconfirmed_document_fields():
    """Unconfirmed document-sourced fields need confirmation."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"]],
            documents=[DocumentRequirement(doc_type="payslip", label="Payslip")]
        )
    )

    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)

    # Eligibility satisfied
    add_field(app, "monthly_net_income", Decimal("5000"), source=FieldSource.document, confirmed=False)
    fp = fingerprint(app, ["monthly_net_income"])
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(
            status=EligibilityStatus.satisfied,
            reasons=[],
            rule_version="v1"
        ),
        input_fingerprint=fp,
        verified_inputs=True
    )

    # Document accepted
    add_document(app, "payslip", status=DocumentStatus.accepted)

    state = make_session(app)
    needs = next_needs(state)

    # One review of the document values (the form), not a confirmation per field
    assert [n.kind for n in needs] == [NeedKind.review_extracted]


def test_conflict_blocks_offers():
    """Open conflict creates resolve_conflict need."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"]],
            documents=[DocumentRequirement(doc_type="payslip", label="Payslip")]
        )
    )

    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    add_field(app, "monthly_net_income", Decimal("5000"), source=FieldSource.document, confirmed=True)

    # Eligibility satisfied
    fp = fingerprint(app, ["monthly_net_income"])
    app.eligibility = EligibilityRecord(
        result=EligibilityResult(
            status=EligibilityStatus.satisfied,
            reasons=[],
            rule_version="v1"
        ),
        input_fingerprint=fp,
        verified_inputs=True
    )

    # Document accepted
    add_document(app, "payslip", status=DocumentStatus.accepted)

    # Add conflict
    app.conflicts.append(FieldConflict(
        field="monthly_net_income",
        customer_value="4500",
        document_value="5000",
        document_id="doc_0"
    ))

    state = make_session(app)
    needs = next_needs(state)

    # An open conflict is settled on the review form
    assert [n.kind for n in needs] == [NeedKind.review_extracted]


def test_choose_product_need_when_discovery_complete():
    """After discovery fields, need to choose product."""
    app = make_app()
    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)

    state = make_session(app)
    needs = next_needs(state)

    # Need choose_product
    assert needs[0].kind == NeedKind.choose_product

    # Stage is still discovery
    assert derive_stage(state) == Stage.discovery


def test_multi_group_needs_missing_discovery_and_choose_product():
    """Missing discovery field lists both missing_field and choose_product."""
    app = make_app()
    add_field(app, "purpose", "debt consolidation")
    # Missing amount and term_months

    state = make_session(app)
    needs = next_needs(state)

    # Should have all discovery missing fields + choose_product
    assert len(needs) == 3
    assert needs[0].kind == NeedKind.missing_field
    assert needs[0].target == "amount"
    assert needs[1].kind == NeedKind.missing_field
    assert needs[1].target == "term_months"
    assert needs[2].kind == NeedKind.choose_product


def test_multi_group_needs_required_fields_and_documents():
    """Values a document verifies are not asked; only the missing document is."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"], specs["employer_name"]],
            documents=[DocumentRequirement(doc_type="payslip", label="Payslip")]
        )
    )

    # Fill discovery fields but not requirement fields
    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    # Missing monthly_net_income, employer_name, and payslip document

    state = make_session(app)
    needs = next_needs(state)

    assert [(n.kind, n.target) for n in needs] == [(NeedKind.document, "payslip")]


def test_is_verified_profile_identity_field():
    """Profile-sourced identity field counts as verified."""
    from src.models.credit import FieldSpec, FieldType

    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[
                FieldSpec(
                    name="ssn",
                    label="SSN",
                    type=FieldType.text,
                    required=True,
                    verified_by="id_card",
                    identity=True
                )
            ],
            documents=[]
        )
    )

    # Add identity field from profile
    add_field(app, "ssn", "123-45-6789", source=FieldSource.profile)

    spec = app.requirements.fields[0]
    assert is_verified(app, spec) is True


def test_is_verified_profile_non_identity_must_verify():
    """Profile-sourced non-identity must_verify field does not count as verified."""
    from src.models.credit import FieldSpec, FieldType

    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[
                FieldSpec(
                    name="income",
                    label="Income",
                    type=FieldType.money,
                    required=True,
                    verified_by="payslip",
                    identity=False
                )
            ],
            documents=[]
        )
    )

    # Add non-identity field from profile
    add_field(app, "income", Decimal("5000"), source=FieldSource.profile)

    spec = app.requirements.fields[0]
    assert is_verified(app, spec) is False


def test_is_verified_document_field_document_not_accepted():
    """Confirmed document-sourced field whose document is not accepted → not verified."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"]],
            documents=[DocumentRequirement(doc_type="payslip", label="Payslip")]
        )
    )

    # Add document in processing state
    doc = add_document(app, "payslip", status=DocumentStatus.processing)

    # Add field from this document
    add_field(app, "monthly_net_income", Decimal("5000"),
              source=FieldSource.document, confirmed=True, document_id=doc.document_id)

    spec = specs["monthly_net_income"]
    assert is_verified(app, spec) is False


def test_is_verified_must_verify_false():
    """Field with must_verify=False is verified when present."""
    from src.models.credit import FieldSpec, FieldType

    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[
                FieldSpec(
                    name="purpose",
                    label="Purpose",
                    type=FieldType.text,
                    required=True,
                    verified_by=None  # No verification required
                )
            ],
            documents=[]
        )
    )

    # Add customer-sourced field
    add_field(app, "purpose", "debt consolidation", source=FieldSource.customer)

    spec = app.requirements.fields[0]
    assert spec.must_verify is False
    assert is_verified(app, spec) is True


def test_offers_current_false_after_amount_change():
    """offers_current returns False after amount changes."""
    specs = make_specs()
    app = make_app(
        product_code=Product.personal_loan,
        requirements=ProductRequirements(
            product_code=Product.personal_loan,
            fields=[specs["monthly_net_income"]],
            documents=[]
        )
    )

    add_field(app, "purpose", "debt consolidation")
    add_field(app, "amount", Decimal("50000"))
    add_field(app, "term_months", 48)
    add_field(app, "monthly_net_income", Decimal("5000"))

    # Create offers
    fp = fingerprint(app, ["amount", "term_months", "monthly_net_income"])
    app.offers = OffersRecord(
        offers=[
            LoanOffer(
                offer_id="offer_1",
                product_code=Product.personal_loan,
                amount=Money(amount=Decimal("50000")),
                term_months=48,
                annual_interest_rate_percent=Decimal("10.5"),
                monthly_installment=Money(amount=Decimal("1280")),
                total_repayment=Money(amount=Decimal("61440")),
                total_cost=Money(amount=Decimal("11440")),
                fees=Money(amount=Decimal("0")),
                assumptions=[]
            )
        ],
        input_fingerprint=fp
    )

    # Offers are current
    assert offers_current(app) is True

    # Change amount
    add_field(app, "amount", Decimal("60000"))

    # Now stale
    assert offers_current(app) is False
