"""Deterministic checks over one session's trace events.

Events follow docs/superpowers/specs/2026-10-29-agent-trace-design.md §4.1.
Customer turns are numbered from 1 in `turn_started` order; the greeting turn
(`event.kind == "session_started"`) is turn 0 and never counts as a customer turn.

A check whose precondition never occurred (no trace, no product chosen, no
switch marked, the later tool never ran) is `not_applicable`, never `pass`.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel

Status = Literal["pass", "fail", "not_applicable"]

REJECTION_CODES = {"unknown_tool", "not_model_callable", "not_allowed_in_flow", "precondition_failed", "invalid_arguments"}
FAILED_OUTCOMES = {"fallback", "step_cap", "model_unavailable", "error"}
SEARCH_TOOL = "search_banking_policies"


class CheckResult(BaseModel):
    check: str
    status: Status
    evidence: list[str] = []
    params: dict = {}


def load_events(path: Path) -> list[dict]:
    """Trace events from a JSONL file; [] if the file is missing or empty. Unparseable lines are skipped."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    events = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


# ---- trace view -----------------------------------------------------------

@dataclass
class _Product:
    index: int
    turn_id: str | None
    step: int | None
    value: Any


@dataclass
class _Trace:
    events: list[dict]
    switch_turn_ids: list[str]
    turn_numbers: dict[str, int] = field(default_factory=dict)
    products: list[_Product] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = 0
        for e in self.events:
            if e.get("type") != "turn_started" or e.get("turn_id") in self.turn_numbers:
                continue
            if (e.get("event") or {}).get("kind") == "session_started":
                self.turn_numbers[e["turn_id"]] = 0
            else:
                n += 1
                self.turn_numbers[e["turn_id"]] = n
        self.products = self._accepted_products()

    def _accepted_products(self) -> list[_Product]:
        """Accepted product_code values: the action_parsed proposal of the same turn+step whose result was accepted."""
        found = []
        for i, e in enumerate(self.events):
            if e.get("type") != "field_updates":
                continue
            if not any(r.get("field") == "product_code" and r.get("accepted") for r in e.get("results") or []):
                continue
            proposal = next(
                (p for p in reversed(self.events[:i]) if p.get("type") == "action_parsed"
                 and p.get("turn_id") == e.get("turn_id") and p.get("step") == e.get("step")),
                None,
            )
            update = next((u for u in (proposal or {}).get("field_updates") or [] if u.get("field") == "product_code"), None)
            if update is not None:
                found.append(_Product(i, e.get("turn_id"), e.get("step"), update.get("value")))
        return found

    def turn(self, e: dict) -> int:
        return self.turn_numbers.get(e.get("turn_id"), 0)

    def where(self, e: dict) -> str:
        step = e.get("step")
        return f"turn {self.turn(e)}" + (f" step {step}" if step is not None else "")

    def of_type(self, type: str) -> list[tuple[int, dict]]:
        return [(i, e) for i, e in enumerate(self.events) if e.get("type") == type]

    def tool_calls(self, tools: set[str] | None = None, caller: str = "any", ok: bool | None = None) -> list[tuple[int, dict]]:
        return [
            (i, e) for i, e in self.of_type("tool_call")
            if (tools is None or e.get("tool") in tools)
            and (caller == "any" or e.get("caller") == caller)
            and (ok is None or bool(e.get("ok")) == ok)
        ]

    def describe_call(self, e: dict) -> str:
        status = "ok" if e.get("ok") else f"error {e.get('error_code')}"
        return f"{self.where(e)}: {e.get('tool')} ({e.get('caller')}) {status}"

    def describe_product(self, p: _Product) -> str:
        return self.where({"turn_id": p.turn_id, "step": p.step}) + f": product_code = {p.value}"


Outcome = tuple[Status, list[str]]


# ---- checks ---------------------------------------------------------------

def _intent_seen(t: _Trace, intent: str, within_turns: int | None = None) -> Outcome:
    seen = [e for _, e in t.of_type("action_parsed") if e.get("intent") == intent and t.turn(e) > 0
            and (within_turns is None or t.turn(e) <= within_turns)]
    if seen:
        return "pass", [f"{t.where(e)}: intent {intent}" for e in seen]
    intents = [f"{t.where(e)}: intent {e.get('intent')}" for _, e in t.of_type("action_parsed") if t.turn(e) > 0]
    return "fail", intents or ["no parsed actions"]


