"""Run conversation-evaluation scenarios against the real agent and write a report.

    python -m scripts.eval.run_scenarios [--scenario ID ...] [--runs 3] [--retrieval rag|stub]
        [--max-turns 25] [--out data/local/eval/<run_id>] [--agent-model NAME]

Exit 0 when the report is written (agent failures are results), 2 on configuration errors.
See docs/runbooks/conversation-eval.md.
"""
import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from scripts.eval.checks import load_events, run_check, run_checks
from scripts.eval.customer import SimulatedCustomer
from scripts.eval.driver import build_eval_app, customer_documents, load_scenarios, run_conversation
from scripts.eval.judge import judge_conversation
from scripts.eval.models import build_eval_model
from scripts.eval.report import RunRecord, write_report
from src.core.errors import ConfigurationError
from src.core.settings import load_orchestrator_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_PATH = REPO_ROOT / "config" / "eval" / "scenarios.yaml"
EVAL_ROOT = REPO_ROOT / "data" / "local" / "eval"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m scripts.eval.run_scenarios", description=__doc__.split("\n\n")[0])
    p.add_argument("--scenario", action="append", default=[], help="scenario id (repeatable; default: all)")
    p.add_argument("--runs", type=int, default=3, help="runs per scenario (default 3)")
    p.add_argument("--retrieval", choices=["rag", "stub"], default=None, help="default: ORCHESTRATOR_RETRIEVAL")
    p.add_argument("--max-turns", type=int, default=25, help="customer turns per conversation (default 25)")
    p.add_argument("--out", type=Path, default=None, help="default: data/local/eval/<UTC yyyymmdd-HHMMSS>")
    p.add_argument("--agent-model", default=None, help="override ORCHESTRATOR_MODEL for the agent")
    return p


def _log(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    out = Path(args.out) if args.out else EVAL_ROOT / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    try:
        if args.runs < 1 or args.max_turns < 1:
            raise ConfigurationError("--runs and --max-turns must be at least 1")
        scenarios = load_scenarios(SCENARIOS_PATH)
        if args.scenario:
            known = {s.id for s in scenarios}
            unknown = [s for s in args.scenario if s not in known]
            if unknown:
                raise ConfigurationError(f"unknown scenario(s): {', '.join(unknown)}; known: {', '.join(sorted(known))}")
            scenarios = [s for s in scenarios if s.id in set(args.scenario)]
        for s in scenarios:
            for spec in s.checks:
                run_check(spec, [])  # unknown check name or missing params: ValueError before any run
        base = load_orchestrator_settings()
        update = {"trace": "file", "traces_dir": out / "traces", "session_store": "memory",
                  "uploads_dir": out / "uploads"}
        if args.retrieval:
            update["retrieval"] = args.retrieval
        if args.agent_model:
            update["model"] = args.agent_model
        settings = base.model_copy(update=update)
        customer_model = build_eval_model("customer", settings)
        judge_model = build_eval_model("judge", settings)
        documents = {s.customer_id: customer_documents(s.customer_id, settings.config_dir,
                                                       settings.credit_sources_db, settings.customer_bindings_path)
                     for s in scenarios}
        app = build_eval_app(settings)
    except (ConfigurationError, ValidationError, ValueError, OSError, sqlite3.Error) as e:
        _log(f"configuration error: {type(e).__name__}: {e}")
        return 2

    _log(f"agent model {settings.model}, retrieval {settings.retrieval}; writing to {out}")
    records: list[RunRecord] = []
    for scenario in scenarios:
        for run_index in range(1, args.runs + 1):
            conv = run_conversation(app, scenario, SimulatedCustomer(customer_model, scenario.brief),
                                    max_turns=args.max_turns, documents=documents[scenario.customer_id],
                                    traces_dir=settings.traces_dir)
            checks = run_checks(scenario.checks, load_events(conv.trace_path), switch_turn_ids=conv.switch_turn_ids)
            judge, judge_error = None, None
            if conv.transcript:
                try:
                    judge = judge_conversation(judge_model, conv.transcript, scenario.rubric)
                except Exception as e:  # judge failure: an evaluation error, never an agent result
                    judge_error = f"{type(e).__name__}: {e}"
            records.append(RunRecord(scenario_id=scenario.id, run_index=run_index, conversation=conv,
                                     checks=checks, judge=judge, judge_error=judge_error))
            failed = sum(c.status == "fail" for c in checks)
            _log(f"{scenario.id} run {run_index}/{args.runs}: {conv.stop_reason}, {len(conv.transcript)} turns, "
                 f"{failed} failed checks" + (", judge error" if judge_error else ""))
    path = write_report(records, out)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
