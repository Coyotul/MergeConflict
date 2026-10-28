# MergeConflict

Bank-agnostic agentic AI banking and credit management platform, covering loan
applications, refinancing, repayment and ongoing credit assistance. Developed in
the VibeHack challenge context; it is not affiliated with or endorsed by a bank.
The repository contains a working local frontend prototype for customers and bank
agents and an authenticated FastAPI backend with deterministic synthetic tools
for a future AI orchestrator. They currently run independently. Authentication,
data and decisions in the prototype are synthetic only.
It also retains the merged evidence-based preliminary eligibility module from
`feature/eligibility-check`. The Python services are not yet wired into the
frontend's temporary Node adapter; none implements live banking or the complete
credit lifecycle.

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

### FastAPI backend and orchestrator tool routes

Use Python 3.11 or newer. From the repository root in PowerShell:

```powershell
# First-time environment only, if .venv does not already exist:
python -m venv .venv
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' -m pip install -r 'C:\Users\George\repos\MergeConflict\requirements-dev.txt'
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' 'C:\Users\George\repos\MergeConflict\main.py'
```

This starts the synthetic backend at http://127.0.0.1:8000:

- `GET /health`: real local database availability and explicitly unconfigured AI dependencies.
- `/docs` and `/openapi.json`: typed contracts and stable logical tool operation IDs.
- `/api/v1`: profile/loans, configured products, fictional policy search, metadata
  checks, preliminary eligibility, Decimal loan/early-repayment/refinancing
  calculations, durable applications, assigned human review, consent, notifications
  and separate conversation context.

`run_eligibility_check` uses the merged evidence-based service with only trusted
application/scenario IDs and a retry key. It retains all four preliminary outcomes;
missing profile/provider consent is not fabricated and metadata stays unverified.
The declared-income calculator is separately labeled `affordability-preview`.

Application state, history, audit and retry results persist transactionally in
ignored `data/local/backend-demo.sqlite3`. Alex/Jamie's demo credentials above
also work here; additional isolation-test accounts and complete commands are in
[the backend runbook](docs/runbooks/backend.md). Tokens expire after eight hours,
are revoked at logout and do not survive restart. Database data does survive.

Every submission requires explicit customer confirmation; every final outcome
requires the assigned reviewer. Document checks are **metadata only**, policy
search is **synthetic keyword matching**, and calculations are **indicative**.
`POST /api/v1/chat` deliberately returns 501 until the orchestrator is connected.
No live LLM/RAG/OCR, real banking operation, signing or disbursement is implemented.

The existing frontend still uses its Node API on port 4010. No frontend files or
startup scripts are switched to FastAPI in this increment. `/api` aliases retain
resource naming but are not full Node chat/input compatibility. See
[the backend contract](contracts/http/backend-v1.md) and
[ADR 006](docs/decisions/006-backend-api.md) before integration. SQLite is local-only;
PostgreSQL/Supabase remains the intended deployed persistence architecture.

Validate the backend from the repository root:

```powershell
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' -m unittest discover -s 'C:\Users\George\repos\MergeConflict\tests' -t 'C:\Users\George\repos\MergeConflict' -v
& 'C:\Users\George\repos\MergeConflict\.venv\Scripts\python.exe' -m pip check
```

Tests use temporary databases, not the normal runtime store. `requirements.txt`
is enough for runtime; `requirements-dev.txt` adds HTTPX for FastAPI TestClient.

## Where to start

- `apps/customer/`, `apps/staff/`: working local Next.js/React/TypeScript customer
  and assigned-reviewer interfaces. Administrator views are deferred.
- `packages/ui/`, `packages/banking/`: shared visual controls, typed demo contracts,
  calculations, React state and the temporary Node demo adapter.
- `src/`: FastAPI gateway/routes, shared Pydantic schemas and modular synthetic
  services. Pure rules/calculations do not depend on HTTP or an LLM; the agent,
  parsers and unimplemented capabilities retain their scaffold locations.
- `contracts/`: HTTP, event and serialized-data specifications.
- `config/`: versioned synthetic product and rule configuration.
- `data/synthetic/`: synthetic demo documents and application inputs.
- `tests/`: unit, integration, contract and end-to-end tests plus synthetic fixtures.
- `infrastructure/`, `scripts/`, `docs/`: environment definitions, maintenance
  commands, architecture decisions and operational notes.

Unimplemented packages/folders retain `__init__.py` or `.gitkeep` markers. Add
capabilities in small verified increments; do not mistake the scaffold for working
integrations. Keep databases, uploads and indexes in ignored `data/local/`; never
commit real credentials or applicant data. Public fictional demo passwords are
fixtures only, not production secrets.

## MVP boundary

Demonstrate a synthetic personal-loan application from login and cited product
answers through eligibility screening, deterministic simulation, explicit customer
submission, a reviewer request for additional information, resubmission and a
human-recorded final decision. Preserve application state, notifications and audit
history. Include at least one refinancing or early repayment simulation.

Every new credit application requires authorized human review. Signing and
disbursement are separate stages and may only be simulated in this MVP. No real
banking inquiries, financial transactions or loan approvals occur.

## Evidence-based Eligibility Check implementation

The merged `feature/eligibility-check` module implements Python preliminary screening:
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
python -m uvicorn src.api.gateway.eligibility_demo:create_app --factory --host 127.0.0.1 --port 8002
```

The API's public demo keys and SQLite storage are **local synthetic demonstration
only**, not production authentication/infrastructure. The reproducible demo uses
an explicit historical reference clock; the normal API enforces current evidence
freshness and policy expiry. No real bank, ANAF or bureau requests are made.
