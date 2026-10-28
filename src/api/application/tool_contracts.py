"""Machine-readable customer-tool allowlist, not an AI/orchestrator implementation."""

from typing import Any


CUSTOMER_TOOLS: dict[str, dict[str, Any]] = {
    name: {"x-orchestrator-tool": True, "x-allowed-roles": ["customer"]}
    for name in (
        "get_customer_profile", "get_customer_loans", "search_banking_policies",
        "get_required_documents", "validate_document", "run_eligibility_check",
        "calculate_loan_offer", "simulate_early_repayment", "compare_refinancing_options",
        "create_loan_application", "submit_application", "get_application_status",
        "request_human_review", "create_customer_notification",
    )
}
for name in ("search_banking_policies", "get_required_documents", "validate_document", "get_application_status", "run_eligibility_check"):
    CUSTOMER_TOOLS[name]["x-allowed-roles"] = ["customer", "reviewer"]
CUSTOMER_TOOLS["submit_application"].update({
    "x-permitted-workflow-states": ["READY_FOR_SUBMISSION"],
    "x-explicit-customer-confirmation-required": True,
})
STAFF_OPERATIONS = {
    "get_assigned_review_queue", "record_human_review_decision", "add_internal_review_note",
}


def operation_metadata(operation_id: str) -> dict[str, Any]:
    if operation_id in CUSTOMER_TOOLS:
        return CUSTOMER_TOOLS[operation_id]
    if operation_id in STAFF_OPERATIONS:
        metadata: dict[str, Any] = {
            "x-orchestrator-tool": False, "x-allowed-roles": ["reviewer"],
            "x-assigned-reviewer-required": True,
        }
        if operation_id == "record_human_review_decision":
            metadata.update({"x-permitted-workflow-states": ["PENDING_HUMAN_REVIEW"], "x-human-action-required": True})
        return metadata
    return {"x-orchestrator-tool": False}