def _tool_called(t: _Trace, tool: str, caller: str = "model", min: int = 1, max: int | None = None) -> Outcome:
    calls = t.tool_calls({tool}, caller)
    count = sum(1 for _, e in calls if e.get("ok"))
    ok = count >= min and (max is None or count <= max)
    return ("pass" if ok else "fail"), [t.describe_call(e) for _, e in calls] or [f"no {caller} call of {tool}"]


def _tool_not_called(t: _Trace, tool: str, caller: str = "any") -> Outcome:
    calls = t.tool_calls({tool}, caller)
    return ("fail" if calls else "pass"), [t.describe_call(e) for _, e in calls] or [f"no {caller} call of {tool}"]


def _tool_order(t: _Trace, before: str, after: str) -> Outcome:
    first_after = next(iter(t.tool_calls({after}, ok=True)), None)
    if first_after is None:
        return "not_applicable", [f"{after} never succeeded"]
    first_before = next(iter(t.tool_calls({before}, ok=True)), None)
    evidence = [t.describe_call(first_after[1])]
    if first_before is None:
        return "fail", [f"{before} never succeeded", *evidence]
    evidence.insert(0, t.describe_call(first_before[1]))
    return ("pass" if first_before[0] < first_after[0] else "fail"), evidence


def _first_product(t: _Trace) -> _Product | None:
    return t.products[0] if t.products else None


def _tool_before_product(t: _Trace, tools: list[str]) -> Outcome:
    product = _first_product(t)
    if product is None:
        return "not_applicable", ["no accepted product_code"]
    calls = [e for i, e in t.tool_calls(set(tools), ok=True) if i < product.index]
    evidence = [t.describe_call(e) for e in calls] + [t.describe_product(product)]
    return ("pass" if calls else "fail"), evidence


def _no_tool_before_product(t: _Trace, tool: str) -> Outcome:
    product = _first_product(t)
    if product is None:
        return "not_applicable", ["no accepted product_code"]
    calls = [e for i, e in t.tool_calls({tool}) if i < product.index]
    evidence = [t.describe_call(e) for e in calls] + [t.describe_product(product)]
    return ("fail" if calls else "pass"), evidence


def _clarifying_before_product(t: _Trace, min_replies: int = 1) -> Outcome:
    product = _first_product(t)
    if product is None:
        return "not_applicable", ["no accepted product_code"]
    replies = [e for i, e in t.of_type("turn_finished") if i < product.index and t.turn(e) > 0 and e.get("reply")]
    evidence = [f"{t.where(e)}: reply" for e in replies] + [t.describe_product(product)]
    return ("pass" if len(replies) >= min_replies else "fail"), evidence


def _product_final(t: _Trace, product: str | None = None, products: list[str] | None = None) -> Outcome:
    allowed = set(products or []) | ({product} if product is not None else set())
    if not allowed:
        raise ValueError("product_final needs product or products")
    if not t.products:
        return "not_applicable", ["no accepted product_code"]
    last = t.products[-1]
    return ("pass" if last.value in allowed else "fail"), [t.describe_product(p) for p in t.products]


def _product_changed(t: _Trace, **params: Any) -> Outcome:
    if "from" not in params or "to" not in params:
        raise ValueError("product_changed needs from and to")
    if not t.products:
        return "not_applicable", ["no accepted product_code"]
    start = next((k for k, p in enumerate(t.products) if p.value == params["from"]), None)
    changed = start is not None and any(p.value == params["to"] for p in t.products[start + 1:])
    return ("pass" if changed else "fail"), [t.describe_product(p) for p in t.products]


