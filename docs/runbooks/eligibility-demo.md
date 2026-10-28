# Eligibility Check: local demo and integration runbook

## Run on the feature branch

From PowerShell, use Python 3.11+ and the declared project dependencies:

```powershell
Set-Location 'c:\Users\Cosmin\Desktop\MergeConflict'
git switch feature/eligibility-check
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m scripts.eligibility_demo
python -m scripts.eligibility_smoke
```

The offline demo and live HTTP smoke use the fixture's explicit **2026-10-28**
reference clock, temporary SQLite files and only fabricated applicant data.
They do not connect to a bank, ANAF or Biroul de Credit. The smoke binds a
temporary port on **127.0.0.1**, tests seven HTTP behaviors and stops the server.
Neither script leaves a running process or changes workflow state.

Run the local API (current UTC clock, ignored local persistence):

```powershell
python -m uvicorn src.api.gateway.eligibility_demo:create_app --factory --host 127.0.0.1 --port 8000
```

Interactive API documentation: `http://127.0.0.1:8000/docs`.
`main.py` remains the original interpreter diagnostic; it is not the API entry
point. No frontend files or frontend server behavior are modified by this branch.

**Do not expose this demo publicly.** Its bundled demo bearer keys are deliberately
public synthetic credentials, not user authentication. Production identity,
rate limits, HTTPS, retention and database access controls are not implemented.

## Try an assessment

In a second PowerShell terminal:

```powershell
$headers = @{ Authorization = 'Bearer demo-customer-key' }
$body = @{
    application_id = 'demo-app-eligible'
    pricing_scenario_id = 'demo-quote-eligible'
    idempotency_key = 'demo-assessment-0001'
} | ConvertTo-Json
$result = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/eligibility/assessments' -Method Post -Headers $headers -ContentType 'application/json' -Body $body
$result.data
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/eligibility/assessments/$($result.data.assessment_id)" -Headers $headers
```

Use `demo-reviewer-key` to inspect the assigned cases below. The customer key is
scoped to `demo-app-eligible`, not arbitrary customer IDs. All roles/assignments
are resolved on the backend, never accepted as request parameters.

| Application | Pricing scenario | Expected at the reference clock |
| --- | --- | --- |
| `demo-app-eligible` | `demo-quote-eligible` | Preliminary requirements satisfied. |
| `demo-app-high-dti` | `demo-quote-high-dti` | Preliminary requirements not satisfied (DTI). |
| `demo-app-missing-id` | `demo-quote-missing-id` | Additional information required. |
| `demo-app-adverse-history` | `demo-quote-adverse-history` | Preliminary requirements not satisfied (synthetic enforcement flag). |
| `demo-app-bureau-unavailable` | `demo-quote-bureau-unavailable` | Manual review required; no financial pass. |
| `demo-app-missing-consent` | `demo-quote-missing-consent` | Additional information required; ANAF provider is not called. |

The normal API uses real current time. As fixtures age, evidence becomes stale
and the published demo policy snapshot expires on **2026-11-26**. Review-required
results then are intentional. Do not extend effective dates or refresh timestamps
silently. Use the reproducible scripts for the historical demonstration, or add
reviewed new policy/evidence versions with a new test fixture.

## Rules and calculations

- Public Raiffeisen references are a configurable snapshot, not internal policy.
  The default **2,700 RON net-income threshold is a labelled synthetic assumption**.
- DTI compares exact monthly debt service to verified income times the configured
  cap (40% or stricter), before ratio-display rounding.
- Existing internal/bureau debts use canonical IDs; matching copies count once.
  Conflicting copies require review. Unused revolving facilities count at least
  3% of granted limit. Foreign-currency and incomplete debts require review.
- Proposed repayment uses Decimal arithmetic and nominal annual interest.
  Financed fees/insurance are already in principal; recurring fees/insurance are
  added only once. Decreasing loans use their highest first payment.
- No FICO approval threshold is invented; no-history/missing score differs from
  unavailable or partial bureau evidence.
- Every result is preliminary, synthetic and human-review-required. This service
  never approves, rejects, submits, signs, disburses or changes application state.

Sources and unresolved bank-policy details: `../research/eligibility-raiffeisen-ro.md`.
The HTTP/tool contract and frontend mapping notes are in
`../../contracts/http/eligibility.md`.

## Persistence, retries and recovery

Runtime file: `c:\Users\Cosmin\Desktop\MergeConflict\data\local\eligibility-demo.sqlite3`
(ignored by Git). Application inputs are read-only synthetic fixtures; assessments,
hashed actor-scoped retry keys and audit events persist in SQLite. This is not
production cloud persistence and does not implement the full application workflow.

- Repeat the same request/key: retrieve the original assessment/time, without a
  new inquiry in the single-process demo. It is a historical replay, not a newly
  verified result. Use a new key for a deliberately fresh check.
- 409 `IDEMPOTENCY_CONFLICT`: change the key only after checking that the caller
  intends to assess the updated inputs/snapshot; never conceal a changed payload.
- 409 `APPLICATION_CHANGED`: upstream evidence changed while verification was in
  flight. No stale assessment is persisted. Review the new state and retry.
- 503 `STORAGE_UNAVAILABLE`: fix local directory permissions/database availability,
  then retry. Assessment/key/audit writes are one transaction; failure is not
  reported as success.
- Provider outage/timeout: bounded attempts, then review/information-required.
  Do not substitute a clean report. A retried assessment with the same persisted
  key returns its historical outcome; use a new key for fresh verification.
- Policies with no effective version or overlapping effective versions: manual
  review, no provider inquiry. Correct/version policy configuration and restart.

Before intentionally deleting the local demo database, stop the server and confirm
the exact file path. Deleting it discards assessment/audit/retry history. Never
apply demo resets or synthetic data procedures to real customer records.

The per-process lock and SQLite unique constraints prevent duplicate saved
outcomes. They do **not** guarantee exactly-once real provider inquiries across
multiple workers; a durable reservation/outbox and approved provider contracts
are required before that architecture is introduced.

## Contracts and handoff

```powershell
python -m scripts.export_eligibility_contracts
python -m scripts.export_eligibility_contracts --check
```

Generated artifacts come from the actual FastAPI/Pydantic/tool definitions. A
contract test verifies they are not stale. To integrate, inject authorized profile,
document verification, application/consent repositories, pricing scenarios and
bank adapters into `EligibilityService`; inject gateway identity into the router.
The LLM calls `run_eligibility_check` with identifiers only. The frontend must
support all four assessment statuses and retain citations/assumptions. Its
metadata-only document checklist is not verified evidence, and its temporary
tokens are not accepted by this Python demo gateway.

Work remains on `feature/eligibility-check`. Push only the explicit feature ref;
merge into `master` through a reviewed pull request, never a direct push.