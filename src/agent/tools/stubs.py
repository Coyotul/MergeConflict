"""Stub tool implementations for the orchestrator."""
import logging
import math

logger = logging.getLogger("src.agent.tools.stubs")
import secrets
from dataclasses import dataclass
from datetime import datetime, UTC, date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, TYPE_CHECKING
import yaml

from src.agent.orchestration.progress import (
    can_run_eligibility,
    can_calculate_offers,
    fingerprint,
    eligibility_input_names,
    offer_input_names,
)
from src.agent.orchestration.state import (
    SessionState,
    ExtractedField,
    FieldSource,
    EscalationRecord,
)
from src.agent.tools.contracts import (
    PassageView,
    SearchPoliciesInput,
    SearchPoliciesOutput,
    GetCreditProductsInput,
    GetCreditProductsOutput,
    GetCustomerProfileInput,
    CustomerProfileOutput,
    GetProductRequirementsInput,
    RunEligibilityInput,
    ProcessDocumentInput,
    ProcessDocumentOutput,
    CalculateOffersInput,
    CalculateOffersOutput,
    CreateApplicationInput,
    CreateApplicationOutput,
    SubmitApplicationInput,
    SubmitApplicationOutput,
    GetApplicationStatusInput,
    ApplicationStatusOutput,
    StatusEntry,
    RequestHumanReviewInput,
    RequestHumanReviewOutput,
)
from src.agent.tools.registry import ToolRegistry, ToolSpec, ToolContext, Flow
from src.agent.tools.retrieval import PolicySearch
from src.core.errors import ToolUnavailable, KnowledgeStoreUnavailable, EmbeddingModelUnavailable
from src.models.chat import CitationRef
from src.models.credit import (
    CreditProduct,
    Money,
    ProductRequirements,
    FieldSpec,
    FieldType,
    DocumentRequirement,
    EligibilityResult,
    EligibilityStatus,
    ReasonItem,
    LoanOffer,
)
from src.models.knowledge import Product, SearchQuery, SearchStatus, PassageFlag

if TYPE_CHECKING:
    from src.services.document_processing.service import DocumentProcessingService


def annuity_installment(principal: Decimal, annual_rate_percent: Decimal, months: int) -> Decimal:
    """Calculate monthly annuity installment.

    Args:
        principal: Loan principal amount
        annual_rate_percent: Annual interest rate as percentage (e.g., 9.5)
        months: Number of months

    Returns:
        Monthly installment quantized to 0.01 with ROUND_HALF_UP
    """
    if annual_rate_percent == Decimal("0"):
        # Zero interest: simple division
        result = principal / Decimal(months)
    else:
        # Standard annuity formula
        monthly_rate = annual_rate_percent / Decimal("100") / Decimal("12")
        # payment = P * r / (1 - (1 + r)^(-n))
        one_plus_r = Decimal("1") + monthly_rate
        # Use Python's built-in pow for Decimal exponentiation
        denominator = Decimal("1") - (one_plus_r ** (-months))
        result = principal * monthly_rate / denominator

    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class EligibilityRule:
    """Eligibility rules for a product."""
    product_code: Product
    min_age: int
    max_age_at_maturity: int
    min_monthly_income: Decimal
    max_dti: Decimal
    min_employment_months: int
    manual_review_employment_types: list[str]
    rule_version: str

    def make_satisfied_result(self) -> EligibilityResult:
        """Create a satisfied eligibility result."""
        return EligibilityResult(
            status=EligibilityStatus.satisfied,
            reasons=[ReasonItem(code="all_preliminary_rules_passed", message="All preliminary rules passed")],
            rule_version=self.rule_version,
            simulated=True
        )


