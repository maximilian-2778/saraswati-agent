"""Run a small end-to-end AgentRuntime smoke benchmark.

This complements the fixed synthetic benchmark. It exercises the compiled
LangGraph workflow, persistence, narrative memory and delta post-processing
against an isolated SQLite database. API credentials are loaded through the
normal project settings path and are never written to the result file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.database import Base, Database  # noqa: E402
from backend.extensions import ExtensionRuntime  # noqa: E402
from backend.models import ChatRecord, MessageRecord  # noqa: E402
from backend.services.agent import AgentRuntime  # noqa: E402
from scripts.run_benchmark import (  # noqa: E402
    INPUT_PRICE_RMB_PER_MILLION,
    OUTPUT_PRICE_RMB_PER_MILLION,
    MeteredClient,
)


SCENARIOS = [
    ("白石镇", "旅店老板", "失踪的信使", "北门", "地图", 3, 27, "天亮前", "银羽纹章铜扣"),
    ("雾港", "灯塔守卫", "失联的巡逻员", "旧码头", "潮汐图", 4, 36, "午夜前", "蓝蜡封信"),
    ("赤岩村", "药铺掌柜", "采药学徒", "鹰嘴崖", "止血药", 5, 45, "日落前", "断裂的药锄"),
    ("月溪城", "档案管理员", "被盗的卷宗", "钟楼", "城防图", 6, 54, "钟响前", "黑曜石印章"),
    ("松风驿", "驿站长", "迟到的商队", "西桥", "干粮包", 2, 18, "黄昏前", "染血的车辙布"),
    ("霜河堡", "军需官", "失踪的斥候", "冰湖", "御寒斗篷", 7, 63, "暴雪前", "刻有狼首的箭头"),
    ("青禾镇", "磨坊主", "被偷的账本", "河湾仓库", "渡河绳", 3, 33, "涨潮前", "沾满面粉的钥匙"),
    ("星落谷", "观星师", "坠落的陨石", "南坡", "星象盘", 8, 72, "月升前", "发光的石屑"),
    ("铁杉营地", "猎人队长", "受伤的猎犬", "黑林", "兽夹", 4, 26, "入夜前", "灰熊毛束"),
    ("金砂城", "商会书记", "失窃的货箱", "东市", "货运凭证", 9, 81, "闭市前", "刻号铜牌"),
]


def scenario_prompts(values: tuple[object, ...]) -> list[str]:
    place, npc, target, destination, item, spent, remaining, deadline, clue = values
    return [
        f"我在雨夜抵达{place}，请用两三句话描写我找到落脚处的情景。",
        f"{npc}告诉我，{target}最后去了{destination}。请继续这一幕。",
        f"我花了{spent}枚金币买下{item}，现在还剩{remaining}枚金币。请写出交易结果。",
        f"我答应{npc}{deadline}处理这件事，然后立即前往{destination}。",
        f"我在{destination}发现{clue}，把它收进行囊。",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmark-results" / "agent-chain-smoke.json",
    )
    parser.add_argument("--story-count", type=int, default=1, choices=range(1, 11))
    parser.add_argument("--story-start", type=int, default=1, choices=range(1, 11))
    return parser.parse_args()


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


async def main() -> None:
    args = parse_args()
    if args.story_start + args.story_count - 1 > len(SCENARIOS):
        raise ValueError("story-start + story-count exceeds available scenarios")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    db_path = output.with_suffix(".db")
    if db_path.exists():
        db_path.unlink()

    base = Settings.from_env()
    if base.provider_mode == "unconfigured":
        raise RuntimeError("No configured model in data/settings.json or environment")
    settings = replace(
        base,
        database_url=f"sqlite:///{db_path.as_posix()}",
        settings_file=None,
        langgraph_checkpoint_path=None,
        max_output_tokens=512,
        max_agent_steps=2,
        input_price_per_million=INPUT_PRICE_RMB_PER_MILLION,
        output_price_per_million=OUTPUT_PRICE_RMB_PER_MILLION,
    )

    database = Database(settings.database_url)
    Base.metadata.create_all(bind=database.engine)
    model = MeteredClient(settings)
    runtime = AgentRuntime(settings, model)
    runtime.extensions = ExtensionRuntime(output.parent / "agent-chain-extensions")

    now = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    try:
        with database.session_factory() as db:
            selected_scenarios = SCENARIOS[
                args.story_start - 1:args.story_start - 1 + args.story_count
            ]
            for story_index, scenario in enumerate(selected_scenarios, args.story_start):
                chat_id = f"benchmark-agent-chain-{story_index:02d}"
                chat = ChatRecord(
                    id=chat_id,
                    title=f"Agent chain story {story_index}",
                    system_prompt=(
                        "你是简洁的中文叙事助手。遵守用户给出的事实，每次只写两到三句话，"
                        "不得擅自改变数字、地点、承诺或物品归属。"
                    ),
                    created_at=now,
                    updated_at=now,
                )
                db.add(chat)
                db.commit()

                for turn_index, prompt in enumerate(scenario_prompts(scenario), 1):
                    message = MessageRecord(
                        id=str(uuid4()),
                        chat_id=chat_id,
                        role="user",
                        content=prompt,
                        created_at=datetime.now(UTC),
                    )
                    db.add(message)
                    db.commit()
                    model.take_calls()
                    started = perf_counter()
                    error = ""
                    try:
                        result = await runtime.run_turn(db, chat, message)
                    except Exception as exc:
                        db.rollback()
                        result = None
                        error = f"{type(exc).__name__}: {exc}"[:1000]
                    elapsed_ms = (perf_counter() - started) * 1000
                    calls = model.take_calls()
                    input_tokens = sum(int(item.get("input_tokens") or 0) for item in calls)
                    output_tokens = sum(int(item.get("output_tokens") or 0) for item in calls)
                    cost = (
                        input_tokens * INPUT_PRICE_RMB_PER_MILLION
                        + output_tokens * OUTPUT_PRICE_RMB_PER_MILLION
                    ) / 1_000_000
                    trace_types = (
                        [trace.event_type for trace in result.traces]
                        if result is not None else []
                    )
                    failed = result is None or any(
                        event_type in {"model_error", "memory_pipeline_error"}
                        for event_type in trace_types
                    )
                    rows.append({
                        "story": story_index,
                        "turn": turn_index,
                        "status": "failed" if failed else "ok",
                        "error": error,
                        "prompt": prompt,
                        "assistant_chars": (
                            len(result.assistant_message.content) if result is not None else 0
                        ),
                        "end_to_end_latency_ms": round(elapsed_ms, 2),
                        "api_calls": len(calls),
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "standard_price_cost_rmb": round(cost, 6),
                        "trace_types": trace_types,
                        "state_proposals": (
                            len(result.state_proposals) if result is not None else 0
                        ),
                        "audit_issues": len(result.audit_issues) if result is not None else 0,
                    })
                    partial = {
                        "metadata": {
                            "generated_at": datetime.now(UTC).isoformat(),
                            "model": settings.llm_model,
                            "planned_stories": args.story_count,
                            "completed_turns": len(rows),
                            "status": "running",
                        },
                        "turns": rows,
                    }
                    output.write_text(
                        json.dumps(partial, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print(
                        json.dumps(
                            {
                                "completed_turns": len(rows),
                                "planned_turns": args.story_count * 5,
                                "last_status": rows[-1]["status"],
                                "last_latency_ms": rows[-1]["end_to_end_latency_ms"],
                                "cumulative_api_calls": sum(
                                    int(row["api_calls"]) for row in rows
                                ),
                                "cumulative_tokens": sum(
                                    int(row["input_tokens"]) + int(row["output_tokens"])
                                    for row in rows
                                ),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    if result is None:
                        break
    finally:
        await runtime.shutdown()
        database.engine.dispose()

    latencies = [float(row["end_to_end_latency_ms"]) for row in rows]
    total_input = sum(int(row["input_tokens"]) for row in rows)
    total_output = sum(int(row["output_tokens"]) for row in rows)
    total_cost = sum(float(row["standard_price_cost_rmb"]) for row in rows)
    payload = {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": settings.llm_model,
            "turns": len(rows),
            "stories": args.story_count,
            "max_output_tokens": settings.max_output_tokens,
            "max_agent_steps": settings.max_agent_steps,
            "scope": "fixed synthetic end-to-end AgentRuntime benchmark",
        },
        "summary": {
            "successful_turns": sum(row["status"] == "ok" for row in rows),
            "failed_turns": sum(row["status"] == "failed" for row in rows),
            "total_api_calls": sum(int(row["api_calls"]) for row in rows),
            "mean_api_calls_per_turn": statistics.mean(int(row["api_calls"]) for row in rows),
            "mean_input_tokens_per_turn": total_input / len(rows),
            "mean_output_tokens_per_turn": total_output / len(rows),
            "mean_standard_price_cost_rmb_per_turn": total_cost / len(rows),
            "total_standard_price_cost_rmb": total_cost,
            "mean_end_to_end_latency_ms": statistics.mean(latencies),
            "p95_end_to_end_latency_ms": percentile(latencies, 0.95),
        },
        "turns": rows,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
