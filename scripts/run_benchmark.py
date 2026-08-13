"""Run the reproducible Saraswati synthetic narrative benchmark.

The runner uses the project's real MemoryService and NarrativeDeltaService.
It never writes API credentials to the result directory.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import random
import statistics
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.database import Base, Database  # noqa: E402
from backend.models import ChatRecord, MemoryRecord  # noqa: E402
from backend.providers.openai_compatible import OpenAICompatibleClient  # noqa: E402
from backend.schemas import MemoryKind  # noqa: E402
from backend.services.memory import MemoryService  # noqa: E402
from backend.services.narrative_delta import NarrativeDeltaService  # noqa: E402
from backend.utils import json_dumps  # noqa: E402


INPUT_PRICE_RMB_PER_MILLION = 2.0
OUTPUT_PRICE_RMB_PER_MILLION = 8.0
PRICE_SOURCE = "https://help.aliyun.com/zh/model-studio/model-pricing"


class MeteredClient(OpenAICompatibleClient):
    """Record provider usage for normal and structured calls without changing production code."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[dict[str, Any]] = []

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        data = await super()._post_json(path, payload)
        elapsed = (perf_counter() - started) * 1000
        usage = self._parse_usage(data.get("usage"))
        self.calls.append({
            "path": path,
            "duration_ms": round(elapsed, 2),
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
            "cached_tokens": usage.cached_tokens if usage else 0,
        })
        return data

    def take_calls(self) -> list[dict[str, Any]]:
        calls, self.calls = self.calls, []
        return calls


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=ROOT / "evals" / "benchmark" / "cases.json")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark-results")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--retrieval-only", action="store_true")
    return parser.parse_args()


def load_settings(output: Path) -> Settings:
    settings = Settings.from_env()
    if settings.provider_mode == "unconfigured":
        raise RuntimeError("No configured model in data/settings.json or environment")
    return replace(
        settings,
        max_output_tokens=512,
        database_url=f"sqlite:///{(output / 'benchmark.db').as_posix()}",
        settings_file=None,
        langgraph_checkpoint_path=None,
        input_price_per_million=INPUT_PRICE_RMB_PER_MILLION,
        output_price_per_million=OUTPUT_PRICE_RMB_PER_MILLION,
    )


