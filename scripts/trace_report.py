#!/usr/bin/env python3
"""Readable trace report generator for agent decision traces.

Reads a session's trace JSONL file and renders it as a Markdown timeline
showing every model call, tool invocation, field update, and decision.

Note: Code tool calls triggered by field updates (e.g., eligibility checks) appear
before the field_updates event of the same step.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any


_skipped_lines_count = 0  # Module-level counter for skipped lines


def load_events(path: Path) -> list[dict]:
    """Load events from a JSONL trace file.

    Skips blank lines, non-JSON lines, and lines that aren't JSON objects or lack 'type'.

    Args:
        path: Path to the JSONL trace file

    Returns:
        List of event dictionaries

    Raises:
        FileNotFoundError: If the trace file doesn't exist
    """
    global _skipped_lines_count
    _skipped_lines_count = 0

    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")

    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                # Skip non-dict objects or dicts without 'type'
                if not isinstance(event, dict) or "type" not in event:
                    _skipped_lines_count += 1
                    continue
                events.append(event)
            except json.JSONDecodeError:
                # Skip corrupt lines
                _skipped_lines_count += 1
                continue

    return events


def get_skipped_lines_count() -> int:
    """Return the count of skipped lines from the last load_events call."""
    return _skipped_lines_count


def _safe_fence(text: str) -> tuple[str, str]:
    """Return fence markers that won't be broken by the text content.

    Returns:
        Tuple of (opening_fence, closing_fence)
    """
    # Start with triple backticks
    fence = "```"
    # If text contains triple backticks, use quadruple
    if "```" in text:
        fence = "````"
    # If text contains quadruple, use quintuple, etc.
    while fence in text:
        fence += "`"
    return fence, fence


def _summarize_output(output: Any, truncated: bool = False) -> str:
    """Create a one-line summary of tool output.

    Args:
        output: Tool output value
        truncated: Whether the output was truncated

    Returns:
        One-line summary string
    """
    if truncated:
        return "(truncated)"

    if output is None:
        return "null"
    elif isinstance(output, str):
        if len(output) < 100:
            return f'"{output}"'
        return f'"{output[:97]}..."'
    elif isinstance(output, dict):
        keys = list(output.keys())
        return f"dict with keys: {', '.join(keys[:5])}" + ("..." if len(keys) > 5 else "")
    elif isinstance(output, list):
        return f"list[{len(output)}]"
    else:
        s = str(output)
        return s[:100] if len(s) > 100 else s


def render_report(events: list[dict], *, full: bool = False) -> str:
    """Render a trace report as Markdown.

    Args:
        events: List of trace event dictionaries
        full: If True, include full context JSON and tool outputs

    Returns:
        Markdown-formatted report string
    """
    if not events:
        return "# Agent Decision Trace\n\nNo events found.\n"

    lines = []

    # Header
    lines.append("# Agent Decision Trace\n")

    # Check for skipped lines
    skipped = get_skipped_lines_count()
    if skipped > 0:
        lines.append(f"*Note: {skipped} unreadable line{'s' if skipped != 1 else ''} skipped*\n")

    # Find session_started or system_prompt_changed event for header info
    session_started = next((e for e in events if e.get("type") == "session_started"), None)
    first_prompt_event = next((e for e in events if e.get("type") in ("session_started", "system_prompt_changed")), None)

    # Render header even if session_started is missing
    if session_started:
        lines.append(f"**Session:** `{session_started['session_id']}`  ")
        lines.append(f"**Customer:** `{session_started['customer_id']}`  ")
        lines.append(f"**Model:** {session_started.get('model', 'unknown')}  ")
        lines.append(f"**Prompt version:** {session_started.get('prompt_version', 'unknown')}  ")
        lines.append(f"**Started:** {session_started.get('ts', 'unknown')}  ")
        lines.append("")
    elif events:
        # Fallback: try to extract session_id from first event
        first_event = events[0]
        session_id = first_event.get("session_id", "unknown")
        lines.append(f"**Session:** `{session_id}`  ")
        lines.append(f"**Started:** {first_event.get('ts', 'unknown')}  ")
        lines.append("")

    # System prompt in collapsed details (from session_started or system_prompt_changed)
    if first_prompt_event and "system_prompt" in first_prompt_event:
        prompt_text = first_prompt_event["system_prompt"]
        open_fence, close_fence = _safe_fence(prompt_text)
        lines.append("<details>")
        lines.append("<summary>System Prompt</summary>")
        lines.append("")
        lines.append(open_fence)
        lines.append(prompt_text)
        lines.append(close_fence)
        lines.append("</details>")
        lines.append("")

    # Render session-level events (turn_id is null)
    session_level_events = [e for e in events if e.get("turn_id") is None and e.get("type") not in ("session_started",)]
    for event in session_level_events:
        event_type = event.get("type", "unknown")
        if event_type == "system_prompt_changed":
            # Already handled above if it's the first prompt event
            if event != first_prompt_event:
                lines.append(f"### System prompt changed")
                lines.append(f"**Version:** {event.get('prompt_version', 'unknown')}")
                lines.append("")
        else:
            # Unknown session-level event - render raw
            lines.append(f"**Session event:** `{event_type}`")
            open_fence, close_fence = _safe_fence(json.dumps(event, indent=2, ensure_ascii=False))
            lines.append(open_fence + "json")
            lines.append(json.dumps(event, indent=2, ensure_ascii=False))
            lines.append(close_fence)
            lines.append("")

    # Group events by turn (skip session-level events, already rendered)
    turns = {}
    for event in events:
        turn_id = event.get("turn_id")
        if turn_id is not None:
            if turn_id not in turns:
                turns[turn_id] = []
            turns[turn_id].append(event)

    # Render each turn
    turn_number = 0
    for turn_id, turn_events in turns.items():
        turn_number += 1

        # Find turn_started and turn_finished for the heading
        turn_start = next((e for e in turn_events if e.get("type") == "turn_started"), None)
        turn_finish = next((e for e in turn_events if e.get("type") == "turn_finished"), None)

        if turn_start:
            event_kind = turn_start.get("event", {}).get("kind", "unknown")
            stage_before = turn_start.get("stage")
            stage_after = turn_finish.get("stage_after") if turn_finish else None
            duration_ms = turn_finish.get("duration_ms") if turn_finish else None

            # Format stage transition with "—" instead of "None → None"
            if stage_before is None and stage_after is None:
                stage_transition = "—"
            elif stage_before is None:
                stage_transition = f"— → {stage_after}"
            elif stage_after is None:
                stage_transition = f"{stage_before} → —"
            else:
                stage_transition = f"{stage_before} → {stage_after}"

            duration_str = f"{duration_ms} ms" if duration_ms is not None else "?"

            lines.append(f"## Turn {turn_number} — {event_kind} ({stage_transition}, {duration_str})")
            lines.append("")

        # Detect discarded replies: a respond action_parsed followed by another model_call
        discarded_reply_steps = set()
        for i, event in enumerate(turn_events):
            if event.get("type") == "action_parsed" and event.get("action", {}).get("type") == "respond":
                # Check if next model_call has same or later step
                current_step = event.get("step")
                for j in range(i + 1, len(turn_events)):
                    next_event = turn_events[j]
                    if next_event.get("type") == "model_call" and next_event.get("step", 0) > current_step:
                        discarded_reply_steps.add(current_step)
                        break

        # Render events in order
        for event_idx, event in enumerate(turn_events):
            event_type = event.get("type")

            if event_type == "turn_started":
                # Show event details
                event_data = event.get("event", {})
                if "text" in event_data:
                    lines.append(f"**Event:** Customer message: \"{event_data['text'][:100]}...\"" if len(event_data['text']) > 100 else f"**Event:** Customer message: \"{event_data['text']}\"")
                elif event_data.get("kind") == "document_uploaded":
                    lines.append(f"**Event:** Document uploaded ({event_data.get('doc_type')}, {event_data.get('size_bytes')} bytes)")
                else:
                    lines.append(f"**Event:** {event_data.get('kind', 'unknown')}")
                lines.append("")

            elif event_type == "system_prompt_changed":
                lines.append(f"### System prompt changed")
                lines.append(f"**Version:** {event.get('prompt_version')}")
                lines.append("")

            elif event_type == "model_call":
                step = event.get("step")
                lines.append(f"### Step {step}: Model call")
                lines.append(f"- **Latency:** {event.get('latency_ms', '?')} ms")

                usage = event.get("usage")
                if usage:
                    lines.append(f"- **Tokens:** {usage.get('prompt_tokens', 0)} prompt + {usage.get('completion_tokens', 0)} completion = {usage.get('total_tokens', 0)} total")

                notices = event.get("notices", [])
                if notices:
                    lines.append(f"- **Notices:** {', '.join(notices)}")

                needs = event.get("context", {}).get("needs", [])
                if needs:
                    needs_summary = ", ".join([f"{n['kind']}" + (f"({n.get('target', '')})" if n.get('target') else "") for n in needs[:3]])
                    lines.append(f"- **Needs:** {needs_summary}")

                if event.get("error"):
                    error = event["error"]
                    lines.append(f"- **Error:** {error.get('code', 'unknown')}: {error.get('message', 'unknown')}")

                # Show raw_output (first ~200 chars by default)
                raw_output = event.get("raw_output")
                if raw_output:
                    if full:
                        open_fence, close_fence = _safe_fence(raw_output)
                        lines.append("")
                        lines.append("**Raw output:**")
                        lines.append(open_fence)
                        lines.append(raw_output)
                        lines.append(close_fence)
                    else:
                        excerpt = raw_output[:200] if len(raw_output) > 200 else raw_output
                        lines.append(f"- **Raw output:** `{excerpt}`" + ("..." if len(raw_output) > 200 else ""))

                if full and "context" in event:
                    lines.append("")
                    lines.append("**Context:**")
                    context_json = json.dumps(event["context"], indent=2, ensure_ascii=False)
                    open_fence, close_fence = _safe_fence(context_json)
                    lines.append(open_fence + "json")
                    lines.append(context_json)
                    lines.append(close_fence)

                lines.append("")

            elif event_type == "action_parsed":
                intent = event.get("intent", "unknown")
                action = event.get("action", {})
                action_type = action.get("type", "unknown")
                step = event.get("step")

                # Check if this is a discarded reply
                is_discarded = step in discarded_reply_steps

                if is_discarded:
                    lines.append(f"**Reply discarded — model asked again (rejected field updates or notices)**")
                else:
                    lines.append(f"**Action parsed:** Intent={intent}, Type={action_type}")

                if action_type == "call_tool":
                    tool = action.get('tool', 'unknown')
                    arguments = action.get('arguments', {})
                    args_json = json.dumps(arguments, ensure_ascii=False)
                    lines.append(f"- Tool: `{tool}({args_json})`")
                elif action_type == "respond":
                    message = action.get("message", "")
                    excerpt = message[:200] if len(message) > 200 else message
                    lines.append(f"- Reply: \"{excerpt}\"")

                lines.append("")

            elif event_type == "action_invalid":
                will_retry = event.get("will_retry", False)
                step = event.get("step")
                lines.append(f"**Invalid action** (will retry: {will_retry})")
                lines.append(f"- Error: {event.get('error', 'unknown')}")

                # Find the corresponding model_call to get raw_output
                model_call = None
                for prev_event in reversed(turn_events[:event_idx]):
                    if prev_event.get("type") == "model_call" and prev_event.get("step") == step:
                        model_call = prev_event
                        break

                # Always show full raw_output for invalid actions
                if model_call and "raw_output" in model_call:
                    raw_output = model_call["raw_output"]
                    open_fence, close_fence = _safe_fence(raw_output)
                    lines.append("")
                    lines.append("**Raw output:**")
                    lines.append(open_fence)
                    lines.append(raw_output)
                    lines.append(close_fence)

                lines.append("")

            elif event_type == "field_updates":
                lines.append("**Field updates:**")
                for result in event.get("results", []):
                    field = result.get("field", "?")
                    accepted = result.get("accepted", False)
                    reason = result.get("reason", "")
                    if accepted:
                        lines.append(f"- ✓ {field}")
                    else:
                        lines.append(f"- ✗ {field} — {reason}")
                lines.append("")

            elif event_type == "tool_call":
                tool = event.get("tool", "?")
                caller = event.get("caller", "?")
                ok = event.get("ok", False)
                duration = event.get("duration_ms", "?")
                arguments = event.get("arguments", {})
                output = event.get("output")
                truncated = event.get("truncated", False)

                args_json = json.dumps(arguments, ensure_ascii=False)
                status = "✓" if ok else "✗"
                error_info = ""
                if not ok:
                    if event.get("error_code"):
                        error_info = f" ({event['error_code']}"
                        if event.get("error_message"):
                            error_info += f": {event['error_message']}"
                        error_info += ")"
                    else:
                        error_info = " (error)"

                # One-line output summary
                output_summary = _summarize_output(output, truncated)

                lines.append(f"**Tool call:** `{tool}({args_json})` (caller={caller}, {duration} ms) {status}{error_info}")
                lines.append(f"  → {output_summary}")

                if full and output is not None:
                    output_json = json.dumps(output, indent=2, ensure_ascii=False) if not isinstance(output, str) else output
                    open_fence, close_fence = _safe_fence(output_json)
                    lines.append(open_fence + "json")
                    lines.append(output_json)
                    lines.append(close_fence)

                lines.append("")

            elif event_type == "citations_filtered":
                kept = event.get("kept", [])
                dropped = event.get("dropped", [])
                lines.append(f"**Citations filtered:**")
                lines.append(f"- Kept ({len(kept)}): {', '.join(kept) if kept else '(none)'}")
                lines.append(f"- Dropped ({len(dropped)}): {', '.join(dropped) if dropped else '(none)'}")
                lines.append("")

            elif event_type == "code_event":
                kind = event.get("kind", "?")
                outcome = event.get("outcome", "?")
                detail = event.get("detail")
                lines.append(f"**Code event:** {kind} → {outcome}")
                if detail:
                    detail_json = json.dumps(detail, ensure_ascii=False) if isinstance(detail, dict) else str(detail)
                    lines.append(f"- Detail: {detail_json}")
                lines.append("")

            elif event_type == "turn_finished":
                outcome = event.get("outcome", "unknown")
                reply = event.get("reply")
                citations = event.get("citations", [])
                steps_used = event.get("steps_used", 0)
                error = event.get("error")
                awaiting_kind = event.get("awaiting_kind")
                saved = event.get("saved")

                lines.append(f"**Turn finished:** {outcome}")
                lines.append(f"- Steps used: {steps_used}")
                if error:
                    error_str = f"{error.get('type', 'unknown')}: {error.get('message', 'unknown')}" if isinstance(error, dict) else str(error)
                    lines.append(f"- Error: {error_str}")
                if reply:
                    excerpt = reply[:200] if len(reply) > 200 else reply
                    lines.append(f"- Reply: \"{excerpt}\"")
                if citations:
                    lines.append(f"- Citations: {', '.join(citations)}")
                if awaiting_kind:
                    lines.append(f"- Awaiting: {awaiting_kind}")
                if saved is not None:
                    lines.append(f"- Saved: {saved}")
                lines.append("")

            elif event_type not in ("session_started",):
                # Unknown event type - render as raw JSON
                lines.append(f"**Unknown event type:** `{event_type}`")
                event_json = json.dumps(event, indent=2, ensure_ascii=False)
                open_fence, close_fence = _safe_fence(event_json)
                lines.append(open_fence + "json")
                lines.append(event_json)
                lines.append(close_fence)
                lines.append("")

    return "\n".join(lines)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate a readable Markdown report from an agent decision trace"
    )
    parser.add_argument(
        "session_id",
        help="Session ID (without .jsonl extension)"
    )
    parser.add_argument(
        "--traces-dir",
        type=Path,
        default=Path("data/local/traces"),
        help="Directory containing trace files (default: data/local/traces)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Output Markdown file path (default: <traces-dir>/<session_id>.md)"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include full context JSON and tool outputs"
    )

    args = parser.parse_args()

    # Build paths
    trace_path = args.traces_dir / f"{args.session_id}.jsonl"
    out_path = args.out or (args.traces_dir / f"{args.session_id}.md")

    # Load events
    try:
        events = load_events(trace_path)
    except FileNotFoundError:
        print(f"Error: Trace file not found: {trace_path}", file=sys.stderr)
        sys.exit(1)

    # Render report
    report = render_report(events, full=args.full)

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    print(str(out_path))
    sys.exit(0)


if __name__ == "__main__":
    main()
