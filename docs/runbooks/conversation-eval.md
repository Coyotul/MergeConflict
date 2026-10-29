# Runbook: conversation evaluation

Plays the scenarios in `config/eval/scenarios.yaml` through the real agent with a simulated
customer, checks every session trace deterministically and has a judge model grade the agent's
wording. Design: [`docs/superpowers/specs/2026-10-29-conversation-eval-design.md`](../superpowers/specs/2026-10-29-conversation-eval-design.md).

The run never confirms an application: it stops when the agent asks for confirmation, when the
scenario's `stop_when` is met, when the simulated customer says `done`, or after `--max-turns`.

## Requirements

- Every command runs **from the repository root** in your own PowerShell window.
- `.env` in the repository root with `FEATHERLESS_API_KEY` (agent, simulated customer and judge
  all use Featherless). The CLI reads `.env` itself; the key is never written to the report.
- Optional model overrides in `.env`:
  - `ORCHESTRATOR_MODEL`: the agent (default `openai/gpt-oss-120b`);
  - `EVAL_CUSTOMER_MODEL`: the simulated customer (default: the agent's model, temperature 0.7);
  - `EVAL_JUDGE_MODEL`: the judge (default `deepseek-ai/DeepSeek-V3-0324`, temperature 0; keep it
    a different model family from the agent so it does not grade its own style).
- `data/local/credit_sources.db` (see [`credit-sources.md`](credit-sources.md)).
- For real retrieval (`--retrieval rag`): the knowledge Postgres running and ingested
  (`docker compose -f infrastructure/local/docker-compose.yml up -d`, see [`rag-local.md`](rag-local.md))
  and `ORCHESTRATOR_DATABASE_URL` pointing at it. The run loads BGE-M3 in-process.

### Run RAG runs outside Claude Code

Claude Code's memory guard kills large processes it launches, and `--retrieval rag` loads BGE-M3.
Run RAG runs **in your own PowerShell window**. `--retrieval stub` needs no embedder or Postgres
and is fine for quick runs anywhere (search results are canned, so the RAG scenario's citation
checks are not meaningful with it).

## Run

All scenarios, three runs each, retrieval from `ORCHESTRATOR_RETRIEVAL`:

```powershell
.\.venv\Scripts\python -m scripts.eval.run_scenarios
```

Real RAG, one run of every scenario:

```powershell
.\.venv\Scripts\python -m scripts.eval.run_scenarios --retrieval rag --runs 1
```

Quick run without the embedder, one scenario:

```powershell
.\.venv\Scripts\python -m scripts.eval.run_scenarios --retrieval stub --runs 1 --scenario knows_loan
```

Options:

| option | default | meaning |
|---|---|---|
| `--scenario ID` | all | scenario id; repeat for several |
| `--runs N` | 3 | runs per scenario |
| `--retrieval rag\|stub` | `ORCHESTRATOR_RETRIEVAL` | knowledge search backend |
| `--max-turns N` | 25 | customer turns per conversation |
| `--out DIR` | `data/local/eval/<UTC yyyymmdd-HHMMSS>` | output directory |
| `--agent-model NAME` | `ORCHESTRATOR_MODEL` | agent model override |

Progress goes to stderr, one line per conversation; the last stdout line is the report path.
Exit code 0 means the report was written (agent failures are results, not errors); 2 means a
configuration error (unknown scenario, missing settings or credit database).

The orchestrator clock is pinned to 2026-10-28 12:00 UTC (the dataset date), sessions are kept
in memory, and uploads go to `<out>/uploads`. The uploaded documents are generated per customer
from `config/orchestrator/customers.yaml` with a checksum-valid CNP.

## Output

`data/local/eval/<run_id>/` (ignored by Git; never commit it):

- `report.md`: scenario table (stop reasons, simulator errors, judge errors), trace-check table
  (`pass / fail / n/a / runs` per scenario and check), judge-criteria table (`passed / graded`),
  then per run: transcript, check results with evidence, judge grades with reasons, trace link;
- `results.json`: the same, machine-readable;
- `traces/<session_id>.jsonl` and `traces/<session_id>.md`: the raw and rendered agent trace.

Reading the results:

- `n/a` means the check's precondition never happened (no product chosen, no switch marked,
  the later tool never ran, no trace); it is neither a pass nor a fail.
- A `customer_error` stop (the simulator produced invalid output twice, or chose an action the
  agent had not offered twice) and a judge error are evaluation failures. They are counted in their
  own columns and never as agent results. Rerun the scenario.
- An `agent_error` stop (HTTP error from the chat API, for example 503 when the model is
  unavailable) is an agent result; the checks still run on the partial trace.

## Adding a scenario

Append an entry to `config/eval/scenarios.yaml` (`id`, `customer_id`, `brief`, `stop_when`,
`checks`, `rubric`). Check names and parameters are documented in `scripts/eval/checks.py`; an
unknown check name or a missing required parameter fails the run at start-up (exit 2). Keep the brief's figures equal to the customer's
entry in `config/orchestrator/customers.yaml`, since the uploaded documents carry those figures.
