# MergeConflict

Bank-agnostic agentic AI banking and credit management platform, covering loan
applications, refinancing, repayment and ongoing credit assistance. Developed in
the VibeHack challenge context; it is not affiliated with or endorsed by a bank.
The repository contains a working local frontend prototype for customers and bank
agents. On `feature/eligibility-check`, it also includes a working **synthetic
Python preliminary eligibility service** alongside the broader platform scaffold.
Authentication, data and decisions in the prototype are synthetic only.
The Python service is not yet wired into the frontend's temporary Node adapter;
neither implements live banking or the complete credit lifecycle.

Start with [SPECIFICATION.md](SPECIFICATION.md), the main product reference supplied
by the project owner. See [ARCHITECTURE.md](ARCHITECTURE.md) for the folder tree, mapping of every
diagram component to code, ownership boundaries and implementation order.
See [CONTEXT.md](CONTEXT.md) for the challenge and [RULES.md](RULES.md) for coding
conventions.

## Local setup

### Frontend prototype

Requires Node.js 22+ and npm. From the repository root in PowerShell:

```powershell
Set-Location 'C:\Users\George\repos\MergeConflict'
npm ci
npm run dev
```

This starts three loopback-only services:

- Customer workspace: http://127.0.0.1:3000
- Bank agent / credit reviewer: http://127.0.0.1:3001
- Temporary synthetic demo API: http://127.0.0.1:4010/health

### Luma + AI orchestrator integration

The customer chat in Luma connects to the AI orchestrator running on port 8000. Start the orchestrator **before** starting the frontend:

```bash
# Real mode (requires FEATHERLESS_API_KEY in .env):
uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8000

# Or mock mode (no API key required):
ORCHESTRATOR_MODEL=fake uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Then start the frontend:

```bash
npm run dev
```

The customer workspace will connect to the orchestrator automatically. Each new chat session picks a random synthetic customer (`cust-001`, `cust-002`, or `cust-003`) for demonstration purposes.

**Environment variables:**

- `NEXT_PUBLIC_ORCHESTRATOR_URL` (default: `http://127.0.0.1:8000`): Orchestrator API base URL.
- `ORCHESTRATOR_CORS_ORIGINS` (default: `http://127.0.0.1:3000,http://127.0.0.1:3001,http://localhost:3000,http://localhost:3001`): Comma-separated list of allowed frontend origins for CORS.

If the orchestrator is not running or becomes unavailable, the chat displays an error message with a retry button.

Sign in using the public **demo** accounts below, also displayed on each login
screen. The “Use demo account” button fills the form; signing in is a separate
explicit action.

| Workspace | Email | Demo password |
| --- | --- | --- |
| Customer (Alex Morgan) | `alex@example.test` | `ClientDemo123!` |
| Bank agent (Jamie Carter) | `jamie@example.test` | `AgentDemo123!` |

The interface uses a Raiffeisen-inspired yellow (`#FFED00`), black and white palette
under the fictional **Luma** brand. It is not an official bank application.
English UI text and the conversational, desktop-first layout are preserved from
the earlier frontend direction; the sign-in screens also work on mobile.

Customers can explore loans, use deterministic calculators, prepare applications,
add synthetic document metadata, confirm submission and track status. Assigned
agents can inspect cases, request additional information, add private notes and
record justified demo approvals or rejections. Signing and funding are not implemented.

The demo API persists applications, conversations and audit history in ignored
`data/local/frontend-demo.json`. Session tokens are role-bound, expire after eight
hours, survive page refresh in the same browser tab and are revoked at logout.
Restarting the demo API requires signing in again, without losing saved applications.
Public fixed credentials and browser session storage are **not production banking
security**. Do not enter real credentials, applicant data or documents. Uploads
store metadata only; no file contents are transmitted or verified. The assistant
uses guided rule-based responses, not a live LLM or RAG service.

Validation commands:

```powershell
npm run check       # ESLint, TypeScript, domain/API tests
npm run build       # Both production Next.js builds
npx playwright install chromium  # First-time browser installation, if needed
npm run test:e2e    # Starts isolated demo services; leave ports 3000/3001/4010 free
```

Browser tests use their own JSON store under ignored `data/local/`, not the normal
demo store. See `docs/decisions/001-local-frontend.md`,
`docs/decisions/003-yellow-black-sign-in.md` and `contracts/http/frontend-demo.md`
for the demo boundary and integration contract.

### Python eligibility service and architecture scaffold

Use Python 3.11 or newer. From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