@dataclass
class StubData:
    """Synthetic configuration data for stubs."""
    products: dict[Product, CreditProduct]
    requirements: dict[Product, ProductRequirements]
    eligibility_rules: dict[Product, EligibilityRule]
    customers: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, config_dir: Path) -> "StubData":
        """Load stub data from YAML files.

        Args:
            config_dir: Directory containing YAML configuration files

        Returns:
            Loaded StubData instance
        """
        # Load products
        with open(config_dir / "products.yaml", "r", encoding="utf-8") as f:
            products_data = yaml.safe_load(f)

        products = {}
        for p in products_data["products"]:
            product_code = Product(p["code"])
            products[product_code] = CreditProduct(
                code=product_code,
                name=p["name"],
                purposes=p["purposes"],
                min_amount=Money(amount=Decimal(str(p["min_amount"])), currency=p["currency"]),
                max_amount=Money(amount=Decimal(str(p["max_amount"])), currency=p["currency"]),
                min_term_months=p["min_term_months"],
                max_term_months=p["max_term_months"],
                indicative_annual_rate_percent=Decimal(str(p["indicative_annual_rate_percent"])),
                rate_note=p["rate_note"]
            )

        # Load requirements
        with open(config_dir / "requirements.yaml", "r", encoding="utf-8") as f:
            requirements_data = yaml.safe_load(f)

        requirements = {}
        for product_code_str, reqs in requirements_data["requirements"].items():
            product_code = Product(product_code_str)

            fields = []
            for f in reqs["fields"]:
                fields.append(FieldSpec(
                    name=f["name"],
                    label=f["label"],
                    type=FieldType(f["type"]),
                    required=f.get("required", True),
                    verified_by=f.get("verified_by"),
                    identity=f.get("identity", False),
                    min=Decimal(str(f["min"])) if "min" in f else None,
                    max=Decimal(str(f["max"])) if "max" in f else None,
                    options=f.get("options")
                ))

            documents = []
            for d in reqs["documents"]:
                documents.append(DocumentRequirement(
                    doc_type=d["doc_type"],
                    label=d["label"]
                ))

            requirements[product_code] = ProductRequirements(
                product_code=product_code,
                fields=fields,
                documents=documents
            )

        # Load eligibility rules
        with open(config_dir / "eligibility.yaml", "r", encoding="utf-8") as f:
            eligibility_data = yaml.safe_load(f)

        eligibility_rules = {}
        for product_code_str, rules in eligibility_data["eligibility"].items():
            product_code = Product(product_code_str)
            eligibility_rules[product_code] = EligibilityRule(
                product_code=product_code,
                min_age=rules["min_age"],
                max_age_at_maturity=rules["max_age_at_maturity"],
                min_monthly_income=Decimal(str(rules["min_monthly_income"])),
                max_dti=Decimal(str(rules["max_dti"])),
                min_employment_months=rules["min_employment_months"],
                manual_review_employment_types=rules["manual_review_employment_types"],
                rule_version=rules["rule_version"]
            )

        # Load customers
        with open(config_dir / "customers.yaml", "r", encoding="utf-8") as f:
            customers_data = yaml.safe_load(f)

        customers = customers_data["customers"]

        return cls(
            products=products,
            requirements=requirements,
            eligibility_rules=eligibility_rules,
            customers=customers
        )


