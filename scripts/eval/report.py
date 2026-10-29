"""Markdown and JSON report over evaluation runs.

Agent check counts and judge criteria are kept apart from simulator/judge errors:
a broken simulator (`customer_error`) or judge (`judge_error`) never counts as an
agent pass or fail.
"""
import json
from pathlib import Path

from pydantic import BaseModel

from scripts.eval.checks import CheckResult
from scripts.eval.driver import ConversationResult
from scripts.eval.judge import JudgeResult
from scripts.trace_report import load_events, render_report

_STATUSES = ("pass", "fail", "not_applicable")


class RunRecord(BaseModel):
    scenario_id: str
    run_index: int
    conversation: ConversationResult
    checks: list[CheckResult]
    judge: JudgeResult | None = None
    judge_error: str | None = None


def _label(result: CheckResult) -> str:
    params = ", ".join(f"{k}={v}" for k, v in result.params.items() if v is not None)
    return f"{result.check}({params})" if params else result.check


def _scenario_order(records: list[RunRecord]) -> list[str]:
    return list(dict.fromkeys(r.scenario_id for r in records))


def _summary(records: list[RunRecord]) -> dict:
    scenarios, checks, criteria = [], [], []
    for sid in _scenario_order(records):
        runs = [r for r in records if r.scenario_id == sid]
        stops: dict[str, int] = {}
        for r in runs:
            stops[r.conversation.stop_reason] = stops.get(r.conversation.stop_reason, 0) + 1
        scenarios.append({
            "scenario_id": sid, "runs": len(runs), "stop_reasons": stops,
            "customer_errors": sum(r.conversation.stop_reason == "customer_error" for r in runs),
            "judge_errors": sum(r.judge_error is not None for r in runs),
        })
        # Checks are matched by position in the scenario's list (one scenario may use a check twice).
        labels: dict[int, str] = {}
        counts: dict[int, dict[str, int]] = {}
        for r in runs:
            for k, c in enumerate(r.checks):
                labels.setdefault(k, _label(c))
                bucket = counts.setdefault(k, {s: 0 for s in _STATUSES} | {"runs": 0})
                bucket[c.status] += 1
                bucket["runs"] += 1
        checks += [{"scenario_id": sid, "check": labels[k], "counts": counts[k]} for k in sorted(labels)]
        # Judge criteria: general ones over every graded reply, scenario ones once per judged run.
        # `pass: null` (situation never occurred) counts as not applicable, apart from pass/fail.
        graded: dict[tuple[str, str], dict[str, int]] = {}

        def add(kind: str, name: str, grade) -> None:
            bucket = graded.setdefault((kind, name), {"passed": 0, "failed": 0, "not_applicable": 0, "graded": 0})
            bucket["passed" if grade.pass_ else "not_applicable" if grade.pass_ is None else "failed"] += 1
            bucket["graded"] += 1

        for r in runs:
            if r.judge is None:
                continue
            for reply in r.judge.replies:
                for name, g in reply.scores.items():
                    add("reply", name, g)
            for name, g in r.judge.scenario.items():
                add("scenario", name, g)
        criteria += [{"scenario_id": sid, "kind": kind, "criterion": name, **counts}
                     for (kind, name), counts in graded.items()]
    return {"scenarios": scenarios, "checks": checks, "criteria": criteria}


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _quote(text: str) -> list[str]:
    return [f"> {line}" if line else ">" for line in (text or "(no reply)").splitlines()]


def _verdict(grade) -> str:
    return "n/a" if grade.pass_ is None else "pass" if grade.pass_ else "FAIL"


def _render_trace(record: RunRecord, out_dir: Path) -> str | None:
    """Render the session trace to traces/<session_id>.md; the relative link, or None without a trace."""
    conv = record.conversation
    if not conv.session_id or not Path(conv.trace_path).exists():
        return None
    target = out_dir / "traces" / f"{conv.session_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(load_events(Path(conv.trace_path))), encoding="utf-8")
    return f"traces/{conv.session_id}.md"