`main.py` reports the interpreter and Python version. It does not start an API or
UI. The eligibility feature has a separate FastAPI entry point documented below;
its dependencies are declared in `requirements.txt`.

Local knowledge base: to build and query the local RAG index over Raiffeisen's public
credit documentation, follow [docs/runbooks/rag-local.md](docs/runbooks/rag-local.md).

## Where to start

- `apps/customer/`, `apps/staff/`: working local Next.js/React/TypeScript customer
  and assigned-reviewer interfaces. Administrator views are deferred.
- `packages/ui/`, `packages/banking/`: shared visual controls, typed demo contracts,
  calculations, React state and the temporary Node demo adapter.
- `src/`: Python components. Existing parser, rule, model, agent, core and UI
  packages remain in place; FastAPI is the selected backend framework.
- `contracts/`: HTTP, event and serialized-data specifications.
- `config/`: versioned synthetic product and rule configuration.
- `data/synthetic/`: synthetic demo documents and application inputs.
- `tests/`: unit, integration, contract and end-to-end tests plus synthetic fixtures.
- `infrastructure/`, `scripts/`, `docs/`: environment definitions, maintenance
  commands, architecture decisions and operational notes.

Unimplemented Python packages contain `__init__.py` placeholders. Unimplemented
non-Python folders contain `.gitkeep` so Git preserves the layout. Add
implementations and tests as capabilities are built. Keep databases, uploads and
indexes in ignored
`data/local/`; never commit credentials or real applicant data.

## MVP boundary

Demonstrate a synthetic personal-loan application from login and cited product
answers through eligibility screening, deterministic simulation, explicit customer
submission, a reviewer request for additional information, resubmission and a
human-recorded final decision. Preserve application state, notifications and audit
history. Include at least one refinancing or early repayment simulation.

Every new credit application requires authorized human review. Signing and
disbursement are separate stages and may only be simulated in this MVP. No real
banking inquiries, financial transactions or loan approvals occur.

## Eligibility Check implementation (feature branch)

`feature/eligibility-check` implements the Python preliminary-screening branch:
deterministic reference rules, Decimal affordability, synthetic ANAF/credit-bureau/
internal-loan adapters, authorized API/tool access and local assessment/audit
persistence. It is independent of the frontend prototype and never records a
final credit decision or changes workflow state.

See [the eligibility runbook](docs/runbooks/eligibility-demo.md),
[HTTP/tool contract](contracts/http/eligibility.md), and
[Raiffeisen/BNR research](docs/research/eligibility-raiffeisen-ro.md) for setup,
sources and explicit synthetic assumptions. From the repository root:

```powershell
python -m unittest discover -s tests -v
python -m scripts.eligibility_demo
python -m scripts.eligibility_smoke
python -m uvicorn src.api.gateway.eligibility_demo:create_app --factory --host 127.0.0.1 --port 8000
```

The API's public demo keys and SQLite storage are **local synthetic demonstration
only**, not production authentication/infrastructure. The reproducible demo uses
an explicit historical reference clock; the normal API enforces current evidence
freshness and policy expiry. No real bank, ANAF or bureau requests are made.

## Synthetic external credit-source database

An independent offline SQLite fixture now models **ANAF**, **Biroul de Credit**
and **CRC**, with one shared product/history source and date-sensitive report
views. It provides 323 fictional people, 422 products and 73 labelled edge-case
scenarios. The canonical schema remains empty; sample data is a separate SQL
export. No real identities or provider calls are used.

Schema, sample SQL and metadata live at
`C:\Users\msi\Downloads\mergeconflict-integration\data\synthetic\credit_sources`
in the integration checkout. The setup command reconstructs an ignored local
database and refuses to overwrite an existing file:

```powershell
Set-Location 'C:\Users\msi\Downloads\mergeconflict-integration'
py -3 -B -m scripts.credit_sources.setup
py -3 -B -m scripts.credit_sources.verify_credit_sources --replay
```

See `C:\Users\msi\Downloads\mergeconflict-integration\docs\runbooks\credit-sources.md`
for commands, test coverage, data-quality limitations and the adapter handoff.
Paths in these examples should be adjusted to your checkout; executable tooling
discovers the repository root from its own location.

**This is not yet wired into the existing eligibility providers or frontend.**
The external source has CNPs rather than application customer IDs, REAL/RON
figures rather than typed Decimal evidence, and intentional incomplete histories.
Its descriptive DSTI view does not replace new-loan affordability, revolving
rules, authorization, evidence provenance or human review. The existing backend
and frontend behavior is preserved. Runtime SQLite files stay in ignored local
storage; only reproducible fictional source fixtures and tools are versioned.

