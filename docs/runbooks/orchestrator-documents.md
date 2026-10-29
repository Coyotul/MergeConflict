# Orchestrator document tools: what works and how to check it

## What happens when you upload a document

The chat API now uses the **actual uploaded file**, not the demonstration values
in `config/orchestrator/customers.yaml`. This also applies when
`ORCHESTRATOR_MODEL=fake`; only the conversation and banking integrations remain
simulated.

1. Check that the customer owns the session and that the application requests this document type.
2. Check the size, real file signature and decodability. Reject damaged, encrypted,
   active/attached-content PDFs, oversized images and files that merely claim to be PDFs.
3. Stage the original in private local storage, bound to the customer **and session**,
   using a generated filename and SHA-256 integrity hash.
4. Read native PDF page text or run Windows OCR on scanned PDF pages / PNG / JPEG.
   Mixed text-and-scanned PDFs and upside-down scans are handled. PDF metadata is
   not an OCR transcript and cannot supply trusted fields.
5. Extract structured fields and run deterministic document rules: identifiers,
   dates, employment evidence, income and statement balance consistency.
6. Compare names/CNPs across documents and compare net income with explicit salary
   deposit evidence. Missing evidence is not replaced with a guess.
7. Persist extraction/validation metadata atomically with the original. Only
   accepted, high-confidence fields enter the application, initially unconfirmed.

Stored originals and results survive restarts. Metadata updates are serialized
across store instances/local workers. A failed uncommitted upload is removed;
evidence referenced by a committed session is not deleted if message logging fails.

## What the assistant can do

| Tool | Access | Purpose |
| --- | --- | --- |
| `process_document` | Server-controlled, automatic on upload | Actual OCR + structured extraction + deterministic validation; no model acceptance override |
| `read_document_extraction` | Model-callable, read-only | Read safe extracted fields for `id_card`, `payslip` or `bank_statement` in the current application; recheck ownership/integrity first |
| `verify_application_documents` | Model-callable, read-only | Inspect current rule results, stored-file integrity and cross-document consistency for the current application |

Read-only tools cannot choose a customer, supply a path, upload arbitrary bytes or
mark evidence accepted. Raw OCR text, file paths, CNPs and IBANs are not included in
their responses to the model. Untrusted document instructions are not forwarded
as a transcript. OCR still derives names/employers from untrusted evidence; these
remain data, not instructions, and cannot invoke a state-changing tool.

Verification runs automatically before further application progress and submission;
it does not depend on the model remembering to call a tool. It rechecks document
expiry/recency against the current turn's date. Replacements invalidate stale
eligibility, offers and summaries. Corrected replacements rerun reconciliation.

## Understanding the results

| Result | What it means | What happens next |
| --- | --- | --- |
| Accepted | Supported, readable, sufficiently complete evidence passed the applicable checks | Review and confirm extracted fields; differences from stated values are shown as conflicts |
| Rejected, no human-review flag | Unreadable or deterministically invalid evidence | Upload a clear, valid replacement; rejected fields are not trusted |
| Human verification required | Low confidence, profile mismatch, inconsistent dossier, unsupported extraction, missing debt/seniority evidence or failed integrity check | The chat shows a fixed explanation and enters `manual_review`; automatic offers/submission are blocked |

The existing checklist uses `rejected` for unusable evidence, including evidence
awaiting human verification, so existing frontend status rendering still works.
The assistant's fixed review message distinguishes review from a request to retry.
Customer confirmation cannot override a document or integrity failure. There is
no new endpoint that lets the model or customer clear a human-review gate.

### Supported evidence and deliberate limits

- `id_card`: Romanian identity-card text/scans; the full name must match the
  configured synthetic customer profile, and **no CNP checksum waiver applies** to chat uploads.
- `payslip`: the existing Romanian income/employment-certificate extractor.
  Arbitrary gross-pay figures and annual ANAF totals are not treated as monthly net pay.
  ANAF evidence without employment start-date evidence requires review.
- `bank_statement`: the existing Romanian statement extractor, with explicit
  monthly obligation evidence such as `Obligatii lunare credite existente: 400,00 RON`.
  Total spending, total incoming transfers or absence of debt rows do **not** prove
  zero obligations. Statements without an explicit debt total require independent review.
- `property_valuation`: no extractor exists yet; safely requires human verification
  rather than returning a made-up property value.
- Native PDFs work without Windows OCR. Scans require Windows `winocr` and a
  Romanian or English OCR language pack. Unavailable OCR safely rejects the scan.
