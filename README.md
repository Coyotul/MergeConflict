# MergeConflict

Bank-agnostic agentic AI banking and credit management platform, covering loan
applications, refinancing, repayment and ongoing credit assistance. Developed in
the VibeHack challenge context; it is not affiliated with or endorsed by a bank.
On `feature/eligibility-check`, the repository includes a working **synthetic
preliminary eligibility service** alongside the broader platform scaffold.
It does not implement live banking services or the complete credit lifecycle.

Start with [SPECIFICATION.md](SPECIFICATION.md), the main product reference supplied
by the project owner. See [ARCHITECTURE.md](ARCHITECTURE.md) for the folder tree, mapping of every
diagram component to code, ownership boundaries and implementation order.
See [CONTEXT.md](CONTEXT.md) for the challenge and [RULES.md](RULES.md) for coding
conventions.

## Local setup

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

- `apps/customer/`, `apps/staff/`: planned Next.js/React/TypeScript interfaces.
  The staff interface includes reviewer and permission-controlled administrator views.
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
implementations and tests as capabilities are built. Keep databases, uploads and indexes in ignored
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
