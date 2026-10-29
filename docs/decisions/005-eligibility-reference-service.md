# ADR 005: synthetic deterministic Eligibility Check branch

Status: accepted for the prototype on `feature/eligibility-check`, 2026-10-28.

## Context

The original diagram routes the orchestrator to Eligibility Check, Biroul de
Credit and other verification APIs. The owner specification separates screening
from final decisions, requires synthetic integrations and human review, selects
Python/FastAPI and forbids LLM financial arithmetic. Public bank criteria alone
are not a complete underwriting model.

## Decision

- A service-owned typed boundary consumes trusted application snapshots,
  purpose-scoped authorization, verified document/profile evidence and optional
  pricing. HTTP/LLM callers submit only application/scenario IDs and retry keys.
- Pure eligibility rules and Decimal-safe financial functions use versioned
  JSON policy configuration with regulatory/public/synthetic provenance.
- Synthetic ANAF, credit-bureau and internal-loan providers implement replaceable
  ports. Response shape, owner, inquiry purpose and provenance are validated
  independently of the provider. Unknown/missing/stale data cannot pass.
- Four preliminary outcomes plus rule-level reasons preserve uncertainty.
  Review flags outrank failures when evidence integrity is in question. FICO is
  informational; no private-bank cutoff or numeric arrears policy is guessed.
- Assessment/audit/idempotency storage uses local stdlib SQLite solely for this
  isolated demo. Atomic writes, foreign keys, unique constraints and update
  guards exercise durable snapshot semantics without adding cloud dependencies.
- Narrow FastAPI and orchestrator-tool adapters delegate authorization and
  calculations to the same service. The loopback demo has public synthetic keys;
  it is not production authentication and is not connected to frontend sessions.
- Standard-library unittest, an in-process ASGI harness and a live Uvicorn
  loopback smoke validate the branch without adding pytest/httpx dependencies.

## Consequences and boundaries

The branch is independently executable and can hand off typed evidence/results
to workflow/review/frontend agents. It never transitions workflow state or
creates a final credit decision. The frontend branch is deliberately unmodified.
The SQLite migration is explicitly not a PostgreSQL production migration.

Production requires durable cloud repositories/migrations, authenticated gateway
identity, reviewed age/income policies, legal bases, consent/notice records,
real document verification and provider contracts, retention controls, security
hardening and multi-worker inquiry reservation semantics. In particular,
transactional saved outcomes do not establish exactly-once provider inquiries.

The snapshot's 2,700 RON net-income threshold, evidence windows, calendar
conventions and retry settings are clearly labelled demo assumptions. Policy
expiry is enforced rather than silently treating a historic snapshot as current.

## Git constraint

All implementation commits/pushes target `feature/eligibility-check`. The task-
claim rollback was handled independently; neither `master` nor the rollback
branch is edited/pushed by this implementation. Final integration uses a PR.