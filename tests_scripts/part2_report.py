"""Compare the Part 2 compacted and full-context trajectory token usage."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def read_trajectory(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    trajectory = json.loads(path.read_text(encoding="utf-8"))
    actions = trajectory["responses"]
    compactions = trajectory["compactions"]
    if not actions:
        raise ValueError(f"{path} has no model responses to compare.")
    return actions, compactions


def token_values(responses: list[dict[str, Any]], field: str) -> list[int] | None:
    values = [(response.get("usage") or {}).get(field) for response in responses]
    if any(type(value) is not int for value in values):
        return None
    return values


def token_total(responses: list[dict[str, Any]], field: str) -> int | None:
    values = token_values(responses, field)
    return sum(values) if values is not None else None


def metrics(actions: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [event["compaction_response"] for event in events]
    action_inputs = token_values(actions, "prompt_tokens")
    models = sorted({action["model"] for action in actions if action.get("model")})
    mean_input = round(sum(action_inputs) / len(action_inputs)) if action_inputs else None
    return {
        "Model reported by provider": ", ".join(models) or None,
        "ReAct steps": len(actions),
        "Compaction requests": len(summaries),
        "ReAct input tokens": token_total(actions, "prompt_tokens"),
        "Mean input tokens per ReAct step": mean_input,
        "Peak ReAct input tokens": max(action_inputs) if action_inputs else None,
        "ReAct output tokens": token_total(actions, "completion_tokens"),
        "Compaction input tokens": token_total(summaries, "prompt_tokens"),
        "Compaction output tokens": token_total(summaries, "completion_tokens"),
        "Total tokens including compaction": token_total([*actions, *summaries], "total_tokens"),
    }


def display(value: str | int | None) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return value if value is not None else "Unavailable"


def compare(label: str, compacted: int | None, baseline: int | None) -> str:
    if compacted is None or baseline is None:
        return f"{label} could not be compared because at least one response omitted usage."
    difference = compacted - baseline
    if difference == 0:
        return f"{label} was the same in both runs ({compacted:,} tokens)."
    direction = "higher" if difference > 0 else "lower"
    return f"{label} was {abs(difference):,} tokens {direction} with compaction."


def build_report(compacted_path: Path, baseline_path: Path) -> str:
    if compacted_path.resolve() == baseline_path.resolve():
        raise ValueError("Choose separate trajectories for the compacted and full-context runs.")
    compacted_actions, events = read_trajectory(compacted_path)
    baseline_actions, baseline_events = read_trajectory(baseline_path)
    if baseline_events:
        raise ValueError(f"{baseline_path} contains compactions. Use the COMPACT_THRESHOLD=0 run.")

    compacted = metrics(compacted_actions, events)
    baseline = metrics(baseline_actions, baseline_events)
    lines = [
        "# Part 2 token usage",
        "",
        f"Measured from `{compacted_path.name}` and `{baseline_path.name}` using provider-reported usage.",
        "",
        "| Metric | Compacted | Full context |",
        "| --- | ---: | ---: |",
    ]
    lines.extend(
        f"| {label} | {display(value)} | {display(baseline[label])} |"
        for label, value in compacted.items()
    )
    lines.extend(["", "## Active context at compaction", ""])
    if events:
        lines.extend([
            "| After ReAct step | Estimated before | Estimated after | Reduction |",
            "| ---: | ---: | ---: | ---: |",
        ])
        for event in events:
            before = event["estimated_tokens_before"]
            after = event["estimated_tokens_after"]
            reduction = f"{(before - after) / before:.1%}" if before else "Unavailable"
            lines.append(f"| {event['step']} | {before:,} | {after:,} | {reduction} |")
    else:
        lines.append("The compacted run recorded no compaction events.")

    lines.extend([
        "",
        "## Observations",
        "",
        compare(
            "Mean ReAct input",
            compacted["Mean input tokens per ReAct step"],
            baseline["Mean input tokens per ReAct step"],
        ),
        compare(
            "Overall usage including summaries",
            compacted["Total tokens including compaction"],
            baseline["Total tokens including compaction"],
        ),
        "",
        "Summaries can reduce repeated input and discard details from older tool output. "
        "They also cost a separate model request. The total depends on the size of those "
        "requests and how many ReAct steps each stochastic run takes.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    instance = os.environ.get("INSTANCE", "django__django-15368")
    parser.add_argument("--compacted", type=Path, default=Path(f"artifacts/{instance}-trajectory.json"))
    parser.add_argument("--baseline", type=Path, default=Path(f"artifacts/{instance}-baseline-trajectory.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/token-usage-analysis.md"))
    args = parser.parse_args()
    try:
        report = build_report(args.compacted, args.baseline)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
