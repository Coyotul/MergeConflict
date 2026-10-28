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
