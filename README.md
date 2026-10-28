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
