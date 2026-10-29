"""run_scenarios CLI end to end, offline: DemoChatModel agent, fake customer and judge."""
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.credit_sources.setup import create_database
from scripts.eval import run_scenarios
from scripts.eval.judge import GENERAL_RUBRIC
from src.integrations.llm.chat import FakeChatModel

TMP_ROOT = Path(__file__).parent / ".test_tmp"


@pytest.fixture
def work_dir():
    path = TMP_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


JUDGE_OUTPUT = json.dumps({
    "replies": [{"turn": 1, "scores": {f"g{i}": {"pass": True, "reason": "fine"}
                                       for i in range(1, len(GENERAL_RUBRIC) + 1)}}],
    "scenario": {"s1": {"pass": True, "reason": "fine"},
                 "s2": {"pass": None, "reason": "no offers reached"},
                 "s3": {"pass": None, "reason": "no offers reached"}},  # knows_loan has three criteria
})


@pytest.fixture
def offline(monkeypatch, work_dir):
    monkeypatch.setenv("ORCHESTRATOR_MODEL", "fake")
    monkeypatch.setenv("ORCHESTRATOR_CREDIT_SOURCES_DB", str(create_database(work_dir / "credit_sources.db")))
    built = {}

    def fake_build(role, base):
        if role == "customer":
            model = FakeChatModel(['{"type": "say", "text": "I want a personal loan", "switch": false}',
                                   '{"type": "done", "reason": "enough"}'])
        else:
            model = FakeChatModel(lambda messages: JUDGE_OUTPUT)
        built[role] = (model, base)
        return model

    monkeypatch.setattr(run_scenarios, "build_eval_model", fake_build)
    return built


def test_cli_end_to_end_offline(offline, work_dir, capsys):
    out = work_dir / "run"
    code = run_scenarios.main(["--retrieval", "stub", "--runs", "1", "--scenario", "knows_loan", "--out", str(out)])
    assert code == 0
    assert (out / "report.md").exists() and (out / "results.json").exists()
    assert str(out / "report.md") in capsys.readouterr().out
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    [rec] = results["records"]
    assert rec["scenario_id"] == "knows_loan" and rec["run_index"] == 1
    assert rec["conversation"]["stop_reason"] == "customer_done"
    assert rec["judge"]["scenario"]
    assert rec["judge_error"] is None
    assert {c["check"] for c in rec["checks"]} >= {"no_failed_turns", "product_final"}
    session_id = rec["conversation"]["session_id"]
    assert (out / "traces" / f"{session_id}.jsonl").exists()
    assert (out / "traces" / f"{session_id}.md").exists()
    # The agent ran with the eval overrides.
    base = offline["judge"][1]
    assert base.trace == "file" and base.session_store == "memory" and base.retrieval == "stub"
    assert base.traces_dir == out / "traces"


def test_cli_judge_error_is_recorded_not_raised(offline, work_dir, monkeypatch):
    original = run_scenarios.build_eval_model

    def broken_judge(role, base):
        model = original(role, base)
        if role == "judge":
            return FakeChatModel(["not json", "still not json"])
        return model

    monkeypatch.setattr(run_scenarios, "build_eval_model", broken_judge)
    out = work_dir / "run"
    assert run_scenarios.main(["--retrieval", "stub", "--runs", "1", "--scenario", "knows_loan", "--out", str(out)]) == 0
    rec = json.loads((out / "results.json").read_text(encoding="utf-8"))["records"][0]
    assert rec["judge"] is None and "invalid output twice" in rec["judge_error"]


def test_cli_unknown_scenario_is_configuration_error(offline, work_dir, capsys):
    code = run_scenarios.main(["--retrieval", "stub", "--scenario", "nope", "--out", str(work_dir / "run")])
    assert code == 2
    assert "nope" in capsys.readouterr().err
