# Fictional external credit sources

Versioned schema and deterministic sample data for ANAF, Biroul de Credit and CRC.
No real identities, bank data, credentials or binary database files belong here.

**Default:** seed 20261028; reporting date 2026-10-28; 323 people (73 labelled cases
plus 250 random people), 422 products, 10,615 payment-history rows. CNPs deliberately
fail checksum validation; fictional birth-date/sex metadata agrees.

Use the runbook at
`C:\Users\msi\Downloads\mergeconflict-integration\docs\runbooks\credit-sources.md`.
The catalogue is
`C:\Users\msi\Downloads\mergeconflict-integration\data\synthetic\credit_sources\SAMPLE_DATA.md`.

From the repository root:

```powershell
py -3 -B -m scripts.credit_sources.setup
py -3 -B -m scripts.credit_sources.verify_credit_sources --replay
```

The first command creates the ignored local database at
`C:\Users\msi\Downloads\mergeconflict-integration\data\local\credit_sources.db`;
it refuses to overwrite an existing file. Schema-only SQL inserts no people.
Sample SQL is loaded only after that schema into an empty target; stop on errors.
Changing the sample dataset requires regenerating and validating its SQL, manifest
and catalogue together. The test suite checks default-seed reproducibility.

This dataset is not wired into the application's existing synthetic providers.
Missing histories and summary zeros are not verified no-debt evidence; descriptive
DSTI is not the application's new-loan eligibility rule. Read the adapter handoff
before exposing data to the orchestrator/frontend or deciding how to map customers.