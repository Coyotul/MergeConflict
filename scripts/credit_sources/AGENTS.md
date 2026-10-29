# Agent handoff: external credit-source fixture tooling

Follow the repository's RULES and Git agent protocol first; claim work on the
shared board before editing. Runtime paths are derived from the repository root.

Read `C:\Users\msi\Downloads\mergeconflict-integration\docs\runbooks\credit-sources.md`
and `C:\Users\msi\Downloads\mergeconflict-integration\docs\decisions\006-credit-sources-fixtures.md`.
This directory is offline stdlib tooling, **not** a live provider or application
repository. Do not alter unrelated scripts, models, frontend or eligibility rules
as a shortcut to importing SQL evidence.

Key invariants: schema is empty except its parameter; samples are separate;
products are shared by bureau/CRC; RON payment money, synthetic CNPs with invalid
checksums; guarantors excluded from debt totals; CRC exact previous-month snapshots;
global reporting date; unknown history must not become verified debt-free evidence.
Never use real personal data, store credentials, or claim official reporting/FICO.

`setup.py` refuses existing files; generator refuses populated targets/exports;
verifier is read-only. Preserve these guarantees. Writable tests use temporary
directories. All runtime DBs/backups/sidecars must remain ignored. Source samples
are versioned at `C:\Users\msi\Downloads\mergeconflict-integration\data\synthetic\credit_sources`;
do not rewrite their schema or values during a path-only change.

Validate both database and parent application suites before handoff. From the
repository root (absolute paths shown for this checkout):

```powershell
py -3 -B 'C:\Users\msi\Downloads\mergeconflict-integration\tests\credit_sources\test_credit_sources.py' --benchmark
py -3 -B -m unittest tests.credit_sources.test_setup -v
py -3 -B -m scripts.credit_sources.verify_credit_sources --replay
```

The full application's tests additionally require its declared Python dependencies
and frontend lockfile. Record the reference FastAPI/Pydantic versions and any
baseline dependency drift instead of changing public contracts to force a pass.
If local data does not exist, `setup` creates it; never delete an existing DB merely
to make the command succeed. Before provider wiring, follow every identity,
provenance, completeness, Decimal/currency and authorization item in the runbook.