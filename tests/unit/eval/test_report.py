"""Report: summary pass rates, separate simulator/judge errors, rendered traces."""
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.eval.checks import CheckResult
from scripts.eval.driver import ConversationResult
from scripts.eval.judge import JudgeResult
from scripts.eval.report import RunRecord, write_report

TMP_ROOT = Path(__file__).parent / ".test_tmp"


@pytest.fixture
def out_dir():
    path = TMP_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def conversation(out_dir: Path, session_id: str, stop_reason: str = "customer_done",
                 error: str | None = None) -> ConversationResult:
    traces = out_dir / "traces"
    traces.mkdir(exist_ok=True)
    trace_path = traces / f"{session_id}.jsonl"
    trace_path.write_text(json.dumps({
        "ts": "2026-10-28T12:00:00+00:00", "session_id": session_id, "turn_id": None, "step": None,
        "type": "session_started", "customer_id": "cust-elena-popa", "model": "fake",
    }) + "\n", encoding="utf-8")
    return ConversationResult(
        scenario_id="knows_loan", session_id=session_id, stop_reason=stop_reason,
        transcript=[{"turn": 1, "turn_id": "t1", "customer": "I want a loan", "agent": "How much?",
                     "awaiting_before": ["missing_field amount"], "tool_results": []}],
        switch_turn_ids=[], trace_path=trace_path, error=error,
    )


def judged(ok: bool) -> JudgeResult:
    return JudgeResult.model_validate({
        "replies": [{"turn": 1, "scores": {"Uses clear, plain English.": {"pass": ok, "reason": "short"}}}],
        "scenario": {"Explains the outcome.": {"pass": True, "reason": "it did"}},
    })


def record(out_dir, index, status, *, judge=None, judge_error=None, **conv) -> RunRecord:
    return RunRecord(
        scenario_id="knows_loan", run_index=index,
        conversation=conversation(out_dir, f"s{index}", **conv),
        checks=[CheckResult(check="no_failed_turns", status=status, evidence=[f"evidence {index}"])],
        judge=judge, judge_error=judge_error,
    )


def test_report_summarises_pass_rates(out_dir):
    records = [record(out_dir, 1, "pass", judge=judged(True)), record(out_dir, 2, "fail", judge=judged(False))]
    path = write_report(records, out_dir)
    assert path == out_dir / "report.md"
    text = path.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if "| no_failed_turns |" in line)
    assert "1 / 1 / 0 / 2" in row
    assert "evidence 2" in text  # per-run evidence
    assert "short" in text  # judge reasons
    criterion = next(line for line in text.splitlines() if "Uses clear, plain English." in line and "/" in line)
    assert "1 / 2" in criterion
    assert (out_dir / "traces" / "s1.md").exists() and (out_dir / "traces" / "s2.md").exists()
    assert "traces/s1.md" in text
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert len(results["records"]) == 2
    assert results["records"][0]["judge"]["replies"][0]["scores"]["Uses clear, plain English."]["pass"] is True
    assert results["summary"]["checks"][0]["counts"] == {"pass": 1, "fail": 1, "not_applicable": 0, "runs": 2}


def test_report_separates_judge_errors(out_dir):
    records = [
        record(out_dir, 1, "pass", judge=judged(True)),
        record(out_dir, 2, "pass", judge_error="EvalModelError: judge returned invalid output twice"),
        record(out_dir, 3, "not_applicable", stop_reason="customer_error", error="simulated customer broke"),
    ]
    text = write_report(records, out_dir).read_text(encoding="utf-8")
    # Agent check counts are unaffected by evaluation errors.
    row = next(line for line in text.splitlines() if "| no_failed_turns |" in line)
    assert "2 / 0 / 1 / 3" in row
    # Judge criteria counted only over judged runs.
    criterion = next(line for line in text.splitlines() if "Uses clear, plain English." in line and "/" in line)
    assert "1 / 1" in criterion
    # The scenario row reports 1 simulator error and 1 judge error in their own columns.
    scenario_row = next(line for line in text.splitlines() if line.startswith("| knows_loan | 3 |"))
    cells = [c.strip() for c in scenario_row.strip("|").split("|")]
    assert cells[-2:] == ["1", "1"]
    assert "judge returned invalid output twice" in text
    assert "simulated customer broke" in text
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert results["summary"]["scenarios"][0]["customer_errors"] == 1
    assert results["summary"]["scenarios"][0]["judge_errors"] == 1