def make_database(settings: Settings, db_path: Path) -> Database:
    if db_path.exists():
        db_path.unlink()
    database = Database(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(bind=database.engine)
    return database


def seed_retrieval(database: Database, payload: dict[str, Any]) -> dict[str, str]:
    now = datetime.now(UTC)
    story_documents: dict[str, dict[str, dict[str, Any]]] = {}
    for case in payload["retrieval_cases"]:
        story_documents.setdefault(case["story_id"], {})
        for document in case["documents"]:
            story_documents[case["story_id"]][document["id"]] = document

    story_chat_ids: dict[str, str] = {}
    with database.session_factory() as db:
        for story_id, documents in story_documents.items():
            chat_id = f"benchmark-{story_id}"
            story_chat_ids[story_id] = chat_id
            db.add(ChatRecord(
                id=chat_id,
                title=f"Benchmark {story_id}",
                system_prompt="",
                created_at=now,
                updated_at=now,
            ))
            for document in documents.values():
                from backend.llm import local_embedding
                db.add(MemoryRecord(
                    id=document["id"],
                    chat_id=chat_id,
                    kind=MemoryKind.EPISODIC.value,
                    content=document["text"],
                    importance=0.75 if "-f" in document["id"] else 0.45,
                    embedding_json=json_dumps(local_embedding(document["text"])),
                    source_message_id=None,
                    variant_id=None,
                    variant_ids_json="[]",
                    access_count=0,
                    last_accessed_at=None,
                    created_at=now - timedelta(days=int(document.get("age_days", 0))),
                ))
        db.commit()
    return story_chat_ids


async def run_retrieval(
    database: Database,
    model: MeteredClient,
    settings: Settings,
    cases: list[dict[str, Any]],
    story_chat_ids: dict[str, str],
) -> list[dict[str, Any]]:
    service = MemoryService(settings)
    rows: list[dict[str, Any]] = []
    with database.session_factory() as db:
        for case in cases:
            started = perf_counter()
            results = await service.search(
                db, model, story_chat_ids[case["story_id"]], case["query"], limit=5
            )
            ranked = [item.record.id for item in results]
            relevant = set(case["relevant_ids"])
            rank = next((i for i, item_id in enumerate(ranked, 1) if item_id in relevant), None)
            rows.append({
                "case_id": case["case_id"],
                "category": case["category"],
                "query": case["query"],
                "relevant_ids": sorted(relevant),
                "ranked_ids": ranked,
                "rank": rank,
                "recall_at_1": int(bool(relevant & set(ranked[:1]))),
                "recall_at_3": int(bool(relevant & set(ranked[:3]))),
                "recall_at_5": int(bool(relevant & set(ranked[:5]))),
                "reciprocal_rank": 1 / rank if rank else 0.0,
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            })
    return rows


async def run_consistency(
    database: Database,
    model: MeteredClient,
    settings: Settings,
    cases: list[dict[str, Any]],
    story_chat_ids: dict[str, str],
    run_id: int,
    progress_path: Path | None = None,
) -> list[dict[str, Any]]:
    service = MemoryService(settings)
    rows: list[dict[str, Any]] = []
    with database.session_factory() as db:
        for case in cases:
            retrieved = await service.search(
                db, model, story_chat_ids[case["story_id"]], case["query"], limit=5
            )
            evidence = "\n".join(f"- {item.record.content}" for item in retrieved)
            model.take_calls()
            started = perf_counter()
            reply = await model.complete([
                {
                    "role": "system",
                    "content": (
                        "你是剧情事实核对器。只能依据给出的记忆回答当前事实。"
                        "旧记录若被包含‘当前、最终、已经、作废、取消’的更新覆盖，应采用更新后的事实。"
                        "只输出一句简短答案，不解释推理过程。"
                    ),
                },
                {"role": "user", "content": f"【记忆】\n{evidence}\n\n【问题】\n{case['query']}"},
            ])
            calls = model.take_calls()
            answer = reply.content or ""
            expected_ok = all(item in answer for item in case["expected_phrases"])
            forbidden_ok = all(item not in answer for item in case["forbidden_phrases"])
            row = {
                "run": run_id,
                "case_id": case["case_id"],
                "category": case["category"],
                "answer": answer,
                "expected_phrases": case["expected_phrases"],
                "forbidden_phrases": case["forbidden_phrases"],
                "consistent": int(expected_ok and forbidden_ok),
                "retrieved_ids": [item.record.id for item in retrieved],
                **aggregate_calls(calls, (perf_counter() - started) * 1000),
            }
            rows.append(row)
            if progress_path:
                append_jsonl(progress_path, {"type": "consistency", **row})
    return rows


def canonical_change(item: dict[str, Any]) -> tuple[str, str, str]:
    value = item.get("new_value")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            number = float(stripped)
            value = int(number) if number.is_integer() else number
        except ValueError:
            value = stripped
    return (
        str(item.get("entity", "")).strip().casefold(),
        str(item.get("key", "")).strip().casefold(),
        json.dumps(value, ensure_ascii=False, sort_keys=True),
    )


def value_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            number = float(stripped)
            value = int(number) if number.is_integer() else number
        except ValueError:
            value = stripped
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def entity_subject(entity: str) -> str:
    value = entity.strip().casefold()
    if ":" in value:
        value = value.split(":", 1)[1]
    for suffix in ("小队", "队伍", "角色", "任务"):
        value = value.removesuffix(suffix)
    return value.strip()


def fact_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Match a state fact while allowing harmless entity/key layout differences."""
    if value_key(expected.get("new_value")) != value_key(actual.get("new_value")):
        return False
    expected_entity = entity_subject(str(expected.get("entity", "")))
    actual_identity = f"{actual.get('entity', '')} {actual.get('key', '')}".casefold()
    if expected_entity and expected_entity not in actual_identity:
        return False
    expected_key = str(expected.get("key", "")).strip().casefold()
    if expected_key == "状态" and "任务" in str(expected.get("entity", "")):
        return True
    return not expected_key or expected_key in actual_identity


def fact_counts(
    expected_items: list[dict[str, Any]], actual_items: list[dict[str, Any]]
) -> tuple[int, int, int]:
    unmatched = set(range(len(actual_items)))
    tp = 0
    for expected in expected_items:
        match = next(
            (index for index in unmatched if fact_match(expected, actual_items[index])),
            None,
        )
        if match is not None:
            unmatched.remove(match)
            tp += 1
    return tp, len(unmatched), len(expected_items) - tp


def extracted_changes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = list(payload.get("state_changes") or [])
    for number in payload.get("numbers") or []:
        if str(number.get("key", "")).strip():
            value: Any = number.get("value")
            if number.get("unit"):
                value = {"value": value, "unit": number["unit"]}
            result.append({
                "entity": number.get("entity") or "剧情数值",
                "key": number.get("key"),
                "new_value": value,
            })
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in result:
        unique[canonical_change(item)] = item
    return list(unique.values())


async def run_state(
    model: MeteredClient,
    cases: list[dict[str, Any]],
    run_id: int,
    progress_path: Path | None = None,
) -> list[dict[str, Any]]:
    service = NarrativeDeltaService()
    rows: list[dict[str, Any]] = []
    for case in cases:
        model.take_calls()
        started = perf_counter()
        payload = await service._extract(model, case["user_text"], case["assistant_text"])
        calls = model.take_calls()
        actual_items = extracted_changes(payload)
        expected = {canonical_change(item) for item in case["expected_state_changes"]}
        actual = {canonical_change(item) for item in actual_items}
        strict_tp = len(expected & actual)
        fact_tp, fact_fp, fact_fn = fact_counts(case["expected_state_changes"], actual_items)
        row = {
            "run": run_id,
            "case_id": case["case_id"],
            "expected": case["expected_state_changes"],
            "actual": actual_items,
            "raw_delta_payload": payload,
            "tp": fact_tp,
            "fp": fact_fp,
            "fn": fact_fn,
            "strict_tp": strict_tp,
            "strict_fp": len(actual - expected),
            "strict_fn": len(expected - actual),
            **aggregate_calls(calls, (perf_counter() - started) * 1000),
        }
        rows.append(row)
        if progress_path:
            append_jsonl(progress_path, {"type": "state", **row})
    return rows


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()


def aggregate_calls(calls: list[dict[str, Any]], fallback_duration_ms: float) -> dict[str, Any]:
    input_tokens = sum(int(item.get("input_tokens") or 0) for item in calls)
    output_tokens = sum(int(item.get("output_tokens") or 0) for item in calls)
    total_tokens = sum(int(item.get("total_tokens") or 0) for item in calls)
    cached_tokens = sum(int(item.get("cached_tokens") or 0) for item in calls)
    duration_ms = sum(float(item.get("duration_ms") or 0) for item in calls)
    if not duration_ms:
        duration_ms = fallback_duration_ms
    cost = (
        input_tokens * INPUT_PRICE_RMB_PER_MILLION
        + output_tokens * OUTPUT_PRICE_RMB_PER_MILLION
    ) / 1_000_000
    return {
        "api_calls": len(calls),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "duration_ms": round(duration_ms, 2),
        "standard_price_cost_rmb": round(cost, 8),
    }


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def wilson(successes: int, total: int, z: float = 1.96) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def bootstrap_mean_ci(values: list[float], seed: int = 20260813, samples: int = 3000) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples)]
    means.sort()
    return [means[int(samples * 0.025)], means[int(samples * 0.975)]]


def metric_summary(
    retrieval: list[dict[str, Any]],
    consistency: list[dict[str, Any]],
    state: list[dict[str, Any]],
) -> dict[str, Any]:
    run_ids = sorted({int(row["run"]) for row in retrieval + consistency + state})
    per_run: list[dict[str, Any]] = []
    for run_id in run_ids:
        retrieval_run = [row for row in retrieval if int(row["run"]) == run_id]
        consistency_run = [row for row in consistency if int(row["run"]) == run_id]
        state_run = [row for row in state if int(row["run"]) == run_id]
        run_tp = sum(row["tp"] for row in state_run)
        run_fp = sum(row["fp"] for row in state_run)
        run_fn = sum(row["fn"] for row in state_run)
        run_precision = run_tp / (run_tp + run_fp) if run_tp + run_fp else 1.0
        run_recall = run_tp / (run_tp + run_fn) if run_tp + run_fn else 1.0
        run_f1 = (
            2 * run_precision * run_recall / (run_precision + run_recall)
            if run_precision + run_recall else 0.0
        )
        model_run = consistency_run + state_run
        per_run.append({
            "run": run_id,
            "retrieval_recall_at_1": (
                statistics.fmean(row["recall_at_1"] for row in retrieval_run)
                if retrieval_run else 0.0
            ),
            "retrieval_recall_at_3": (
                statistics.fmean(row["recall_at_3"] for row in retrieval_run)
                if retrieval_run else 0.0
            ),
            "retrieval_recall_at_5": (
                statistics.fmean(row["recall_at_5"] for row in retrieval_run)
                if retrieval_run else 0.0
            ),
            "setting_consistency": (
                sum(row["consistent"] for row in consistency_run) / len(consistency_run)
                if consistency_run else 0.0
            ),
            "state_precision": run_precision,
            "state_recall": run_recall,
            "state_f1": run_f1,
            "mean_input_tokens": (
                statistics.fmean(row["input_tokens"] for row in model_run)
                if model_run else 0.0
            ),
            "mean_latency_ms": (
                statistics.fmean(row["duration_ms"] for row in model_run)
                if model_run else 0.0
            ),
            "standard_price_cost_rmb": sum(
                row["standard_price_cost_rmb"] for row in model_run
            ),
        })
    count = len(retrieval)
    retrieval_metrics = {
        "cases": count,
        "recall_at_1": statistics.fmean(row["recall_at_1"] for row in retrieval),
        "recall_at_3": statistics.fmean(row["recall_at_3"] for row in retrieval),
        "recall_at_5": statistics.fmean(row["recall_at_5"] for row in retrieval),
        "mrr": statistics.fmean(row["reciprocal_rank"] for row in retrieval),
        "mean_local_latency_ms": statistics.fmean(row["duration_ms"] for row in retrieval),
        "p95_local_latency_ms": percentile([row["duration_ms"] for row in retrieval], 0.95),
    }
    consistent = sum(row["consistent"] for row in consistency)
    tp = sum(row["tp"] for row in state)
    fp = sum(row["fp"] for row in state)
    fn = sum(row["fn"] for row in state)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    strict_tp = sum(row["strict_tp"] for row in state)
    strict_fp = sum(row["strict_fp"] for row in state)
    strict_fn = sum(row["strict_fn"] for row in state)
    strict_precision = strict_tp / (strict_tp + strict_fp) if strict_tp + strict_fp else 1.0
    strict_recall = strict_tp / (strict_tp + strict_fn) if strict_tp + strict_fn else 1.0
    strict_f1 = (
        2 * strict_precision * strict_recall / (strict_precision + strict_recall)
        if strict_precision + strict_recall else 0.0
    )
    model_rows = consistency + state
    input_values = [float(row["input_tokens"]) for row in model_rows]
    latency_values = [float(row["duration_ms"]) for row in model_rows]
    cost_values = [float(row["standard_price_cost_rmb"]) for row in model_rows]
    return {
        "per_run": per_run,
        "retrieval": retrieval_metrics,
        "consistency": {
            "observations": len(consistency),
            "passed": consistent,
            "rate": consistent / len(consistency) if consistency else 0.0,
            "wilson_95_ci": wilson(consistent, len(consistency)),
        },
        "state_updates_micro": {
            "observations": len(state),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "precision_wilson_95_ci": wilson(tp, tp + fp),
            "recall_wilson_95_ci": wilson(tp, tp + fn),
        },
        "state_updates_strict_schema": {
            "tp": strict_tp,
            "fp": strict_fp,
            "fn": strict_fn,
            "precision": strict_precision,
            "recall": strict_recall,
            "f1": strict_f1,
        },
        "model_efficiency": {
            "observations": len(model_rows),
            "api_calls": sum(row["api_calls"] for row in model_rows),
            "mean_input_tokens": statistics.fmean(input_values) if input_values else 0.0,
            "mean_input_tokens_bootstrap_95_ci": bootstrap_mean_ci(input_values),
            "mean_output_tokens": statistics.fmean(row["output_tokens"] for row in model_rows) if model_rows else 0.0,
            "mean_standard_price_cost_rmb": statistics.fmean(cost_values) if cost_values else 0.0,
            "total_standard_price_cost_rmb": sum(cost_values),
            "mean_latency_ms": statistics.fmean(latency_values) if latency_values else 0.0,
            "p50_latency_ms": percentile(latency_values, 0.50),
            "p95_latency_ms": percentile(latency_values, 0.95),
            "mean_latency_bootstrap_95_ci": bootstrap_mean_ci(latency_values),
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                for key, value in row.items()
            })


def write_report(path: Path, metadata: dict[str, Any], metrics: dict[str, Any]) -> None:
    r = metrics["retrieval"]
    c = metrics["consistency"]
    s = metrics["state_updates_micro"]
    ss = metrics["state_updates_strict_schema"]
    e = metrics["model_efficiency"]
    path.write_text(
        "\n".join([
            "# Saraswati Synthetic Narrative Benchmark Report",
            "",
            "> This is a deterministic synthetic benchmark, not real-user evidence.",
            "",
            "## Configuration",
            "",
            f"- Model: `{metadata['model']}`",
            f"- Runs: {metadata['runs']}",
            f"- Embedding: {metadata['embedding_mode']}",
            f"- Reranker: {metadata['reranker_mode']}",
            f"- Dataset SHA-256: `{metadata['dataset_sha256']}`",
            f"- Pricing: standard list-price equivalent, {INPUT_PRICE_RMB_PER_MILLION} RMB/M input and {OUTPUT_PRICE_RMB_PER_MILLION} RMB/M output tokens.",
            f"- Pricing source: {PRICE_SOURCE}",
            "",
            "## Results",
            "",
            "| Metric | Result |",
            "| --- | ---: |",
            f"| Retrieval Recall@1 | {r['recall_at_1']:.3f} |",
            f"| Retrieval Recall@3 | {r['recall_at_3']:.3f} |",
            f"| Retrieval Recall@5 | {r['recall_at_5']:.3f} |",
            f"| Retrieval MRR | {r['mrr']:.3f} |",
            f"| Setting consistency | {c['rate']:.3f} ({c['wilson_95_ci'][0]:.3f}-{c['wilson_95_ci'][1]:.3f}) |",
            f"| State update precision | {s['precision']:.3f} ({s['precision_wilson_95_ci'][0]:.3f}-{s['precision_wilson_95_ci'][1]:.3f}) |",
            f"| State update recall | {s['recall']:.3f} ({s['recall_wilson_95_ci'][0]:.3f}-{s['recall_wilson_95_ci'][1]:.3f}) |",
            f"| State update F1 | {s['f1']:.3f} |",
            f"| State strict-schema F1 | {ss['f1']:.3f} |",
            f"| Mean input tokens / model observation | {e['mean_input_tokens']:.1f} |",
            f"| Mean output tokens / model observation | {e['mean_output_tokens']:.1f} |",
            f"| Mean standard-price cost / model observation | ¥{e['mean_standard_price_cost_rmb']:.5f} |",
            f"| Total standard-price equivalent | ¥{e['total_standard_price_cost_rmb']:.3f} |",
            f"| Mean provider latency | {e['mean_latency_ms'] / 1000:.2f}s |",
            f"| P95 provider latency | {e['p95_latency_ms'] / 1000:.2f}s |",
            "",
            "## Limitations",
            "",
            "- The cases are synthetic and template-generated; the results do not establish real-user satisfaction or market impact.",
            "- Retrieval uses the project's 96-dimensional local hash embedding fallback when no external embedding model is configured.",
            "- No independent reranker is enabled in this configuration.",
            "- Cost is computed from the public standard list price; free quota, temporary discounts, and cached-input discounts are not subtracted.",
            "- Provider latency includes network and model processing and is specific to the test time and endpoint.",
            "- Fact-level state matching allows harmless entity/key layout differences; strict-schema F1 separately measures exact canonical field agreement.",
        ]) + "\n",
        encoding="utf-8",
    )


async def async_main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    settings = load_settings(args.output)
    database = make_database(
        settings,
        args.output / ("benchmark-smoke.db" if args.smoke else "benchmark-full.db"),
    )
    story_chat_ids = seed_retrieval(database, payload)
    model = MeteredClient(settings)
    try:
        await model.check_connection()
        retrieval_cases = payload["retrieval_cases"][:12] if args.smoke else payload["retrieval_cases"]
        consistency_cases = payload["consistency_cases"][:3] if args.smoke else payload["consistency_cases"]
        state_cases = payload["state_cases"][:3] if args.smoke else payload["state_cases"]
        runs = 1 if args.smoke else args.runs

        retrieval_runs = []
        for run_id in range(1, runs + 1):
            rows = await run_retrieval(database, model, settings, retrieval_cases, story_chat_ids)
            retrieval_runs.extend({"run": run_id, **row} for row in rows)

        consistency_rows: list[dict[str, Any]] = []
        state_rows: list[dict[str, Any]] = []
        progress_path = args.output / ("progress-smoke.jsonl" if args.smoke else "progress-full.jsonl")
        if progress_path.exists():
            progress_path.unlink()
        if not args.retrieval_only:
            for run_id in range(1, runs + 1):
                consistency_rows.extend(await run_consistency(
                    database, model, settings, consistency_cases, story_chat_ids, run_id,
                    progress_path,
                ))
                state_rows.extend(await run_state(model, state_cases, run_id, progress_path))

        metrics = metric_summary(retrieval_runs, consistency_rows, state_rows)
        metadata = {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": settings.llm_model,
            "runs": runs,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "max_output_tokens": settings.max_output_tokens,
            "embedding_mode": settings.embedding_model or "local_hash_96",
            "reranker_mode": settings.rerank_model or "disabled",
            "dataset_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
            "dataset_metadata": payload["metadata"],
            "pricing_source": PRICE_SOURCE,
            "input_price_rmb_per_million": INPUT_PRICE_RMB_PER_MILLION,
            "output_price_rmb_per_million": OUTPUT_PRICE_RMB_PER_MILLION,
            "smoke": args.smoke,
        }
        result = {"metadata": metadata, "metrics": metrics}
        suffix = "smoke" if args.smoke else "full"
        (args.output / f"metrics-{suffix}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_csv(args.output / f"retrieval-{suffix}.csv", retrieval_runs)
        write_csv(args.output / f"consistency-{suffix}.csv", consistency_rows)
        write_csv(args.output / f"state-{suffix}.csv", state_rows)
        write_report(args.output / f"BENCHMARK_REPORT-{suffix}.md", metadata, metrics)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        await model.close()
        database.engine.dispose()


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