## Synthetic banking test documents

The repository includes a generator for realistic Romanian banking documents in standard A4 PDF format:
1. **Carte de Identitate (Buletin)**: Romanian national identity card with CNP, series/number, VIZ fields, and MRZ checksum lines.
2. **Adeverință de Venit**: Salary & employer certificate with employer CUI, monthly net income, 6-month salary table, indefinite contract, and seniority.
3. **Extras de Cont Bancar**: Multi-transaction bank account statement (Raiffeisen Bank, BT, BCR, etc.) with IBAN, initial balance, salary deposit inflows, debits, and closing balance.

```powershell
# Generate default document suites for Alex Morgan and primary personas:
.\.venv\Scripts\python.exe scripts/generate_documents.py

# Generate for a specific scenario persona or customer:
.\.venv\Scripts\python.exe scripts/generate_documents.py --customer alex_morgan
```

Generated PDF files are stored under `data/synthetic/documents/<customer_id>/`.

## Document Processing Pipeline & Regulatory Verification

Implements the 4-stage document processing architecture:
1. **Secure Document Storage** (`src/storage/secure_documents/`):
   - Customer-isolated storage under `data/local/secure_documents/<customer_id>/`.
   - Content hashing with SHA-256 for non-repudiation and tamper detection (`verify_integrity`).
   - Path-traversal defense, sanitized UUID filenames, and strict MIME/size controls.
2. **OCR & Extraction** (`src/parsers/ocr/`, `src/parsers/extraction/`):
   - Fast vector text extraction via `pypdf`.
   - Native **Windows Media OCR** integration (`winocr`) with Romanian (`ro-RO`) and English (`en-US`) language models for scanned raster PDFs and image files (`.png`, `.jpg`).
   - Auto-orientation detection for tilted or inverted/upside-down scans (90°, 180°, 270°).
   - Structured field extractors for ID Cards (`IdCardExtractor`), Income Certificates (`IncomeCertificateExtractor`), and Bank Statements (`BankStatementExtractor`).
3. **Regulatory & Mathematical Validation** (`src/parsers/validation/`):
   - **CNP Validator**: Official Romanian Modulo 11 checksum (`279146358279`), century/gender decoding, calendar birth date, county mapping, and age policy (18–70 years).
   - **CUI Validator**: Official Romanian ANAF fiscal code algorithm (`753217532`, modulo 11).
   - **IBAN Validator**: ISO 7064 MOD 97-10 check digits for Romanian accounts (`RO..`).
   - **BNR Underwriting Norms** (Regulations 17/2012 and 12/2018):
     - Income certificate recency <= 30 calendar days.
     - Employment seniority >= 3 months at current employer and indefinite contract (`NEDETERMINATĂ`).
     - Minimum net income >= 2,363 RON (Romanian statutory threshold).
     - Statement recency <= 90 days, balance integrity (`Initial + Credits - Debits == Closing`), and salary deposit detection.
4. **Cross-Document Verification**:
   - Reconciles applicant full name across ID card, income certificate, and statement holder.
   - CNP identity matching between ID card and income certificate.
   - Cross-checks net income against detected recurring statement salary inflow.

### Manual Verification CLI Tool

You can manually inspect any document or full customer dossier using [`scripts/verify_documents.py`](scripts/verify_documents.py):

```powershell
# Verify full dossier for demo customer Alex Morgan:
.\.venv\Scripts\python.exe scripts/verify_documents.py

# Verify a specific synthetic customer dossier:
.\.venv\Scripts\python.exe scripts/verify_documents.py --customer dan_ionescu_dsti_39

# List all available synthetic customer folders:
.\.venv\Scripts\python.exe scripts/verify_documents.py --list

# Verify any single custom PDF or image scan:
.\.venv\Scripts\python.exe scripts/verify_documents.py --file path/to/document.pdf --type identity
```

See [ADR 007](docs/decisions/007-document-processing-pipeline.md) and the [Technical Specification](docs/reference/document-processing-specification.md) for complete details.

## Run the orchestrator

The orchestrator is a conversational AI agent that guides customers through credit applications. It uses Featherless AI (gpt-oss-120b) for natural language understanding and maintains session state across turns.

### Environment variables

Copy `.env.example` to `.env` in the repository root and configure:

