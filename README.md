# MergeConflict

Bank-agnostic agentic AI banking and credit management platform, covering loan
applications, refinancing, repayment and ongoing credit assistance. Developed in
the VibeHack challenge context; it is not affiliated with or endorsed by a bank.
The repository currently contains scaffolding and documentation, not working
banking services or frontend applications.

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
UI. No additional framework or infrastructure dependencies are needed to inspect
or extend the scaffold.

Local knowledge base: to build and query the local RAG index over Raiffeisen's public
credit documentation, follow [docs/runbooks/rag-local.md](docs/runbooks/rag-local.md).

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

New Python packages contain only `__init__.py` placeholders. Non-Python folders
contain `.gitkeep` so Git preserves the layout. Add implementations and tests as
capabilities are built. Keep databases, uploads and indexes in ignored
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