def _no_tool_after_switch(t: _Trace, tools: list[str]) -> Outcome:
    starts = [i for i, e in t.of_type("turn_started") if e.get("turn_id") in set(t.switch_turn_ids)]
    if not starts:
        return "not_applicable", ["no switch marked" if not t.switch_turn_ids else "switch turn not in trace"]
    start = starts[0]
    current = next((p.value for p in reversed(t.products) if p.index < start), None)
    change = next((p for p in t.products if p.index > start and p.value != current), None)
    end = change.index if change is not None else len(t.events)
    calls = [e for i, e in t.tool_calls(set(tools), caller="model") if start < i < end]
    evidence = [f"{t.where(t.events[start])}: switch"]
    evidence.append(t.describe_product(change) if change is not None else "no product change after the switch")
    evidence += [t.describe_call(e) for e in calls]
    return ("fail" if calls else "pass"), evidence


def _search_per_question(t: _Trace, min: int) -> Outcome:
    calls = t.tool_calls({SEARCH_TOOL}, caller="model", ok=True)
    return ("pass" if len(calls) >= min else "fail"), [t.describe_call(e) for _, e in calls] or ["no searches"]


def _cited_answers(t: _Trace, min: int) -> Outcome:
    cited = [e for _, e in t.of_type("turn_finished") if e.get("citations")]
    evidence = [f"{t.where(e)}: citations {', '.join(map(str, e['citations']))}" for e in cited]
    return ("pass" if len(cited) >= min else "fail"), evidence or ["no cited replies"]


def _no_model_tool_rejections(t: _Trace) -> Outcome:
    rejected = [e for _, e in t.tool_calls(caller="model", ok=False) if e.get("error_code") in REJECTION_CODES]
    return ("fail" if rejected else "pass"), [t.describe_call(e) for e in rejected]


def _no_failed_turns(t: _Trace) -> Outcome:
    failed = [e for _, e in t.of_type("turn_finished") if e.get("outcome") in FAILED_OUTCOMES]
    return ("fail" if failed else "pass"), [f"{t.where(e)}: outcome {e.get('outcome')}" for e in failed]


# name -> (function, defaults, required params)
_CHECKS: dict[str, tuple[Callable[..., Outcome], dict, tuple[str, ...]]] = {
    "intent_seen": (_intent_seen, {"within_turns": None}, ("intent",)),
    "tool_called": (_tool_called, {"caller": "model", "min": 1, "max": None}, ("tool",)),
    "tool_not_called": (_tool_not_called, {"caller": "any"}, ("tool",)),
    "tool_order": (_tool_order, {}, ("before", "after")),
    "tool_before_product": (_tool_before_product, {}, ("tools",)),
    "no_tool_before_product": (_no_tool_before_product, {}, ("tool",)),
    "clarifying_before_product": (_clarifying_before_product, {"min_replies": 1}, ()),
    "product_final": (_product_final, {}, ()),
    "product_changed": (_product_changed, {}, ("from", "to")),
    "no_tool_after_switch": (_no_tool_after_switch, {}, ("tools",)),
    "search_per_question": (_search_per_question, {}, ("min",)),
    "cited_answers": (_cited_answers, {}, ("min",)),
    "no_model_tool_rejections": (_no_model_tool_rejections, {}, ()),
    "no_failed_turns": (_no_failed_turns, {}, ()),
}


def run_check(spec: dict, events: list[dict], *, switch_turn_ids: list[str] = []) -> CheckResult:
    """Run one check; `spec["check"]` names it, the other keys are its params. Unknown name or bad params: ValueError."""
    name = spec.get("check")
    if name not in _CHECKS:
        raise ValueError(f"unknown check: {name!r}")
    fn, defaults, required = _CHECKS[name]
    params = {**defaults, **{k: v for k, v in spec.items() if k != "check"}}
    missing = [p for p in required if p not in params]
    if missing:
        raise ValueError(f"check {name} missing params: {', '.join(missing)}")
    if not events:
        return CheckResult(check=name, status="not_applicable", evidence=["no trace"], params=params)
    try:
        status, evidence = fn(_Trace(list(events), list(switch_turn_ids)), **params)
    except TypeError as e:
        raise ValueError(f"check {name}: bad params: {e}") from e
    return CheckResult(check=name, status=status, evidence=evidence, params=params)


def run_checks(specs: list[dict], events: list[dict], *, switch_turn_ids: list[str] = []) -> list[CheckResult]:
    """Run every check in order over the same events."""
    return [run_check(spec, events, switch_turn_ids=switch_turn_ids) for spec in specs]