- Format/checksum/consistency checks **do not prove issuer authenticity**, complete
  debt-bureau verification or bank-grade KYC, and do not approve a loan.
- Extraction confidence is a deterministic field-completeness heuristic, not a
  calibrated OCR accuracy probability. Difficult layouts and unclear evidence
  require review rather than a guarantee that arbitrary bank documents are readable.
- A detected mismatch or tamper check blocks progression and is logged when the
  turn commits. Local staging is not a transactional database spanning every file
  and conversation: an abrupt process crash can leave an unreferenced staged file
  or a stale worker lock. The prototype retains/blocks rather than guessing that
  deletion or evidence acceptance is safe; production needs recovery/retention jobs.
- This is local **synthetic-data prototype storage**, not an encrypted production
  vault. The registry is part of the trusted local application directory; SHA-256
  detects changed originals, not an attacker who can rewrite both registry and file.
  There is no malware-scanner integration, production identity gateway, encrypted
  object store, key management or retention policy. Do not upload real customer data.
- `X-Customer-Id` is the existing demo identity header, not secure authentication.
  Production deployment still requires a trusted authenticated gateway and restricted
  filesystem access. Run the demo on loopback only.

## Easily understandable tests

From PowerShell, run:

```powershell
& 'C:\Users\Cosmin\Desktop\MergeConflict\.venv\Scripts\python.exe' 'C:\Users\Cosmin\Desktop\MergeConflict\scripts\check_document_tools.py'
```

This prints a PASS/FAIL line for each area:

- Safe uploads and isolated, restart-safe storage.
- Strict document checks and no guessed financial values.
- Actual OCR of images, native/scanned/mixed PDFs and upside-down scans.
- Assistant read-only tools and blocked acceptance overrides.
- Real API processing, conflicts, tampering, restart and interrupted-write recovery.
- The complete application conversation using real synthetic PDFs, ending in
  submission **for human review**, never automatic approval.

No paid model call or Docker is needed. On non-Windows systems the actual Windows
OCR checks are explicitly reported as skipped, not presented as passing. The
command exits nonzero on any failure, includes failing test details, and writes a
JUnit report under `data/local/document-checks/results.xml` (ignored by Git).
Add `--verbose` to show all pytest output.

For the whole Python regression suite:

```powershell
& 'C:\Users\Cosmin\Desktop\MergeConflict\.venv\Scripts\python.exe' -m pytest 'C:\Users\Cosmin\Desktop\MergeConflict\tests' -q -p no:cacheprovider -rs
```

Install the repository's declared dependencies into `.venv` first. The committed
OpenAPI contracts were generated with FastAPI 0.162.0; FastAPI 0.115.12 remains
within the broad requirement range but produces different generated validation
schemas. The contract tests catch that environment drift. No eligibility contract
was changed by this integration.

For browser checks, using a free test port rather than interrupting any service on 8000:

```powershell
$env:ORCHESTRATOR_PYTHON = 'C:\Users\Cosmin\Desktop\MergeConflict\.venv\Scripts\python.exe'
$env:ORCHESTRATOR_E2E_URL = 'http://127.0.0.1:8010'
npm run test:e2e
```

`ORCHESTRATOR_E2E_URL` is only a browser-test setting. Normal runtime still defaults
to port 8000. Existing sessions whose documents were accepted by the old stub lack
verified secure-storage records: start a new demo session or replace those files;
they are deliberately not grandfathered in as verified evidence.

## Verified local results (2026-10-29)

- Document-only command: **119 passed**, no failures or skips (actual Windows OCR included).
- Full Python suite with the optional credit-source benchmark enabled: **742 passed**,
  **420 subtests passed**, **13 skipped**, no failures. The skips are 12 unavailable
  PostgreSQL checks and 1 live-model check without `FEATHERLESS_API_KEY`.
- `npm run check`: lint/type checks pass, **63 JavaScript tests pass**. Two existing
  unused-import lint warnings remain in frontend files untouched by this task.
- Browser suite: **8 passed**, including the real orchestrator upload path.
- Both customer and staff production builds pass. One Windows `kill EPERM` attempt
  was followed by a successful normal build retry; no build code was changed.
- Real loopback HTTP server: healthy startup, spoofed-PDF rejection, real PNG OCR,
  income/statement extraction, full human-review submission and cross-customer denial
  all passed. The temporary server/files were cleaned up.
- Generated chat/eligibility contracts, dependency consistency and Python compilation pass.

No real banking request, model API call, final credit decision, main merge or push
was performed. Changes are on `feature/orchestrator-document-tools` only.