def _markdown(records: list[RunRecord], summary: dict, links: dict[int, str | None]) -> str:
    lines = ["# Conversation evaluation", ""]
    lines += ["## Scenarios", "",
              "Simulator and judge errors are evaluation failures, not agent results.", "",
              "| scenario | runs | stop reasons | simulator errors | judge errors |",
              "|---|---|---|---|---|"]
    for s in summary["scenarios"]:
        stops = ", ".join(f"{k}: {v}" for k, v in s["stop_reasons"].items())
        lines.append(f"| {s['scenario_id']} | {s['runs']} | {stops} | {s['customer_errors']} | {s['judge_errors']} |")
    lines += ["", "## Trace checks", "", "| scenario | check | pass / fail / n/a / runs |", "|---|---|---|"]
    for c in summary["checks"]:
        n = c["counts"]
        lines.append(f"| {c['scenario_id']} | {_cell(c['check'])} | "
                     f"{n['pass']} / {n['fail']} / {n['not_applicable']} / {n['runs']} |")
    lines += ["", "## Judge criteria", "", "| scenario | kind | criterion | pass / fail / n/a / graded |",
              "|---|---|---|---|"]
    for c in summary["criteria"]:
        lines.append(f"| {c['scenario_id']} | {c['kind']} | {_cell(c['criterion'])} | "
                     f"{c['passed']} / {c['failed']} / {c['not_applicable']} / {c['graded']} |")

    for k, r in enumerate(records):
        conv = r.conversation
        lines += ["", f"## {r.scenario_id}, run {r.run_index}", "",
                  f"- Stop reason: `{conv.stop_reason}`"]
        if conv.error:
            lines.append(f"- Error: {_cell(conv.error)}")
        if conv.session_id:
            lines.append(f"- Session: `{conv.session_id}`")
        if links.get(k):
            lines.append(f"- Trace: [{links[k]}]({links[k]})")
        if conv.switch_turn_ids:
            lines.append(f"- Switch turns: {', '.join(conv.switch_turn_ids)}")
        lines += ["", "### Transcript", ""]
        if not conv.transcript:
            lines.append("(no turns)")
        for item in conv.transcript:
            lines.append(f"**Turn {item.get('turn')}, customer:** {item.get('customer', '')}")
            lines.append("")
            lines += _quote(item.get("agent", ""))
            meta = []
            if item.get("awaiting_before"):
                meta.append("awaiting before: " + ", ".join(item["awaiting_before"]))
            if item.get("tool_results"):
                meta.append("tools: " + ", ".join(item["tool_results"]))
            if item.get("blocks"):
                meta.append("shown: " + "; ".join(item["blocks"]))
            if meta:
                lines += ["", f"*{'; '.join(meta)}*"]
            lines.append("")
        lines += ["### Checks", ""]
        for c in r.checks:
            lines.append(f"- **{c.status}** {_cell(_label(c))}")
            lines += [f"  - {_cell(e)}" for e in c.evidence]
        lines += ["", "### Judge", ""]
        if r.judge_error:
            lines.append(f"Judge error (not an agent result): {_cell(r.judge_error)}")
        elif r.judge is None:
            lines.append("(not judged)")
        else:
            for reply in r.judge.replies:
                lines.append(f"- Turn {reply.turn}:")
                lines += [f"  - {_verdict(g)}: {_cell(name)} ({_cell(g.reason)})"
                          for name, g in reply.scores.items()]
            lines.append("- Scenario:")
            lines += [f"  - {_verdict(g)}: {_cell(name)} ({_cell(g.reason)})"
                      for name, g in r.judge.scenario.items()]
    return "\n".join(lines) + "\n"


def write_report(records: list[RunRecord], out_dir: Path) -> Path:
    """Write report.md, results.json and traces/<session_id>.md; returns the report.md path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    links = {k: _render_trace(r, out_dir) for k, r in enumerate(records)}
    summary = _summary(records)
    results = {"summary": summary,
               "records": [r.model_dump(mode="json", by_alias=True) for r in records]}
    (out_dir / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    path = out_dir / "report.md"
    path.write_text(_markdown(records, summary, links), encoding="utf-8")
    return path