def build_stub_registry(
    data: StubData, policy_search: PolicySearch, *, document_service: "DocumentProcessingService | None" = None,
) -> ToolRegistry:
    """Build a tool registry with stub implementations.

    Args:
        data: Loaded stub data
        policy_search: Policy search implementation

    Returns:
        Configured ToolRegistry
    """
    registry = ToolRegistry()

    # Shared state for submit_application idempotency
    submission_cache: dict[str, str] = {}

    # Handler for search_banking_policies
    def handle_search_policies(input: SearchPoliciesInput, ctx: ToolContext) -> SearchPoliciesOutput:
        try:
            query = SearchQuery(
                text=input.text,
                products=input.products
            )
            result = policy_search.search(query)
        except (KnowledgeStoreUnavailable, EmbeddingModelUnavailable) as e:
            # Map RAG exceptions to ToolUnavailable
            raise ToolUnavailable(str(e))

        # Filter passages: drop superseded/withdrawn unless they're the only ones
        filtered_passages = []
        has_normal_passage = False

        for passage in result.passages:
            if PassageFlag.superseded not in passage.flags and PassageFlag.withdrawn not in passage.flags:
                has_normal_passage = True
                filtered_passages.append(passage)

        if not has_normal_passage:
            # Include all passages if only superseded/withdrawn ones exist
            filtered_passages = result.passages

        # Build conflict mapping: chunk_id -> citation_ids
        chunk_to_citations: dict[int, list[str]] = {}
        for conflict in result.conflicts:
            for chunk_id in conflict.chunk_ids:
                chunk_to_citations.setdefault(chunk_id, [])

        # Convert passages to PassageView and assign citation IDs
        passages = []
        for passage in filtered_passages:
            # Assign citation ID
            citation_id = f"c{len(ctx.state.retrieved_sources) + 1}"

            # Build section string
            section = " > ".join(passage.citation.section_path) if passage.citation.section_path else None

            # Store citation reference
            ctx.state.retrieved_sources[citation_id] = CitationRef(
                id=citation_id,
                publisher=passage.citation.publisher,
                title=passage.citation.title,
                url=passage.citation.url,
                section=section,
                effective_date=passage.citation.effective_date
            )

            # Track citation for conflict mapping
            if passage.chunk_id in chunk_to_citations:
                chunk_to_citations[passage.chunk_id].append(citation_id)

            # Build passage text with warnings
            text = passage.text
            warnings_to_append = []

            if PassageFlag.campaign_ended in passage.flags:
                warnings_to_append.append("campaign_ended")
            if PassageFlag.teaser_figure in passage.flags:
                warnings_to_append.append("teaser_figure")

            for warning in warnings_to_append:
                text = f"{text} [warning: {warning}]"

            # Create passage view
            passages.append(PassageView(
                citation_id=citation_id,
                header=passage.header,
                text=text,
                publisher=passage.citation.publisher,
                title=passage.citation.title,
                url=passage.citation.url,
                flags=[f.value for f in passage.flags]
            ))

        # Build notices from conflicts
        notices = []
        for conflict in result.conflicts:
            # Collect all citation IDs for chunks in this conflict
            conflict_citation_ids = []
            for chunk_id in conflict.chunk_ids:
                if chunk_id in chunk_to_citations:
                    conflict_citation_ids.extend(chunk_to_citations[chunk_id])

            if conflict_citation_ids:
                # Deduplicate and sort
                unique_ids = sorted(set(conflict_citation_ids))
                notices.append(f"CONFLICTING_SOURCES: {', '.join(unique_ids)}")

        # Mark as simulated only if using stub policy search
        is_simulated = getattr(policy_search, "simulated", False)
        if is_simulated:
            ctx.state.used_stubs = True

        return SearchPoliciesOutput(
            status=result.status.value,
            passages=passages,
            simulated=is_simulated,
            notices=notices
        )

    # Handler for get_credit_products
    def handle_get_products(input: GetCreditProductsInput, ctx: ToolContext) -> GetCreditProductsOutput:
        products = list(data.products.values())

        # Filter by purpose if provided
        if input.purpose:
            matching = [p for p in products if input.purpose.lower() in [tag.lower() for tag in p.purposes]]
            # If no match, return all products
            if matching:
                products = matching

        ctx.state.used_stubs = True
        return GetCreditProductsOutput(products=products, simulated=True)

    # Handler for get_customer_profile
    def handle_get_profile(input: GetCustomerProfileInput, ctx: ToolContext) -> CustomerProfileOutput:
        customer_id = ctx.state.customer_id
        if customer_id not in data.customers:
            raise ValueError("unknown customer")

        customer = data.customers[customer_id]
        profile = customer["profile"]

        ctx.state.used_stubs = True
        return CustomerProfileOutput(
            customer_id=customer_id,
            full_name=profile["full_name"],
            age=profile["age"],
            simulated=True
        )

    # Handler for get_product_requirements
    def handle_get_requirements(input: GetProductRequirementsInput, ctx: ToolContext) -> ProductRequirements:
        if input.product_code not in data.requirements:
            raise ValueError(f"No requirements for product {input.product_code}")

        return data.requirements[input.product_code]

    # Handler for run_eligibility_check
    def handle_eligibility(input: RunEligibilityInput, ctx: ToolContext) -> EligibilityResult:
        app = ctx.state.application
        if app is None or app.product_code is None:
            raise ValueError("No application or product selected")

        # Try real ANAF eligibility service bridge first
        try:
            from src.services.eligibility.orchestrator_bridge import assess_session_eligibility
            real_result = assess_session_eligibility(ctx, data)
            if real_result is not None:
                return real_result
        except Exception as exc:
            logger.warning(f"Eligibility service bridge evaluation failed, using fallback: {exc}")

        product_code = app.product_code
        if product_code not in data.eligibility_rules:
            raise ValueError(f"No eligibility rules for product {product_code}")

        rule = data.eligibility_rules[product_code]

        # Get fields from application state
        def get_field(name: str) -> Any:
            if name not in app.fields:
                raise ValueError(f"Missing field: {name}")
            return app.fields[name].value

        # Extract required fields
        age = int(get_field("age"))
        employment_type = str(get_field("employment_type"))
        employment_months = int(get_field("employment_months"))
        monthly_net_income = Decimal(str(get_field("monthly_net_income")))
        existing_monthly_obligations = Decimal(str(get_field("existing_monthly_obligations")))
        amount = Decimal(str(get_field("amount")))
        term_months = int(get_field("term_months"))

        # Check rules
        reasons = []

        # Age check: age >= min_age and age + ceil(term_months/12) <= max_age_at_maturity
        age_at_maturity = age + math.ceil(term_months / 12)
        if age < rule.min_age or age_at_maturity > rule.max_age_at_maturity:
            reasons.append(ReasonItem(
                code="age_out_of_range",
                message=f"Age or age at maturity out of acceptable range (age: {age}, age at maturity: {age_at_maturity})"
            ))

        # Income check
        if monthly_net_income < rule.min_monthly_income:
            reasons.append(ReasonItem(
                code="income_below_minimum",
                message=f"Monthly net income {monthly_net_income} RON is below minimum {rule.min_monthly_income} RON"
            ))

        # Employment duration check
        if employment_months < rule.min_employment_months:
            reasons.append(ReasonItem(
                code="employment_too_short",
                message=f"Employment duration {employment_months} months is below minimum {rule.min_employment_months} months"
            ))

        # DTI check
        product = data.products[product_code]
        indicative_rate = product.indicative_annual_rate_percent
        monthly_installment = annuity_installment(amount, indicative_rate, term_months)
        total_monthly_obligations = existing_monthly_obligations + monthly_installment
        dti = total_monthly_obligations / monthly_net_income

        if dti > rule.max_dti:
            reasons.append(ReasonItem(
                code="dti_above_limit",
                message=f"Debt-to-income ratio {float(dti):.2%} exceeds maximum {float(rule.max_dti):.2%}"
            ))

        # Manual review for employment types
        if employment_type in rule.manual_review_employment_types:
            ctx.state.used_stubs = True
            return EligibilityResult(
                status=EligibilityStatus.manual_review,
                reasons=[ReasonItem(
                    code="self_employed_manual_review",
                    message=f"Employment type '{employment_type}' requires manual review"
                )],
                rule_version=rule.rule_version,
                simulated=True
            )

        # Determine status
        if reasons:
            status = EligibilityStatus.not_satisfied
        else:
            status = EligibilityStatus.satisfied
            reasons = [ReasonItem(code="all_preliminary_rules_passed", message="All preliminary rules passed")]

        ctx.state.used_stubs = True
        return EligibilityResult(
            status=status,
            reasons=reasons,
            rule_version=rule.rule_version,
            simulated=True
        )

    # Handler for process_document
    def handle_process_document(input: ProcessDocumentInput, ctx: ToolContext) -> ProcessDocumentOutput:
        # Check for empty file
        if input.size_bytes == 0:
            ctx.state.used_stubs = True
            return ProcessDocumentOutput(
                status="rejected",
                rejection_reason="The file is empty.",
                extracted_fields={},
                simulated=True
            )

        # Check for reject_ prefix
        if input.filename.startswith("reject_"):
            ctx.state.used_stubs = True
            return ProcessDocumentOutput(
                status="rejected",
                rejection_reason="The document is unreadable; please upload a clearer copy.",
                extracted_fields={},
                simulated=True
            )

        # Get customer data
        customer_id = ctx.state.customer_id
        if customer_id not in data.customers:
            raise ValueError("unknown customer")

        customer = data.customers[customer_id]

        # Extract fields for this doc type
        if input.doc_type not in customer["documents"]:
            ctx.state.used_stubs = True
            return ProcessDocumentOutput(
                status="accepted",
                rejection_reason=None,
                extracted_fields={},
                simulated=True
            )

        doc_data = customer["documents"][input.doc_type]
        low_confidence_fields = set(customer.get("low_confidence", []))

        extracted = {}
        for field_name, value in doc_data.items():
            confidence = 0.6 if field_name in low_confidence_fields else 0.95
            extracted[field_name] = ExtractedField(
                value=str(value),
                confidence=confidence,
                location=None
            )

        ctx.state.used_stubs = True
        return ProcessDocumentOutput(
            status="accepted",
            rejection_reason=None,
            extracted_fields=extracted,
            simulated=True
        )

    # Handler for calculate_loan_offer
    def handle_calculate_offers(input: CalculateOffersInput, ctx: ToolContext) -> CalculateOffersOutput:
        app = ctx.state.application
        if app is None or app.product_code is None:
            raise ValueError("No application or product selected")

        product_code = app.product_code
        product = data.products[product_code]

        # Get amount and term_months from application
        amount = Decimal(str(app.fields["amount"].value))
        term_months = int(app.fields["term_months"].value)

        # Build list of terms: [term_months] + input options, maintaining order
        # Customer's term_months is always first
        terms_list = [term_months]

        # Add options in order, clamping each to product range
        if input.term_options_months:
            for opt in input.term_options_months:
                # Clamp to product range
                clamped = max(product.min_term_months, min(product.max_term_months, opt))
                terms_list.append(clamped)

        # Clamp customer's term too
        terms_list[0] = max(product.min_term_months, min(product.max_term_months, terms_list[0]))

        # Dedupe while maintaining order, take up to 3
        seen = set()
        deduped_terms = []
        for t in terms_list:
            if t not in seen:
                seen.add(t)
                deduped_terms.append(t)
                if len(deduped_terms) >= 3:
                    break

        sorted_terms = deduped_terms

        # Build offers
        offers = []
        input_fingerprint = fingerprint(app, offer_input_names(app))

        for term in sorted_terms:
            # Calculate installment
            rate = product.indicative_annual_rate_percent
            monthly_installment = annuity_installment(amount, rate, term)

            # Calculate totals
            total_repayment = monthly_installment * Decimal(term)
            total_cost = total_repayment - amount
            fees = Decimal("0")

            # Build offer ID
            offer_id = f"{product_code.value}-{term}m-{input_fingerprint[:6]}"

            # Assumptions
            assumptions = [
                f"Illustrative annual interest rate: {rate}%",
                "Fees: 0 RON",
                "Simulated, based on public conditions; not an offer from Raiffeisen Bank"
            ]

            offers.append(LoanOffer(
                offer_id=offer_id,
                product_code=product_code,
                amount=Money(amount=amount, currency="RON"),
                term_months=term,
                annual_interest_rate_percent=rate,
                monthly_installment=Money(amount=monthly_installment, currency="RON"),
                total_repayment=Money(amount=total_repayment, currency="RON"),
                total_cost=Money(amount=total_cost, currency="RON"),
                fees=Money(amount=fees, currency="RON"),
                assumptions=assumptions,
                indicative=True,
                simulated=True
            ))

        ctx.state.used_stubs = True
        return CalculateOffersOutput(offers=offers, simulated=True)

    # Handler for create_loan_application
    def handle_create_application(input: CreateApplicationInput, ctx: ToolContext) -> CreateApplicationOutput:
        draft_id = f"DRAFT-{secrets.token_hex(4)}"
        ctx.state.used_stubs = True
        return CreateApplicationOutput(draft_application_id=draft_id, simulated=True)

    # Handler for submit_application
    def handle_submit_application(input: SubmitApplicationInput, ctx: ToolContext) -> SubmitApplicationOutput:
        # Check idempotency
        if input.idempotency_key in submission_cache:
            app_id = submission_cache[input.idempotency_key]
        else:
            app_id = f"APP-{secrets.token_hex(4)}"
            submission_cache[input.idempotency_key] = app_id

        ctx.state.used_stubs = True
        return SubmitApplicationOutput(
            application_id=app_id,
            status="PENDING_HUMAN_REVIEW",
            simulated=True
        )

    # Handler for get_application_status
    def handle_get_status(input: GetApplicationStatusInput, ctx: ToolContext) -> ApplicationStatusOutput:
        app = ctx.state.application

        if app is None or app.application_id is None:
            ctx.state.used_stubs = True
            return ApplicationStatusOutput(
                application_id=None,
                status="NO_APPLICATION",
                history=[],
                simulated=True
            )

        # Build history
        history = []
        if app.submitted_at:
            history.append(StatusEntry(
                status="SUBMITTED",
                at=app.submitted_at.isoformat()
            ))
        if app.draft_application_id:
            history.append(StatusEntry(
                status="DRAFT",
                at=ctx.state.updated_at.isoformat()
            ))

        ctx.state.used_stubs = True
        return ApplicationStatusOutput(
            application_id=app.application_id,
            status="PENDING_HUMAN_REVIEW",
            history=history,
            simulated=True
        )

    # Handler for request_human_review
    def handle_request_review(input: RequestHumanReviewInput, ctx: ToolContext) -> RequestHumanReviewOutput:
        ticket_id = f"HR-{secrets.token_hex(4)}"

        # Set escalation in state
        ctx.state.escalation = EscalationRecord(
            ticket_id=ticket_id,
            reason=input.reason,
            created_at=ctx.now
        )

        ctx.state.used_stubs = True
        return RequestHumanReviewOutput(
            ticket_id=ticket_id,
            message="A human advisor will review your case and a representative will follow up with you.",
            simulated=True
        )

    # Register all tools
    registry.register(ToolSpec(
        name="search_banking_policies",
        description="Search for banking policy information",
        input_model=SearchPoliciesInput,
        output_model=SearchPoliciesOutput,
        model_callable=True,
        flows=frozenset([Flow.product_info, Flow.credit_application]),
        handler=handle_search_policies
    ))

    registry.register(ToolSpec(
        name="get_credit_products",
        description="Get available credit products",
        input_model=GetCreditProductsInput,
        output_model=GetCreditProductsOutput,
        model_callable=True,
        flows=frozenset([Flow.product_info, Flow.credit_application]),
        handler=handle_get_products
    ))

    registry.register(ToolSpec(
        name="get_customer_profile",
        description="Get customer profile",
        input_model=GetCustomerProfileInput,
        output_model=CustomerProfileOutput,
        model_callable=True,
        flows=frozenset([Flow.credit_application]),
        handler=handle_get_profile
    ))

    registry.register(ToolSpec(
        name="get_product_requirements",
        description="Get requirements for a product",
        input_model=GetProductRequirementsInput,
        output_model=ProductRequirements,
        model_callable=False,
        flows=frozenset([Flow.credit_application]),
        handler=handle_get_requirements
    ))

    registry.register(ToolSpec(
        name="run_eligibility_check",
        description="Run eligibility check",
        input_model=RunEligibilityInput,
        output_model=EligibilityResult,
        model_callable=True,
        flows=frozenset([Flow.credit_application]),
        handler=handle_eligibility,
        precondition=can_run_eligibility
    ))

    registry.register(ToolSpec(
        name="process_document",
        description="Process an uploaded document",
        input_model=ProcessDocumentInput,
        output_model=ProcessDocumentOutput,
        model_callable=False,
        flows=frozenset([Flow.credit_application]),
        handler=handle_process_document
    ))

    registry.register(ToolSpec(
        name="calculate_loan_offer",
        description="Calculate loan offers",
        input_model=CalculateOffersInput,
        output_model=CalculateOffersOutput,
        model_callable=True,
        flows=frozenset([Flow.credit_application]),
        handler=handle_calculate_offers,
        precondition=can_calculate_offers
    ))

    registry.register(ToolSpec(
        name="create_loan_application",
        description="Create a draft loan application",
        input_model=CreateApplicationInput,
        output_model=CreateApplicationOutput,
        model_callable=False,
        flows=frozenset([Flow.credit_application]),
        handler=handle_create_application
    ))

    registry.register(ToolSpec(
        name="submit_application",
        description="Submit loan application",
        input_model=SubmitApplicationInput,
        output_model=SubmitApplicationOutput,
        model_callable=False,
        flows=frozenset([Flow.credit_application]),
        handler=handle_submit_application
    ))

    registry.register(ToolSpec(
        name="get_application_status",
        description="Get application status",
        input_model=GetApplicationStatusInput,
        output_model=ApplicationStatusOutput,
        model_callable=True,
        flows=frozenset([Flow.none, Flow.product_info, Flow.credit_application]),
        handler=handle_get_status
    ))

    registry.register(ToolSpec(
        name="request_human_review",
        description="Request human review",
        input_model=RequestHumanReviewInput,
        output_model=RequestHumanReviewOutput,
        model_callable=True,
        flows=frozenset([Flow.none, Flow.product_info, Flow.credit_application]),
        handler=handle_request_review
    ))

    if document_service is not None:
        from src.agent.tools.documents import register_document_tools
        register_document_tools(registry, document_service, data.customers)
    return registry
