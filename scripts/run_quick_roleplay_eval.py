"""Run a small role-play consistency evaluation through production services.

The suite is intentionally lightweight. It uses the real MemoryService for
retrieval and evidence selection, and NarrativeDeltaService for world-ledger
state extraction. API credentials are never written to the output file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


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


EARLY_RECALL_CASES = [
    ("early-01", "旧王留下的密门口令是什么？", "赤月无声", "六十天前，旧王把密门口令定为“赤月无声”，此后从未更改。"),
    ("early-02", "白塔盟约规定谁保管星纹钥匙？", "守钟人", "初次结盟时双方约定，星纹钥匙始终由守钟人保管。"),
    ("early-03", "阿岚左肩伤疤来自哪场战斗？", "灰桥战役", "远征第一章中，阿岚在灰桥战役留下了左肩伤疤。"),
    ("early-04", "进入雾港地下河的入口在哪里？", "废弃盐仓", "队伍最早发现，雾港地下河唯一安全入口藏在废弃盐仓。"),
    ("early-05", "银铃遇到什么情况会失效？", "月食", "铸铃师曾明确警告：银铃只会在月食期间失效。"),
    ("early-06", "北境停战条款禁止携带什么进入议事厅？", "弓弩", "北境停战条款第三项规定，任何人不得携带弓弩进入议事厅。"),
    ("early-07", "洛书真正的出生地是哪里？", "栖霞岛", "族谱密页确认，洛书真正出生于栖霞岛。"),
    ("early-08", "解除石化诅咒需要哪种花？", "夜昙", "神殿碑文记载，解除石化诅咒必须使用盛开的夜昙。"),
    ("early-09", "黑林中的安全路标是什么颜色？", "蓝色", "猎人最初教给队伍的规则是：黑林中只有蓝色路标可信。"),
    ("early-10", "海镜预言生效的前提是什么？", "双月同升", "海镜预言的原文写明，预言只在双月同升时生效。"),
]


QA_CASES = [
    {
        "case_id": "persona-01",
        "category": "persona_adherence",
        "documents": ["夏栀从不饮酒，即使在正式宴会上也只喝清茶。", "夏栀今天受邀参加城主宴会。"],
        "query": "侍者递来烈酒时，夏栀会怎么做？只回答“拒绝饮酒”或“接受饮酒”。",
        "expected": ["拒绝饮酒"],
        "forbidden": ["接受饮酒"],
    },
    {
        "case_id": "persona-02",
        "category": "persona_adherence",
        "documents": ["言川把诚实视为不可违背的原则，拒绝伪造证词。", "商人请求言川替他编造一份证词。"],
        "query": "言川会接受商人的请求吗？只回答“拒绝编造”或“接受编造”。",
        "expected": ["拒绝编造"],
        "forbidden": ["接受编造"],
    },
    {
        "case_id": "persona-03",
        "category": "persona_adherence",
        "documents": ["雪弥极度惧怕明火，不会主动触碰燃烧物。", "火盆中有一封尚未烧尽的信。"],
        "query": "雪弥会徒手伸进火盆吗？只回答“不会触碰”或“会触碰”。",
        "expected": ["不会触碰"],
        "forbidden": ["会触碰"],
    },
    {
        "case_id": "persona-04",
        "category": "persona_adherence",
        "documents": ["青禾承诺不伤害已经投降的人。", "敌方斥候已经放下武器并正式投降。"],
        "query": "青禾会继续攻击斥候吗？只回答“停止攻击”或“继续攻击”。",
        "expected": ["停止攻击"],
        "forbidden": ["继续攻击"],
    },
    {
        "case_id": "identity-01",
        "category": "identity_consistency",
        "documents": ["锦书的身份是药师，从未担任军官。", "锦书目前在南城医馆工作。"],
        "query": "锦书的身份是什么？只回答“药师”或“军官”。",
        "expected": ["药师"],
        "forbidden": ["军官"],
    },
    {
        "case_id": "identity-02",
        "category": "identity_consistency",
        "documents": ["凌霄已经退出黑旗团，当前效忠白塔议会。", "黑旗团仍在北境活动。"],
        "query": "凌霄当前效忠哪个阵营？只回答阵营名称。",
        "expected": ["白塔议会"],
        "forbidden": ["黑旗团"],
    },
    {
        "case_id": "identity-03",
        "category": "identity_consistency",
        "documents": ["照夜是人类观星师，不是精灵。", "照夜正在研究精灵留下的星图。"],
        "query": "照夜是什么种族？只回答“人类”或“精灵”。",
        "expected": ["人类"],
        "forbidden": ["精灵"],
    },
    {
        "case_id": "identity-04",
        "category": "identity_consistency",
        "documents": ["闻溪是商会书记，负责登记货运凭证。", "守城队长今天来到商会查账。"],
        "query": "闻溪担任什么职务？只回答“商会书记”或“守城队长”。",
        "expected": ["商会书记"],
        "forbidden": ["守城队长"],
    },
    {
        "case_id": "item-01",
        "category": "item_hallucination",
        "documents": ["阿岚当前行囊中只有地图和麻绳。", "银钥匙仍由旅店老板保管，阿岚从未获得它。"],
        "query": "阿岚当前拥有银钥匙吗？只回答“有”或“没有”。",
        "expected": ["没有"],
        "forbidden": ["有"],
    },
    {
        "case_id": "item-02",
        "category": "item_hallucination",
        "documents": ["白芷已经把长剑交给守门人，当前不再持有长剑。", "白芷仍持有一瓶净水。"],
        "query": "白芷当前拥有长剑吗？只回答“有”或“没有”。",
        "expected": ["没有"],
        "forbidden": ["有"],
    },
    {
        "case_id": "item-03",
        "category": "item_hallucination",
        "documents": ["丹砂已经用完最后一瓶治疗药水。", "丹砂的背包里还有火石和账本。"],
        "query": "丹砂当前还有治疗药水吗？只回答“有”或“没有”。",
        "expected": ["没有"],
        "forbidden": ["有"],
    },
    {
        "case_id": "item-04",
        "category": "item_hallucination",
        "documents": ["青禾从未得到星纹戒指，戒指一直属于祭司。", "青禾当前持有木弓和短刀。"],
        "query": "青禾当前拥有星纹戒指吗？只回答“有”或“没有”。",
        "expected": ["没有"],
        "forbidden": ["有"],
    },
    {
        "case_id": "location-01",
        "category": "location_consistency",
        "documents": ["阿岚已经离开北门，当前抵达钟楼顶层。", "此前阿岚曾在北门调查车辙。"],
        "query": "阿岚当前在哪里？只回答地点名称。",
        "expected": ["钟楼顶层"],
        "forbidden": ["北门"],
    },
    {
        "case_id": "location-02",
        "category": "location_consistency",
        "documents": ["白芷已经从黑林返回，当前位于松风旅店。", "白芷上午曾在黑林采药。"],
        "query": "白芷当前在哪里？只回答地点名称。",
        "expected": ["松风旅店"],
        "forbidden": ["黑林"],
    },
    {
        "case_id": "location-03",
        "category": "location_consistency",
        "documents": ["丹砂已经离开旧码头，当前进入白塔档案室。", "丹砂昨日曾在旧码头接头。"],
        "query": "丹砂当前在哪里？只回答地点名称。",
        "expected": ["白塔档案室"],
        "forbidden": ["旧码头"],
    },
    {
        "case_id": "location-04",
        "category": "location_consistency",
        "documents": ["照夜已经走出观星台，当前到达南坡营地。", "照夜入夜前曾在观星台记录星象。"],
        "query": "照夜当前在哪里？只回答地点名称。",
        "expected": ["南坡营地"],
        "forbidden": ["观星台"],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmark-results" / "quick-roleplay-eval.json",
    )
    return parser.parse_args()


def normalize(text: str) -> str:
    return re.sub(r"[\s。！？；，、,.!?;:'\"“”‘’]", "", text).casefold()


def answer_passes(answer: str, expected: list[str], forbidden: list[str]) -> bool:
    value = normalize(answer)
    expected_ok = any(normalize(item) == value for item in expected)
    forbidden_ok = all(normalize(item) != value for item in forbidden)
    return expected_ok and forbidden_ok


def canonical_value(value: Any) -> str:
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
    if canonical_value(expected.get("new_value")) != canonical_value(actual.get("new_value")):
        return False
    subject = entity_subject(str(expected.get("entity", "")))
    actual_identity = f"{actual.get('entity', '')} {actual.get('key', '')}".casefold()
    if subject and subject not in actual_identity:
        return False
    expected_key = str(expected.get("key", "")).strip().casefold()
    if expected_key == "状态" and "任务" in str(expected.get("entity", "")):
        return True
    return not expected_key or expected_key in actual_identity


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
        key = (
            str(item.get("entity", "")).strip().casefold(),
            str(item.get("key", "")).strip().casefold(),
            canonical_value(item.get("new_value")),
        )
        unique[key] = item
    return list(unique.values())


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


def make_database(path: Path) -> Database:
    if path.exists():
        path.unlink()
    database = Database(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(bind=database.engine)
    return database


def seed_memories(database: Database) -> dict[str, str]:
    now = datetime.now(UTC)
    case_chat_ids: dict[str, str] = {}
    with database.session_factory() as db:
        for case_id, query, expected, relevant_text in EARLY_RECALL_CASES:
            del query, expected
            chat_id = f"quick-{case_id}"
            case_chat_ids[case_id] = chat_id
            db.add(ChatRecord(id=chat_id, title=case_id, system_prompt="", created_at=now, updated_at=now))
            documents = [
                (f"{case_id}-relevant", relevant_text, 72, 0.95),
                (f"{case_id}-d1", "三天前，队伍在集市补充了食物和净水。", 3, 0.45),
                (f"{case_id}-d2", "两天前，守卫更换了城门值班次序。", 2, 0.45),
                (f"{case_id}-d3", "昨天，旅店大厅举行了一场普通的商队会议。", 1, 0.45),
                (f"{case_id}-d4", "今天清晨，天气转晴，主路恢复通行。", 0, 0.45),
            ]
            for memory_id, text, age_days, importance in documents:
                from backend.llm import local_embedding
                db.add(MemoryRecord(
                    id=memory_id,
                    chat_id=chat_id,
                    kind=MemoryKind.EPISODIC.value,
                    content=text,
                    importance=importance,
                    embedding_json=json_dumps(local_embedding(text)),
                    source_message_id=None,
                    variant_id=None,
                    variant_ids_json="[]",
                    access_count=0,
                    last_accessed_at=None,
                    created_at=now - timedelta(days=age_days),
                ))

        for case in QA_CASES:
            chat_id = f"quick-{case['case_id']}"
            case_chat_ids[case["case_id"]] = chat_id
            db.add(ChatRecord(id=chat_id, title=case["case_id"], system_prompt="", created_at=now, updated_at=now))
            for index, text in enumerate(case["documents"]):
                from backend.llm import local_embedding
                db.add(MemoryRecord(
                    id=f"{case['case_id']}-m{index + 1}",
                    chat_id=chat_id,
                    kind=MemoryKind.EPISODIC.value,
                    content=text,
                    importance=0.9 if index == 0 else 0.7,
                    embedding_json=json_dumps(local_embedding(text)),
                    source_message_id=None,
                    variant_id=None,
                    variant_ids_json="[]",
                    access_count=0,
                    last_accessed_at=None,
                    created_at=now - timedelta(days=index),
                ))
        db.commit()
    return case_chat_ids


async def run_retrieval(
    database: Database,
    model: OpenAICompatibleClient,
    settings: Settings,
    chat_ids: dict[str, str],
) -> list[dict[str, Any]]:
    service = MemoryService(settings)
    rows: list[dict[str, Any]] = []
    with database.session_factory() as db:
        for case_id, query, expected, _ in EARLY_RECALL_CASES:
            results = await service.search(db, model, chat_ids[case_id], query, limit=3)
            ranked = [item.record.id for item in results]
            relevant_id = f"{case_id}-relevant"
            rank = next((index for index, item_id in enumerate(ranked, 1) if item_id == relevant_id), None)
            row = {
                "case_id": case_id,
                "expected": expected,
                "rank": rank,
                "ranked_ids": ranked,
                "recall_at_1": int(rank == 1),
                "recall_at_3": int(rank is not None and rank <= 3),
            }
            rows.append(row)
            print(f"retrieval {case_id}: rank={rank}", flush=True)
    return rows


async def run_qa(
    database: Database,
    model: OpenAICompatibleClient,
    settings: Settings,
    chat_ids: dict[str, str],
) -> list[dict[str, Any]]:
    service = MemoryService(settings)
    rows: list[dict[str, Any]] = []
    with database.session_factory() as db:
        for index, case in enumerate(QA_CASES, 1):
            results = await service.search(db, model, chat_ids[case["case_id"]], case["query"], limit=5)
            evidence = "\n".join(f"- {item.record.content}" for item in results)
            reply = await model.complete([
                {
                    "role": "system",
                    "content": (
                        "你是长篇角色扮演事实核对器。只能依据给出的当前事实回答，"
                        "不得补充不存在的物品、身份、地点或行为。严格遵守问题指定的输出格式。"
                    ),
                },
                {"role": "user", "content": f"【当前事实】\n{evidence}\n\n【问题】\n{case['query']}"},
            ])
            answer = reply.content or ""
            passed = answer_passes(answer, case["expected"], case["forbidden"])
            rows.append({
                "case_id": case["case_id"],
                "category": case["category"],
                "answer": answer,
                "expected": case["expected"],
                "forbidden": case["forbidden"],
                "passed": passed,
                "retrieved_ids": [item.record.id for item in results],
            })
            print(f"qa {index}/{len(QA_CASES)} {case['case_id']}: {'pass' if passed else 'fail'}", flush=True)
    return rows


async def run_state(
    model: OpenAICompatibleClient, state_cases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    service = NarrativeDeltaService()
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(state_cases, 1):
        payload = await service._extract(model, case["user_text"], case["assistant_text"])
        actual = extracted_changes(payload)
        tp, fp, fn = fact_counts(case["expected_state_changes"], actual)
        exact_case = fp == 0 and fn == 0
        rows.append({
            "case_id": case["case_id"],
            "expected": case["expected_state_changes"],
            "actual": actual,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "exact_case": exact_case,
        })
        print(f"state {index}/{len(state_cases)} {case['case_id']}: {'pass' if exact_case else 'fail'}", flush=True)
    return rows


def summarize(
    retrieval_rows: list[dict[str, Any]],
    qa_rows: list[dict[str, Any]],
    state_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    def category_rate(category: str) -> dict[str, Any]:
        rows = [row for row in qa_rows if row["category"] == category]
        passed = sum(bool(row["passed"]) for row in rows)
        return {"passed": passed, "total": len(rows), "rate": passed / len(rows) if rows else 0.0}

    tp = sum(row["tp"] for row in state_rows)
    fp = sum(row["fp"] for row in state_rows)
    fn = sum(row["fn"] for row in state_rows)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    exact = sum(bool(row["exact_case"]) for row in state_rows)

    persona = category_rate("persona_adherence")
    identity = category_rate("identity_consistency")
    item = category_rate("item_hallucination")
    location = category_rate("location_consistency")
    setting_total = persona["total"] + identity["total"]
    setting_passed = persona["passed"] + identity["passed"]
    contradiction_total = item["total"] + location["total"]
    contradiction_passed = item["passed"] + location["passed"]

    return {
        "early_plot_recall": {
            "cases": len(retrieval_rows),
            "recall_at_1": sum(row["recall_at_1"] for row in retrieval_rows) / len(retrieval_rows),
            "recall_at_3": sum(row["recall_at_3"] for row in retrieval_rows) / len(retrieval_rows),
        },
        "persona_adherence": persona,
        "identity_consistency": identity,
        "combined_setting_adherence": {
            "passed": setting_passed,
            "total": setting_total,
            "rate": setting_passed / setting_total,
        },
        "unsupported_item_rate": {
            "violations": item["total"] - item["passed"],
            "total": item["total"],
            "rate": (item["total"] - item["passed"]) / item["total"],
        },
        "location_conflict_rate": {
            "violations": location["total"] - location["passed"],
            "total": location["total"],
            "rate": (location["total"] - location["passed"]) / location["total"],
        },
        "combined_setting_violation_rate": {
            "violations": contradiction_total - contradiction_passed,
            "total": contradiction_total,
            "rate": (contradiction_total - contradiction_passed) / contradiction_total,
        },
        "world_ledger_update": {
            "cases": len(state_rows),
            "exact_cases": exact,
            "exact_case_rate": exact / len(state_rows),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
    }


async def async_main() -> int:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env()
    if settings.provider_mode == "unconfigured":
        raise RuntimeError("No configured model in data/settings.json or environment")
    settings = replace(
        settings,
        temperature=0.0,
        max_output_tokens=256,
        embedding_model=None,
        rerank_base_url=None,
        rerank_api_key=None,
        rerank_model=None,
        settings_file=None,
        langgraph_checkpoint_path=None,
    )
    db_path = args.output.parent / "quick-roleplay-eval.db"
    database = make_database(db_path)
    chat_ids = seed_memories(database)
    dataset = json.loads((ROOT / "evals" / "benchmark" / "cases.json").read_text(encoding="utf-8"))
    state_cases = dataset["state_cases"][:10]
    model = OpenAICompatibleClient(settings)
    try:
        await model.check_connection()
        retrieval_rows = await run_retrieval(database, model, settings, chat_ids)
        qa_rows = await run_qa(database, model, settings, chat_ids)
        state_rows = await run_state(model, state_cases)
        result = {
            "metadata": {
                "generated_at": datetime.now(UTC).isoformat(),
                "model": settings.llm_model,
                "temperature": settings.temperature,
                "suite": "Saraswati Quick Roleplay Consistency Eval v1",
                "notice": "Small synthetic quick test; use as a directional engineering result.",
            },
            "metrics": summarize(retrieval_rows, qa_rows, state_rows),
            "retrieval_rows": retrieval_rows,
            "qa_rows": qa_rows,
            "state_rows": state_rows,
        }
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result["metrics"], ensure_ascii=False, indent=2), flush=True)
        return 0
    finally:
        await model.close()
        database.engine.dispose()
        if db_path.exists():
            db_path.unlink()


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
