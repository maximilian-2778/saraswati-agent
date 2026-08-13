"""Merge sharded end-to-end Agent benchmark results without API calls."""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "benchmark-results"
SOURCES = [
    ("agent-chain-50.json", {1}),
    ("agent-chain-story-02.json", {2}),
    ("agent-chain-stories-03-05.json", {3, 4, 5}),
    ("agent-chain-stories-06-07.json", {6, 7}),
    ("agent-chain-stories-08-10.json", {8, 9, 10}),
]


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap_mean_ci(values: list[float], samples: int = 5000) -> list[float]:
    rng = random.Random(20260813)
    means = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples)]
    means.sort()
    return [means[int(samples * 0.025)], means[int(samples * 0.975)]]


def main() -> None:
    rows: list[dict[str, Any]] = []
    for filename, stories in SOURCES:
        payload = json.loads((RESULTS / filename).read_text(encoding="utf-8"))
        rows.extend(row for row in payload["turns"] if int(row["story"]) in stories)

    unique: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        key = (int(row["story"]), int(row["turn"]))
        if key in unique:
            raise RuntimeError(f"Duplicate turn: {key}")
        unique[key] = row
    rows = [unique[key] for key in sorted(unique)]

    planned = {(story, turn) for story in range(1, 11) for turn in range(1, 6)}
    completed = set(unique)
    missing = sorted(planned - completed)
    # The first missing turn is evidenced by the retained DB/trace and stack trace;
    # the following turn was not attempted after the story-level crash.
    failed_turns = [{
        "story": 5,
        "turn": 4,
        "error": "ValueError: 场景路径不能为空",
        "stage": "apply_narrative_delta",
        "cost_included": False,
    }]
    skipped_turns = [{"story": 5, "turn": 5, "reason": "previous turn crashed"}]

    latencies = [float(row["end_to_end_latency_ms"]) for row in rows]
    input_tokens = [int(row["input_tokens"]) for row in rows]
    output_tokens = [int(row["output_tokens"]) for row in rows]
    costs = [float(row["standard_price_cost_rmb"]) for row in rows]
    api_calls = [int(row["api_calls"]) for row in rows]

    by_turn: list[dict[str, Any]] = []
    for turn in range(1, 6):
        group = [row for row in rows if int(row["turn"]) == turn]
        by_turn.append({
            "turn_position": turn,
            "observations": len(group),
            "mean_latency_ms": statistics.fmean(
                float(row["end_to_end_latency_ms"]) for row in group
            ),
            "mean_input_tokens": statistics.fmean(int(row["input_tokens"]) for row in group),
            "mean_output_tokens": statistics.fmean(int(row["output_tokens"]) for row in group),
            "mean_api_calls": statistics.fmean(int(row["api_calls"]) for row in group),
        })

    summary = {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "qwen3.7-plus",
            "planned_stories": 10,
            "planned_turns": 50,
            "max_output_tokens": 512,
            "max_agent_steps": 2,
            "pricing": "standard list-price equivalent; free quota and discounts not subtracted",
        },
        "summary": {
            "successful_turns": len(rows),
            "failed_turns": len(failed_turns),
            "skipped_turns": len(skipped_turns),
            "success_rate_of_attempted": len(rows) / (len(rows) + len(failed_turns)),
            "completion_rate_of_planned": len(rows) / 50,
            "total_api_calls_completed_turns": sum(api_calls),
            "mean_api_calls_per_completed_turn": statistics.fmean(api_calls),
            "api_call_distribution": dict(sorted(Counter(api_calls).items())),
            "total_input_tokens_completed_turns": sum(input_tokens),
            "total_output_tokens_completed_turns": sum(output_tokens),
            "total_tokens_completed_turns": sum(input_tokens) + sum(output_tokens),
            "mean_input_tokens_per_completed_turn": statistics.fmean(input_tokens),
            "mean_input_tokens_bootstrap_95_ci": bootstrap_mean_ci(input_tokens),
            "mean_output_tokens_per_completed_turn": statistics.fmean(output_tokens),
            "mean_standard_price_cost_rmb_per_completed_turn": statistics.fmean(costs),
            "total_standard_price_cost_rmb_completed_turns": sum(costs),
            "mean_end_to_end_latency_ms": statistics.fmean(latencies),
            "mean_end_to_end_latency_bootstrap_95_ci": bootstrap_mean_ci(latencies),
            "p50_end_to_end_latency_ms": percentile(latencies, 0.50),
            "p95_end_to_end_latency_ms": percentile(latencies, 0.95),
            "min_end_to_end_latency_ms": min(latencies),
            "max_end_to_end_latency_ms": max(latencies),
        },
        "by_turn_position": by_turn,
        "failed_turns": failed_turns,
        "skipped_turns": skipped_turns,
        "missing_turns": [{"story": s, "turn": t} for s, t in missing],
        "turns": rows,
    }
    (RESULTS / "agent-chain-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
