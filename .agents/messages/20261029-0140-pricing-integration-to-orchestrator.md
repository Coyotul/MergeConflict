# Handoff: deterministic pricing connected to the orchestrator

- **From:** Cline / pricing-integration
- **To:** Orchestrator, pricing, eligibility, frontend and maintainers
- **Task:** ORCH-PRICING-02 (local implementation complete)
- **Base:** main `c7cea73f00e2c8a7d031eb29224b278c13ae6fab`
- **Branch:** `feature/orchestrator-pricing`; local review commit only, not pushed/merged.
- **Engine found:** `13b4cf25fe7ea4c606730184e5f799efdca2dc72`, scenarios `b7ee96d`,
  already merged into main by `53c95c2`; no cherry-pick performed.

## Connection

`C:\Users\msi\Downloads\mergeconflict-integration\src\agent\tools\pricing.py`
adapts the existing `calculate_loan_offer` tool to the deterministic service.
The registry factory in
`C:\Users\msi\Downloads\mergeconflict-integration\src\agent\tools\stubs.py`
now registers it for both mock and real-model composition. Personal loan,
unsecured refinancing loan and Casa Ta map to the existing versioned product IDs.
Catalog discovery returns actual simulator limits/rates rather than stale YAML
pricing limits; the independent synthetic eligibility rule stub is unchanged.

The model may request only strict integer alternative terms. Money/product/customer
fields come from the owned session; explicit date is the injected UTC server clock.
Current/satisfied eligibility, verified evidence/conflicts and submitted/escalated
guards remain enforced. No salary discounts, insurance election, risk score,
first-home uplift or missing debt/income are guessed from unrelated fields.

Amounts, DAE, first/later mortgage payments, cost/repayment totals and fees are
engine results, not model arithmetic. Gross credit differs from net payout.
Existing offer assumptions carry precise disclosures/warnings/disclaimer through
JSON, model context, offer cards and confirmation summaries; mock replies include
them with per-term labels. DAE_INCOMPLETE must remain visible. HTTP offer/OpenAPI
shape and frontend implementation are unchanged.

Primary inputs are never clamped; typed pricing rejections produce no selectable
offers. A failed recalculation clears old selection/summary before submission.
Quote IDs include actual result/date/version so repricing requires a new selection
and confirmation. Final application actions remain explicit UI events resulting
only in PENDING_HUMAN_REVIEW. Stored quotes are dated snapshots; automatic expiry
or repricing on every submission is not implemented.

## Not in this connection

The engine's early-repayment and portfolio refinancing-comparison functions are
not registered in this new-application flow: authorized existing loans, balances,
repayment months and settlement costs are not collected. Do not manufacture them.
A dedicated servicing/comparison flow and explicit inputs are needed. Likewise,
new optional insurance/salary account/repayment-method controls require user
collection/confirmation and downstream invalidation, not raw model overrides.

## Checks and follow-ups

- 435 focused pricing/orchestrator/API/chat-contract tests pass (42 new cases).
- 63 Node/API tests, TypeScript/ESLint, both Next builds and 9 Playwright journeys
  pass, including the new real offer/disclosure/selection/confirmation UI journey.
- Full offline run with database benchmark: 670 pass, 2 document/OCR failures;
  both reproduce on untouched c7cea73. First-name fixture mismatch (Dan/Mihai)
  and full-dossier statement validation remain document-owner follow-ups.
- Current local database person names differ from current versioned sample SQL;
  it was left untouched. Reconstruct in a separate temporary file for export parity.
- Existing main chat contracts require a newer allowed FastAPI than the previous
  local environment. Validated here with FastAPI 0.162.0, Pydantic 2.11.10 and
  Uvicorn 0.34.0. Requirements and HTTP schemas were not edited to hide drift.
- PostgreSQL/RAG/live Featherless tests were not run; all new pricing tests are offline.
- Engine mathematics/config, document processing, data fixtures, dependency files
  and frontend source are untouched. Three chat example JSON files were regenerated
  under a fixed execution clock; exported OpenAPI remains identical.

Runbook: `C:\Users\msi\Downloads\mergeconflict-integration\docs\runbooks\orchestrator-pricing.md`.
Review the local diff/commit before publishing. No push or merge was requested.