- `FEATHERLESS_API_KEY`: Your Featherless API key (required for real mode)
- `ORCHESTRATOR_MODEL`: Model identifier (default: `openai/gpt-oss-120b`)
- `ORCHESTRATOR_SESSION_STORE`: `memory`, `file`, or `postgres` (default: `file`)
- `ORCHESTRATOR_RETRIEVAL`: `stub` (synthetic) or `rag` (requires RAG service, default: `stub`)
- `ORCHESTRATOR_REQUEST_TIMEOUT_S`: Model request timeout in seconds (default: `60.0`)

See `.env.example` for all available settings.

### Mock mode (no API key required)

Run the API with a scripted, deterministic assistant using synthetic data:

```bash
ORCHESTRATOR_MODEL=fake uvicorn src.api.app:create_app --factory --port 8000
```

Sessions are saved under `data/local/sessions/` and survive restarts. Set `ORCHESTRATOR_SESSION_STORE=memory` for a clean slate on every start.

### Real mode (with Featherless AI)

Run with the real model (requires `FEATHERLESS_API_KEY` in `.env`):

```bash
uvicorn src.api.app:create_app --factory --port 8000
```

Omit `ORCHESTRATOR_MODEL` to use the default (`openai/gpt-oss-120b`).

### PostgreSQL session store

To persist sessions in PostgreSQL instead of the filesystem, start the local
database, apply the SQL migrations (idempotent; uses `ORCHESTRATOR_DATABASE_URL`,
default `postgresql://rag:rag@127.0.0.1:5433/rag`), then start the API:

```bash
docker compose -f infrastructure/local/docker-compose.yml up -d
python -c "import psycopg; from src.core.settings import load_orchestrator_settings; from src.storage.application_db.migrate import apply_migrations; print(apply_migrations(psycopg.connect(load_orchestrator_settings().database_url)))"
ORCHESTRATOR_SESSION_STORE=postgres uvicorn src.api.app:create_app --factory --port 8000
```

The migration command prints the newly applied files (`[]` when up to date).

### Testing

- All tests: `python -m pytest tests -v`
- Unit tests only: `python -m pytest tests/unit -v`
- Integration tests (require Docker): `python -m pytest tests/integration -v`
- E2E scenarios: `python -m pytest tests/e2e -v`
- Live smoke test (requires API key): `python -m pytest tests/live -v`

### Frontend integration

See [contracts/http/README.md](contracts/http/README.md) for the chat API contract, endpoints, request/response formats, and rendering guidance.

### Agent decision trace

The orchestrator records every decision, model call, tool invocation, and turn outcome to an append-only trace file for debugging and evaluation. Traces are written as JSON Lines (one event per line) and survive crashes mid-turn.

**Environment variables:**

- `ORCHESTRATOR_TRACE`: `file` (default) or `off` — enables or disables trace recording
- `ORCHESTRATOR_TRACES_DIR`: Directory for trace files (default: `data/local/traces`)

**Trace location:**

Each session's trace is stored at `<ORCHESTRATOR_TRACES_DIR>/<session_id>.jsonl`. Traces live in the ignored `data/local/` directory and are never committed to Git.

**Generating a readable report:**

Use `scripts/trace_report.py` to convert a trace file into a Markdown timeline:

```bash
python scripts/trace_report.py <session_id> [--traces-dir DIR] [--out FILE] [--full]
```

The report shows:
- Session metadata (customer, model, prompt version)
- Per-turn timeline with stage transitions and duration
- Model calls with latency, token usage, and context
- Tool calls with caller (model or code), status, and duration
- Field updates with acceptance/rejection reasons (✓/✗)
- Citations kept and dropped
- Turn outcomes (replied, fallback, step_cap, model_unavailable, error)

Use `--full` to include complete context JSON and tool outputs.

**Event types:**

- `session_started`: Session created with model settings and system prompt
- `system_prompt_changed`: Prompt version updated mid-session
- `turn_started`: New turn with triggering event and current needs
- `model_call`: LLM request with context, latency, tokens, and raw output
- `action_parsed`: Successfully parsed intent and action from model output
- `action_invalid`: Parse failure, with retry flag
- `field_updates`: Field validation results (accepted/rejected with reasons)
- `tool_call`: Tool execution (model-invoked or code-triggered) with outcome
- `citations_filtered`: Citation IDs kept vs. dropped after validation
- `code_event`: Code-handled events (upload processed, offer selected, confirmation)
- `turn_finished`: Turn outcome, reply, citations, and final stage

**Warning:** Traces contain conversation content and context. Use synthetic data only for development and testing.
