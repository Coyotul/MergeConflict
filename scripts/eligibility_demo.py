"""Reproducible offline screening demo. Run as: python -m scripts.eligibility_demo."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.eligibility_demo import build_demo_service, demo_cases, load_reference_fixture
from src.models.eligibility import EligibilityCheckRequest
from src.security.eligibility import ActorContext, ActorRole
from scripts.credit_sources.setup import create_database


async def run_demo() -> list[dict]:
    reference_time = load_reference_fixture().reference_time
    with TemporaryDirectory(prefix="eligibility-demo-") as directory:
        anaf_database = create_database(Path(directory) / "credit_sources.db")
        service = build_demo_service(
            Path(directory) / "demo.sqlite3", clock=lambda: reference_time,
            anaf_database_path=anaf_database,
        )
        cases = demo_cases()
        actor = ActorContext(
            "demo-reviewer-actor", ActorRole.REVIEWER,
            permissions=frozenset({"eligibility:assess", "eligibility:read"}),
            assigned_application_ids=frozenset(case.application.application_id for case in cases),
        )
        output = []
        for case in cases:
            application = case.application
            result = await service.assess(EligibilityCheckRequest(
                application_id=application.application_id,
                pricing_scenario_id=application.pricing_scenarios[0].scenario_id,
                idempotency_key=f"demo-run-{application.application_id}",
            ), actor)
            output.append({
                "application": application.application_id, "status": result.status.value,
                "financial_assessment": result.financial_assessment.model_dump(mode="json") if result.financial_assessment else None,
                "flags": [c.reason_code for c in result.checks if c.status.value in {"FAIL", "INFORMATION_REQUIRED", "REVIEW_REQUIRED"}],
                "simulated": result.simulated, "final_credit_decision": result.final_credit_decision,
                "human_review_required": result.human_review_required,
            })
        return output


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), indent=2))