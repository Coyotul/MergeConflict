#!/usr/bin/env python3
"""Readable trace report generator for agent decision traces.

Reads a session's trace JSONL file and renders it as a Markdown timeline
showing every model call, tool invocation, field update, and decision.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_events(path: Path) -> list[dict]:
    """Load events from a JSONL trace file.

    Skips blank lines and lines that fail to parse as JSON.

    Args:
        path: Path to the JSONL trace file

    Returns:
        List of event dictionaries

    Raises:
        FileNotFoundError: If the trace file doesn't exist
    """
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
                events.append(event)
            except json.JSONDecodeError:
                # Skip corrupt lines silently
                continue

    return events


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

    # Find session_started event for header info
    session_started = next((e for e in events if e["type"] == "session_started"), None)
    if session_started:
        lines.append(f"**Session:** `{session_started['session_id']}`  ")
        lines.append(f"**Customer:** `{session_started['customer_id']}`  ")
        lines.append(f"**Model:** {session_started.get('model', 'unknown')}  ")
        lines.append(f"**Prompt version:** {session_started.get('prompt_version', 'unknown')}  ")
        lines.append(f"**Started:** {session_started.get('ts', 'unknown')}  ")
        lines.append("")

        # System prompt in collapsed details
        if "system_prompt" in session_started:
            lines.append("<details>")
            lines.append("<summary>System Prompt</summary>")
            lines.append("")
            lines.append("```")
            lines.append(session_started["system_prompt"])
            lines.append("```")
            lines.append("</details>")
            lines.append("")

    # Group events by turn
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
        turn_start = next((e for e in turn_events if e["type"] == "turn_started"), None)
        turn_finish = next((e for e in turn_events if e["type"] == "turn_finished"), None)

        if turn_start:
            event_kind = turn_start.get("event", {}).get("kind", "unknown")
            stage_before = turn_start.get("stage", "?")
            stage_after = turn_finish.get("stage_after", "?") if turn_finish else "?"
            duration_ms = turn_finish.get("duration_ms", "?") if turn_finish else "?"

            lines.append(f"## Turn {turn_number} — {event_kind} ({stage_before} → {stage_after}, {duration_ms} ms)")
            lines.append("")

        # Render events in order
        for event in turn_events:
            event_type = event["type"]

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

                if full and "context" in event:
                    lines.append("")
                    lines.append("**Context:**")
                    lines.append("```json")
                    lines.append(json.dumps(event["context"], indent=2, ensure_ascii=False))
                    lines.append("```")

                lines.append("")

            elif event_type == "action_parsed":
                intent = event.get("intent", "unknown")
                action = event.get("action", {})
                action_type = action.get("type", "unknown")

                lines.append(f"**Action parsed:** Intent={intent}, Type={action_type}")

                if action_type == "call_tool":
                    lines.append(f"- Tool: `{action.get('tool')}`")
                elif action_type == "respond":
                    message = action.get("message", "")
                    excerpt = message[:200] if len(message) > 200 else message
                    lines.append(f"- Reply: \"{excerpt}\"")

                lines.append("")

            elif event_type == "action_invalid":
                will_retry = event.get("will_retry", False)
                lines.append(f"**Invalid action** (will retry: {will_retry})")
                lines.append(f"- Error: {event.get('error', 'unknown')}")
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

                status = "✓" if ok else "✗"
                error_info = ""
                if not ok and event.get("error_code"):
                    error_info = f" ({event['error_code']}: {event.get('error_message', '')})"

                lines.append(f"**Tool call:** `{tool}` (caller={caller}, {duration} ms) {status}{error_info}")

                if full and "output" in event:
                    lines.append("```json")
                    output = event["output"]
                    if isinstance(output, str):
                        lines.append(output)
                    else:
                        lines.append(json.dumps(output, indent=2, ensure_ascii=False))
                    lines.append("```")

                lines.append("")

            elif event_type == "citations_filtered":
                kept = event.get("kept", [])
                dropped = event.get("dropped", [])
                lines.append(f"**Citations filtered:** kept={len(kept)}, dropped={len(dropped)}")
                lines.append("")

            elif event_type == "code_event":
                kind = event.get("kind", "?")
                outcome = event.get("outcome", "?")
                lines.append(f"**Code event:** {kind} → {outcome}")
                lines.append("")

            elif event_type == "turn_finished":
                outcome = event.get("outcome", "unknown")
                reply = event.get("reply")
                citations = event.get("citations", [])
                steps_used = event.get("steps_used", 0)

                lines.append(f"**Turn finished:** {outcome}")
                lines.append(f"- Steps used: {steps_used}")
                if reply:
                    excerpt = reply[:200] if len(reply) > 200 else reply
                    lines.append(f"- Reply: \"{excerpt}\"")
                if citations:
                    lines.append(f"- Citations: {', '.join(citations)}")
                lines.append("")

            elif event_type not in ("session_started",):
                # Unknown event type - render as raw JSON
                lines.append(f"**Unknown event type:** `{event_type}`")
                lines.append("```json")
                lines.append(json.dumps(event, indent=2, ensure_ascii=False))
                lines.append("```")
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
