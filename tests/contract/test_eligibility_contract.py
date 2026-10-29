import json
import unittest

from pydantic import ValidationError

from src.agent.tools.eligibility import tool_definition
from src.models.eligibility import (
    CreditBureauData, EligibilityAssessment, EligibilityCheckRequest,
    EvidenceSource, IncomeVerificationData, VerificationResult,
)
from tests.fixtures.eligibility import application, provider_records
from scripts.export_eligibility_contracts import contract_contents


class EligibilityContractTests(unittest.TestCase):
    def test_generated_artifacts_match_executable_contracts(self):
        for path, content in contract_contents().items():
            with self.subTest(path=str(path)):
                self.assertTrue(path.is_file(), f"Missing generated artifact: {path}")
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_tool_has_only_identifier_request_fields(self):
        schema = tool_definition()["parameters"]
        self.assertEqual(set(schema["properties"]), {"application_id", "pricing_scenario_id", "idempotency_key"})
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(tool_definition()["name"], "run_eligibility_check")

    def test_request_rejects_actor_consent_and_evidence_injection(self):
        for field in ("actor", "role", "consent", "profile", "evidence", "annual_interest_percent", "cnp"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                EligibilityCheckRequest.model_validate({"application_id": "demo-app-eligible", "idempotency_key": "test-key-0001", field: "injected"})

    def test_identifier_rejects_paths_and_unbounded_values(self):
        for app_id in ("../other", "a/b", "", "a" * 129):
            with self.subTest(app_id=app_id), self.assertRaises(ValidationError):
                EligibilityCheckRequest(application_id=app_id, idempotency_key="test-key-0001")

    def test_trusted_money_serializes_as_decimal_strings(self):
        payload = json.loads(application().model_dump_json())
        self.assertIsInstance(payload["request"]["amount_ron"], str)
        self.assertIsInstance(payload["pricing_scenarios"][0]["annual_interest_percent"], str)

    def test_provider_envelope_requires_success_evidence_and_no_failure_data(self):
        record = provider_records()[EvidenceSource.ANAF]
        record.pop("evidence")
        with self.assertRaises(ValidationError):
            VerificationResult[IncomeVerificationData].model_validate(record)
        record = provider_records()[EvidenceSource.ANAF]
        record["status"] = "UNAVAILABLE"
        with self.assertRaises(ValidationError):
            VerificationResult[IncomeVerificationData].model_validate(record)

    def test_duplicate_liabilities_and_impossible_no_history_rejected(self):
        data = provider_records()[EvidenceSource.CREDIT_BUREAU]["data"]
        data["obligations"].append(data["obligations"][0].copy())
        with self.assertRaises(ValidationError):
            CreditBureauData.model_validate(data)
        data = provider_records()[EvidenceSource.CREDIT_BUREAU]["data"]
        data["no_credit_history"] = True
        with self.assertRaises(ValidationError):
            CreditBureauData.model_validate(data)

    def test_assessment_schema_cannot_express_final_decision(self):
        schema = EligibilityAssessment.model_json_schema()
        self.assertEqual(schema["properties"]["final_credit_decision"]["const"], False)
        self.assertEqual(schema["properties"]["human_review_required"]["const"], True)
        self.assertEqual(schema["properties"]["simulated"]["const"], True)
        statuses = schema["$defs"]["AssessmentStatus"]["enum"]
        self.assertNotIn("APPROVED", statuses)
        self.assertNotIn("REJECTED", statuses)
        self.assertEqual(len(statuses), 4)