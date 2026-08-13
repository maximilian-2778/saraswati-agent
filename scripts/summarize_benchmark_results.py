"""Rebuild aggregate and per-run metrics from existing benchmark CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.run_benchmark import metric_summary  # noqa: E402


INTEGER_FIELDS = {
    "api_calls", "cached_tokens", "consistent", "fn", "fp", "input_tokens",
    "output_tokens", "rank", "recall_at_1", "recall_at_3", "recall_at_5",
    "run", "strict_fn", "strict_fp", "strict_tp", "total_tokens", "tp",
}
FLOAT_FIELDS = {"duration_ms", "reciprocal_rank", "standard_price_cost_rmb"}
JSON_FIELDS = {
    "actual", "expected", "expected_phrases", "forbidden_phrases",
    "ranked_ids", "raw_delta_payload", "relevant_ids", "retrieved_ids",
}


def read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in INTEGER_FIELDS:
            if row.get(key) not in (None, ""):
                row[key] = int(row[key])
        for key in FLOAT_FIELDS:
            if row.get(key) not in (None, ""):
                row[key] = float(row[key])
        for key in JSON_FIELDS:
            if row.get(key) not in (None, ""):
                row[key] = json.loads(row[key])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark-results")
    args = parser.parse_args()
    root = args.output.resolve()
    metrics_path = root / "metrics-full.json"
    existing = json.loads(metrics_path.read_text(encoding="utf-8"))
    existing["metrics"] = metric_summary(
        read_rows(root / "retrieval-full.csv"),
        read_rows(root / "consistency-full.csv"),
        read_rows(root / "state-full.csv"),
    )
    metrics_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(existing["metrics"]["per_run"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
