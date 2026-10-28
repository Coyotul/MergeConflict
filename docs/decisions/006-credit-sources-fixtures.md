# ADR 006: isolated synthetic external credit-source fixtures

Status: accepted for the local prototype integration, 2026-10-28.

## Context

The project already has synthetic preliminary eligibility providers and separate
application/assessment/audit storage. A separately tested SQLite schema simulates
ANAF, bureau and CRC using a common CNP/product history, plus repeatable edge-case
fixtures. The user requested importing it without breaking the existing app.
The actual default branch is `main`, which the user explicitly confirmed.

## Decision

- Version only schema/sample SQL, JSON metadata/catalogue, tooling, tests and docs
  under the existing synthetic-data/scripts/tests ownership boundaries. Runtime
  SQLite files stay in ignored local storage, not in the application migration tree.
- Keep schema-only creation separate from sample loading. Provide a safe setup
  command that refuses existing targets, verifies in memory and verifies the
  saved fixture. Retain the original external specification verbatim.
- Preserve SQL/fixture values and all original 67 tests; add repository setup and
  default-seed reproducibility tests. Do not replace the parent `scripts`/`tests`
  packages: use the scoped `credit_sources` namespace.
- Do not wire providers, HTTP/frontend routes or eligibility policies in this
  import. The external-source store has different identity, completeness,
  provenance, currency and affordability semantics; publish an adapter handoff.
- No new third-party dependencies, real identities/provider requests, final
  decisions, workflow transitions, consent storage or cloud provisioning.
- Use the project's agent claim/log/message workflow and a PR into `main` after
  regression validation; no unrelated histories, protected-branch bypass or force push.

## Consequences

Agents can reconstruct and explore 323 fictional people and 73 labelled scenarios
without touching existing demo stores. SQLite binaries are reproducible local
artifacts, avoiding binary merge conflicts. Tests cover SQL constraints, snapshots,
roles, DSTI, fixtures, imports/rollback, data-quality policies and performance.

This is **not** a plug-compatible `VerificationProvider`: an authorized customer
mapping, Decimal serialization, completeness/freshness/provenance, currency policy,
canonical liabilities and preliminary inquiry semantics remain downstream work.
The current SQL DSTI is descriptive and cannot override the application's new-loan
affordability/revolving calculations or required human review.

The original main dependency ranges permit newer FastAPI versions that change
generated OpenAPI; the pre-existing parity failure is documented in the runbook,
not hidden by regenerating contracts. Regression versions are recorded explicitly.

## References

- Current checkout runbook: `C:\Users\msi\Downloads\mergeconflict-integration\docs\runbooks\credit-sources.md`.
- Canonical SQL/fixtures: `C:\Users\msi\Downloads\mergeconflict-integration\data\synthetic\credit_sources`.
- Repository agent rules: `C:\Users\msi\Downloads\mergeconflict-integration\GIT_AGENT_PROTOCOL.md`.