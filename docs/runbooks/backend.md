# Local synthetic FastAPI backend

Run from the repository root with Python 3.11+. The implementation was tested in
the existing Windows `.venv` with Python 3.14.6. Use synthetic data only.

```powershell
Set-Location 'C:\Users\George\repos\MergeConflict'
# First-time environment only, if .venv does not already exist:
python -m venv .venv
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' -m pip install -r 'C:\Users\George\repos\MergeConflict\requirements-dev.txt'
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' 'C:\Users\George\repos\MergeConflict\main.py'
```

- Health: http://127.0.0.1:8001/health
- Swagger: http://127.0.0.1:8001/docs
- OpenAPI: http://127.0.0.1:8001/openapi.json
- Canonical tool base: http://127.0.0.1:8001/api/v1
- Runtime database: `data/local/backend-demo.sqlite3`, ignored by Git.

`requirements.txt` is sufficient to run the server. `requirements-dev.txt` additionally
installs HTTPX for TestClient; tests use unittest, not pytest. A known Starlette 1.10
HTTPX deprecation warning does not indicate a test failure; the pinned combination
is tested. No API key, cloud account or running frontend is needed.

The Node/frontend demo continues to run independently with `npm run dev` at ports
3000/3001/4010 and its own JSON store. This increment does not switch its API client
or implement guided/LLM chat. Do not point the entire existing frontend at this API
and assume full compatibility; see the contract's integration limitations.

## Public fictional accounts

| Role | Actor | Email | Public demo password |
| --- | --- | --- | --- |
| Customer | Alex Morgan | `alex@example.test` | `ClientDemo123!` |
| Customer | Blake Rivera | `blake@example.test` | `ClientDemo123!` |
| Reviewer | Jamie Carter | `jamie@example.test` | `AgentDemo123!` |
| Reviewer | Taylor Quinn | `taylor@example.test` | `AgentDemo123!` |

New demo cases are assigned server-side to Jamie. Blake cannot see Alex's data;
Taylor cannot inspect Jamie's assigned applications. There is no administrator
account or role-edit API. Login role is checked against the account, not trusted
as a permission grant. Restart invalidates sessions; application data remains.

## Call a tool from PowerShell

```powershell
$base = 'http://127.0.0.1:8001/api/v1'
$login = Invoke-RestMethod -Method Post -Uri "$base/session" -ContentType 'application/json' -Body (@{
    role = 'customer'; email = 'alex@example.test'; password = 'ClientDemo123!'
} | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($login.data.token)" }
Invoke-RestMethod -Uri "$base/customers/me" -Headers $headers
$scenario = @{ productId = 'personal'; amount = '30000.00'; months = 36 }
Invoke-RestMethod -Method Post -Uri "$base/calculations/loan-offer" -Headers $headers -ContentType 'application/json' -Body ($scenario | ConvertTo-Json)
$scenario.idempotencyKey = [guid]::NewGuid().ToString()
$draft = Invoke-RestMethod -Method Post -Uri "$base/applications" -Headers $headers -ContentType 'application/json' -Body ($scenario | ConvertTo-Json)
Invoke-RestMethod -Uri "$base/applications/$($draft.data.id)/status" -Headers $headers
$check = @{ applicationId = $draft.data.id; pricingScenarioId = $draft.data.pricingScenarioId; idempotencyKey = [guid]::NewGuid().ToString() }
Invoke-RestMethod -Method Post -Uri "$base/eligibility/check" -Headers $headers -ContentType 'application/json' -Body ($check | ConvertTo-Json)
```

This saves a draft only. Add synthetic metadata for identity/income using the
contract's attachment schema, each with a new idempotencyKey. Submission must follow
an actual user confirmation and include `{confirmed: true, idempotencyKey: UUID}`.
The API will not approve a customer tool call; assigned review is separate.
Eligibility uses the merged reference service and ID-only request. Its response
preserves snake_case fields/all four outcomes. With this metadata-only workflow,
profile/identity evidence and purpose-scoped provider authorizations are missing;
an information-required/manual-review outcome is expected, not a satisfied claim.
No reference-fixture consents or income reports are silently copied to your case.
`/calculations/affordability-preview` is a different declared-income-only calculator.

For timeout retries, keep the **same operation/body/key**. A replay returns the
original response snapshot; query status for the latest state. Never retry with a
new key just because the first response was interrupted.
Eligibility preserves a separate replay namespace: the application/policy snapshot
must also be unchanged. After a document or state/revision change, a new check needs
a new key; a historical assessment can still be fetched separately.

## Configuration and validation

Environment overrides (PowerShell; restart server after changing):

```powershell
$env:BACKEND_PORT = '8001'
$env:BACKEND_DB_PATH = 'C:\Users\George\repos\MergeConflict\data\local\backend-demo.sqlite3'
```

Default host is 127.0.0.1. `BACKEND_HOST` is available for explicit local tooling,
but public credentials, plaintext synthetic storage and process-local sessions
make this unsuitable for exposing to a network. Use one worker. SQLite files must
be on persistent local disk, not ephemeral cloud filesystems. Config JSON is loaded
and validated at startup. Existing applications retain their saved policy/evidence
requirements/quote even when later configuration is changed; do not alter a policy
without publishing its matching version.

Run validation:

```powershell
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' -m unittest discover -s 'C:\Users\George\repos\MergeConflict\tests' -t 'C:\Users\George\repos\MergeConflict' -v
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' -m compileall -q 'C:\Users\George\repos\MergeConflict\src' 'C:\Users\George\repos\MergeConflict\tests' 'C:\Users\George\repos\MergeConflict\main.py'
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' -m pip check
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' -m scripts.backend_smoke
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' -m scripts.export_eligibility_contracts --check
npm run check  # Unchanged frontend regression checks
```

Tests create isolated temporary databases and do not change the normal demo store.
No external provider is contacted. For local request traces, the main entry point
logs JSON method/operation/status/correlation/duration, not passwords, tokens,
query strings, message bodies or applicant metadata.

## Failure and reset handling

- 401: sign in again after expiry/logout/restart; never guess a principal.
- 409: inspect the current workflow or key conflict; do not force a status change.
- 429: wait at least Retry-After and use bounded retry.
- 503 or unhealthy database: stop and inspect the database path/disk permissions;
  failed transactional actions do not commit successful workflow states.
- Corrupt/unversioned stores fail startup rather than silently reseed. Preserve
  the file for diagnosis; use a **new BACKEND_DB_PATH** for a fresh synthetic demo.
- For backup, stop the process first or use SQLite's backup API; do not copy only
  the main file while WAL writes are active. Never commit database/WAL files.
- `/chat` returning 501 is expected until orchestration is implemented. Document
  validation returning FORMAT_ACCEPTED is not verification. No real bank support,
  loan approval, signature, funds transfer or debt repayment happens here.

Complete wire/state/authorization contract: `contracts/http/backend-v1.md`.