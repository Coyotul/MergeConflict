import unittest
from uuid import uuid4

from pydantic import ValidationError

from src.models.requests import CreateApplicationInput, DocumentInput, RefinancingInput, ReviewInput, SubmitApplicationInput


class RequestSchemaTests(unittest.TestCase):
    def test_confirmation_is_literal_boolean_not_coerced(self):
        for confirmation in (False, 1, "true", "yes", None):
            with self.subTest(confirmation=confirmation), self.assertRaises(ValidationError):
                SubmitApplicationInput.model_validate({"confirmed": confirmation, "idempotencyKey": str(uuid4())})

    def test_amount_months_and_extra_authority_are_strict(self):
        valid = {"productId": "personal", "amount": "30000.00", "months": 36, "idempotencyKey": str(uuid4())}
        self.assertEqual(CreateApplicationInput.model_validate(valid).months, 36)
        for change in ({"amount": 30000}, {"amount": "3e4"}, {"amount": "٣٠٠٠٠"}, {"amount": "30000.001"}, {"months": "36"}, {"months": True}, {"annualRate": "0"}, {"customerId": "customer-blake"}, {"status": "APPROVED"}, {"product_id": "personal"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                CreateApplicationInput.model_validate({**valid, **change})

    def test_document_checks_are_metadata_only_and_reject_bad_formats(self):
        valid = {"kind": "identity", "name": "synthetic.pdf", "mimeType": "application/pdf", "size": 100, "syntheticConfirmed": True}
        self.assertEqual(DocumentInput.model_validate(valid).name, "synthetic.pdf")
        for change in ({"name": "../secret.pdf"}, {"name": "synthetic.exe"}, {"size": 0}, {"size": 10485761}, {"size": True}, {"syntheticConfirmed": 1}, {"verified": True}, {"bytes": "payload"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                DocumentInput.model_validate({**valid, **change})

    def test_review_requires_evidence_and_requested_document_consistency(self):
        valid = {"action": "approve", "reason": "Independently inspected demo evidence.", "evidenceReviewed": True, "idempotencyKey": str(uuid4())}
        self.assertEqual(ReviewInput.model_validate(valid).action, "approve")
        for change in ({"evidenceReviewed": 1}, {"evidenceReviewed": False}, {"reason": "short"}, {"action": "request-information"}, {"requestedDocument": "income"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ReviewInput.model_validate({**valid, **change})

    def test_refinancing_rejects_duplicate_loan_ids(self):
        with self.assertRaises(ValidationError):
            RefinancingInput.model_validate({"loanIds": ["loan-car", "loan-car"], "months": 36})