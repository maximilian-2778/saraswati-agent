"""Evaluate long-dialogue consistency through the production context pipeline.

The suite seeds two deterministic 50-turn role-play histories. Facts are placed
outside the recent-message window, followed by unrelated dialogue. Final
questions compare Saraswati's real ContextBuilder/MemoryService path with the
same model receiving only the latest 16 messages. State-changing turns are also
processed by NarrativeDeltaService and replayed through StateService.

Credentials are loaded from the application's local settings and are never
written to the result file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.database import Base, Database  # noqa: E402
from backend.llm import local_embedding  # noqa: E402
from backend.models import ChatRecord, MemoryRecord, MessageRecord  # noqa: E402
from backend.providers.openai_compatible import OpenAICompatibleClient  # noqa: E402
from backend.schemas import MemoryKind  # noqa: E402
from backend.services.context import ContextBuilder  # noqa: E402
from backend.services.memory import MemoryService  # noqa: E402
from backend.services.narrative_delta import NarrativeDeltaService  # noqa: E402
from backend.services.narrative_memory import NarrativeMemoryService  # noqa: E402
from backend.services.roleplay_graph import RoleplayGraphService  # noqa: E402
from backend.services.state import StateService  # noqa: E402
from backend.services.world_engine import WorldEngineService  # noqa: E402
from backend.utils import json_dumps  # noqa: E402


RECENT_MESSAGE_LIMIT = 16
TURNS_PER_STORY = 50


@dataclass(frozen=True, slots=True)
class StorySpec:
    story_id: str
    title: str
    events: dict[int, dict[str, Any]]
    questions: tuple[dict[str, Any], ...]
    state_events: tuple[dict[str, Any], ...]
    final_state: tuple[dict[str, Any], ...]


STORIES = (
    StorySpec(
        story_id="mist-harbor",
        title="雾港钟楼",
        events={
            2: {
                "user": "我检查旧王留下的密函，里面有没有进入密门的口令？",
                "assistant": "密函末页写得很清楚：密门口令是“赤月无声”，此后没有更改。",
                "importance": 0.98,
                "fact": "passphrase",
            },
            4: {
                "user": "先记住林澈在宴席上的规矩，他从不饮酒，只喝清茶。",
                "assistant": "林澈确认这条原则：无论谁劝酒，他都会拒绝饮酒，只喝清茶。",
                "importance": 0.96,
                "fact": "persona",
            },
            6: {
                "user": "林澈终于公开自己的真实身份。",
                "assistant": "他承认自己是旧王室最后一名档案官，过去一直用商旅身份掩护。",
                "importance": 0.96,
                "fact": "identity",
            },
            10: {
                "user": "结清渡船和补给费用后，请核对队伍金币。",
                "assistant": "账目已经核对完毕，队伍金币明确变为42枚。",
                "importance": 0.92,
                "fact": "coins_old",
            },
            12: {
                "user": "林澈正式选择效忠哪个阵营？",
                "assistant": "林澈退出灰帆商会，宣誓效忠白塔议会；当前阵营是白塔议会。",
                "importance": 0.97,
                "fact": "faction",
            },
            14: {
                "user": "守钟人暂时把星纹钥匙交给林澈，让他开启档案室。",
                "assistant": "林澈接过星纹钥匙并随身保管，准备前往钟楼。",
                "importance": 0.78,
                "fact": "key_old_owner",
            },
            18: {
                "user": "我们先在旧码头查完这批货单。",
                "assistant": "林澈停留在旧码头，逐页核对货单与船期。",
                "importance": 0.72,
                "fact": "location_old",
            },
            20: {
                "user": "治疗结束后检查林澈的生命值。",
                "assistant": "治疗已经完成，林澈当前生命值明确为78点。",
                "importance": 0.92,
                "fact": "health",
            },
            22: {
                "user": "林澈和守钟人约定了什么联络信号？",
                "assistant": "双方约定：黎明前连续敲三次钟，就是档案已经安全转移的信号。",
                "importance": 0.97,
                "fact": "promise",
            },
            24: {
                "user": "档案室已经打开，把星纹钥匙归还原主。",
                "assistant": "林澈将星纹钥匙交还守钟人。现在钥匙由守钟人保管，林澈不再持有。",
                "importance": 0.99,
                "fact": "key_current_owner",
            },
            28: {
                "user": "清点林澈的背包，确认有没有黑铁王冠。",
                "assistant": "清点结果显示林澈从未获得黑铁王冠，背包中也没有这件物品。",
                "importance": 0.95,
                "fact": "absent_item",
            },
            30: {
                "user": "离开旧码头后，我们转移到哪里？",
                "assistant": "队伍已经离开旧码头，林澈当前位于钟楼档案室。",
                "importance": 0.99,
                "fact": "location_current",
            },
            35: {
                "user": "密函是否已经交到白塔议会？",
                "assistant": "密函已经安全交付，任务“雾港密约”的状态变为已完成。",
                "importance": 0.94,
                "fact": "quest",
            },
            40: {
                "user": "采购封蜡和药品后，再核对一次队伍金币。",
                "assistant": "新账目确认无误，队伍金币从42枚变为31枚，当前余额是31枚。",
                "importance": 0.99,
                "fact": "coins_current",
            },
        },
        questions=(
            {
                "case_id": "mist-passphrase",
                "category": "early_plot",
                "query": "旧王密门的口令是什么？只回答口令。",
                "expected": ["赤月无声"],
                "forbidden": [],
                "relevant_fact": "passphrase",
            },
            {
                "case_id": "mist-persona",
                "category": "persona_adherence",
                "query": "宴会上有人向林澈递酒，他会怎么做？只回答“拒绝饮酒”或“接受饮酒”。",
                "expected": ["拒绝饮酒"],
                "forbidden": ["接受饮酒"],
                "relevant_fact": "persona",
            },
            {
                "case_id": "mist-identity",
                "category": "identity_consistency",
                "query": "林澈的真实身份是什么？只回答身份名称。",
                "expected": ["旧王室最后一名档案官", "旧王室档案官"],
                "forbidden": ["商旅"],
                "relevant_fact": "identity",
            },
            {
                "case_id": "mist-faction",
                "category": "faction_consistency",
                "query": "林澈当前效忠哪个阵营？只回答阵营名称。",
                "expected": ["白塔议会"],
                "forbidden": ["灰帆商会"],
                "relevant_fact": "faction",
            },
            {
                "case_id": "mist-item-owner",
                "category": "item_consistency",
                "query": "星纹钥匙现在由谁保管？只回答人物名称。",
                "expected": ["守钟人"],
                "forbidden": ["林澈"],
                "relevant_fact": "key_current_owner",
            },
            {
                "case_id": "mist-location",
                "category": "location_consistency",
                "query": "林澈当前在哪里？只回答地点名称。",
                "expected": ["钟楼档案室"],
                "forbidden": ["旧码头"],
                "relevant_fact": "location_current",
            },
            {
                "case_id": "mist-promise",
                "category": "promise_consistency",
                "query": "档案安全转移的联络信号是什么？只回答信号。",
                "expected": ["黎明前连续敲三次钟", "连续敲三次钟"],
                "forbidden": [],
                "relevant_fact": "promise",
            },
            {
                "case_id": "mist-absent-item",
                "category": "unsupported_item",
                "query": "林澈现在拥有黑铁王冠吗？只回答“有”或“没有”。",
                "expected": ["没有"],
                "forbidden": ["有"],
                "relevant_fact": "absent_item",
            },
            {
                "case_id": "mist-coins",
                "category": "state_value",
                "query": "队伍当前有多少枚金币？只回答数字。",
                "expected": ["31"],
                "forbidden": ["42"],
                "relevant_fact": "coins_current",
            },
        ),
        state_events=(
            {"turn": 10, "expected": [{"entity": "队伍", "key": "金币", "new_value": 42}]},
            {"turn": 20, "expected": [{"entity": "林澈", "key": "生命值", "new_value": 78}]},
            {"turn": 35, "expected": [{"entity": "任务:雾港密约", "key": "状态", "new_value": "已完成"}]},
            {"turn": 40, "expected": [{"entity": "队伍", "key": "金币", "new_value": 31}]},
        ),
        final_state=(
            {"entity": "队伍", "key": "金币", "new_value": 31},
            {"entity": "林澈", "key": "生命值", "new_value": 78},
            {"entity": "任务:雾港密约", "key": "状态", "new_value": "已完成"},
        ),
    ),
    StorySpec(
        story_id="twin-moons",
        title="双月观星台",
        events={
            2: {
                "user": "神殿碑文写的石化解药是什么？",
                "assistant": "碑文确认：解除石化诅咒必须使用盛开的夜昙，普通药草无效。",
                "importance": 0.98,
                "fact": "cure",
            },
            4: {
                "user": "记住照夜的底线：她绝不伪造观测记录。",
                "assistant": "照夜把真实记录视为不可违背的原则，即使受到威胁也会拒绝伪造数据。",
                "importance": 0.96,
                "fact": "persona",
            },
            6: {
                "user": "照夜说明自己的种族和职业。",
                "assistant": "照夜是人类观星师，并非精灵；她负责记录双月轨迹。",
                "importance": 0.96,
                "fact": "identity",
            },
            10: {
                "user": "补给车抵达后，核对营地药草数量。",
                "assistant": "仓库登记完成，营地药草明确变为18份。",
                "importance": 0.92,
                "fact": "herbs_old",
            },
            12: {
                "user": "照夜离开北境学院后加入了哪里？",
                "assistant": "照夜已经离开北境学院，当前所属阵营是南坡学社。",
                "importance": 0.97,
                "fact": "faction",
            },
            14: {
                "user": "藏镜阁把海镜借给照夜观测双月。",
                "assistant": "照夜接过海镜，暂时随身保管，用它校准观星台。",
                "importance": 0.78,
                "fact": "mirror_old_owner",
            },
            18: {
                "user": "我们先去星桥记录潮汐。",
                "assistant": "照夜到达星桥，并在桥中央完成第一轮潮汐记录。",
                "importance": 0.72,
                "fact": "location_old",
            },
            20: {
                "user": "仪式结束后检查照夜的法力值。",
                "assistant": "仪式消耗已经结算，照夜当前法力值明确为63点。",
                "importance": 0.92,
                "fact": "mana",
            },
            22: {
                "user": "照夜与学社约定如何标记预言开始生效？",
                "assistant": "约定的信号是：双月同升时点燃一盏蓝灯，表示海镜预言开始生效。",
                "importance": 0.97,
                "fact": "promise",
            },
            24: {
                "user": "观测完成，把海镜送回藏镜阁。",
                "assistant": "照夜已经归还海镜。现在海镜由藏镜阁保管，照夜不再持有。",
                "importance": 0.99,
                "fact": "mirror_current_owner",
            },
            28: {
                "user": "检查照夜的装备，确认有没有龙骨短笛。",
                "assistant": "装备清单里没有龙骨短笛，照夜此前也从未得到过它。",
                "importance": 0.95,
                "fact": "absent_item",
            },
            30: {
                "user": "离开星桥后我们在哪里扎营？",
                "assistant": "队伍已经离开星桥，照夜当前位于南坡营地。",
                "importance": 0.99,
                "fact": "location_current",
            },
            35: {
                "user": "双月轨迹校准任务进展如何？",
                "assistant": "最后一组数据已经校准，任务“双月校准”的状态变为已完成。",
                "importance": 0.94,
                "fact": "quest",
            },
            40: {
                "user": "配制解药用了七份药草，请更新库存。",
                "assistant": "库存重新核对后，营地药草从18份变为11份，当前数量是11份。",
                "importance": 0.99,
                "fact": "herbs_current",
            },
        },
        questions=(
            {
                "case_id": "moon-cure",
                "category": "early_plot",
                "query": "解除石化诅咒需要哪种花？只回答花名。",
                "expected": ["夜昙"],
                "forbidden": [],
                "relevant_fact": "cure",
            },
            {
                "case_id": "moon-persona",
                "category": "persona_adherence",
                "query": "有人要求照夜伪造观测记录，她会怎么做？只回答“拒绝伪造”或“接受伪造”。",
                "expected": ["拒绝伪造"],
                "forbidden": ["接受伪造"],
                "relevant_fact": "persona",
            },
            {
                "case_id": "moon-identity",
                "category": "identity_consistency",
                "query": "照夜是什么种族、从事什么职业？只回答“人类观星师”或“精灵祭司”。",
                "expected": ["人类观星师"],
                "forbidden": ["精灵祭司"],
                "relevant_fact": "identity",
            },
            {
                "case_id": "moon-faction",
                "category": "faction_consistency",
                "query": "照夜当前属于哪个阵营？只回答阵营名称。",
                "expected": ["南坡学社"],
                "forbidden": ["北境学院"],
                "relevant_fact": "faction",
            },
            {
                "case_id": "moon-item-owner",
                "category": "item_consistency",
                "query": "海镜现在由谁保管？只回答名称。",
                "expected": ["藏镜阁"],
                "forbidden": ["照夜"],
                "relevant_fact": "mirror_current_owner",
            },
            {
                "case_id": "moon-location",
                "category": "location_consistency",
                "query": "照夜当前在哪里？只回答地点名称。",
                "expected": ["南坡营地"],
                "forbidden": ["星桥"],
                "relevant_fact": "location_current",
            },
            {
                "case_id": "moon-promise",
                "category": "promise_consistency",
                "query": "海镜预言开始生效的约定信号是什么？只回答信号。",
                "expected": ["双月同升时点燃一盏蓝灯", "点燃一盏蓝灯"],
                "forbidden": [],
                "relevant_fact": "promise",
            },
            {
                "case_id": "moon-absent-item",
                "category": "unsupported_item",
                "query": "照夜现在拥有龙骨短笛吗？只回答“有”或“没有”。",
                "expected": ["没有"],
                "forbidden": ["有"],
                "relevant_fact": "absent_item",
            },
            {
                "case_id": "moon-herbs",
                "category": "state_value",
                "query": "营地当前有多少份药草？只回答数字。",
                "expected": ["11"],
                "forbidden": ["18"],
                "relevant_fact": "herbs_current",
            },
        ),
        state_events=(
            {"turn": 10, "expected": [{"entity": "营地", "key": "药草", "new_value": 18}]},
            {"turn": 20, "expected": [{"entity": "照夜", "key": "法力值", "new_value": 63}]},
            {"turn": 35, "expected": [{"entity": "任务:双月校准", "key": "状态", "new_value": "已完成"}]},
            {"turn": 40, "expected": [{"entity": "营地", "key": "药草", "new_value": 11}]},
        ),
        final_state=(
            {"entity": "营地", "key": "药草", "new_value": 11},
            {"entity": "照夜", "key": "法力值", "new_value": 63},
            {"entity": "任务:双月校准", "key": "状态", "new_value": "已完成"},
        ),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmark-results" / "long-dialogue-eval.json",
    )
    return parser.parse_args()


def normalize(text: str) -> str:
    return re.sub(r"[\s。！？；，、,.!?;:'\"“”‘’]", "", text).casefold()


def answer_passes(answer: str, expected: list[str], forbidden: list[str]) -> bool:
    value = normalize(answer)
    return any(normalize(item) == value for item in expected) and all(
        normalize(item) != value for item in forbidden
    )


def selected_forbidden(answer: str, forbidden: list[str]) -> bool:
    value = normalize(answer)
    return any(normalize(item) == value for item in forbidden)


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
    value = entity.strip().casefold().replace("：", ":")
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
            result.append(
                {
                    "entity": number.get("entity") or "剧情数值",
                    "key": number.get("key"),
                    "new_value": value,
                }
            )
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in result:
        key = (
            str(item.get("entity", "")).strip().casefold(),
            str(item.get("key", "")).strip().casefold(),
            canonical_value(item.get("new_value")),
        )
        unique[key] = item
    return list(unique.values())


def make_database(path: Path) -> Database:
    if path.exists():
        path.unlink()
    database = Database(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(bind=database.engine)
    return database


def filler_turn(story: StorySpec, turn: int) -> tuple[str, str]:
    topics = (
        "天气与道路",
        "营地值班",
        "普通商队",
        "食物和净水",
        "地图边角",
        "远处鸟鸣",
        "篝火维护",
        "次日行程",
    )
    topic = topics[(turn - 1) % len(topics)]
    user = f"第{turn}轮，我们处理一下{topic}，不要推进关键线索。"
    assistant = (
        f"第{turn}轮的{topic}已经处理完毕。众人完成例行检查，"
        "没有获得新物品，也没有改变身份、阵营、约定、位置或精确状态。"
    )
    return user, assistant


def seed_histories(database: Database) -> dict[str, dict[str, str]]:
    base_time = datetime.now(UTC) - timedelta(days=50)
    fact_memory_ids: dict[str, dict[str, str]] = {}
    with database.session_factory() as db:
        for story_index, story in enumerate(STORIES):
            story_start = base_time + timedelta(days=story_index)
            db.add(
                ChatRecord(
                    id=story.story_id,
                    title=story.title,
                    system_prompt=(
                        "只依据本故事中已经确认的事实回答最终核对问题。"
                        "不得猜测，不得补充未出现的物品、地点、身份或数值。"
                        "严格遵守问题指定的输出格式。"
                    ),
                    created_at=story_start,
                    updated_at=story_start + timedelta(hours=TURNS_PER_STORY),
                )
            )
            db.flush()
            fact_memory_ids[story.story_id] = {}
            for turn in range(1, TURNS_PER_STORY + 1):
                event = story.events.get(turn)
                if event:
                    user_text = str(event["user"])
                    assistant_text = str(event["assistant"])
                    importance = float(event["importance"])
                else:
                    user_text, assistant_text = filler_turn(story, turn)
                    importance = 0.35
                user_id = f"{story.story_id}-u-{turn:02d}"
                assistant_id = f"{story.story_id}-a-{turn:02d}"
                created_at = story_start + timedelta(minutes=turn * 20)
                db.add_all(
                    [
                        MessageRecord(
                            id=user_id,
                            chat_id=story.story_id,
                            role="user",
                            content=user_text,
                            created_at=created_at,
                        ),
                        MessageRecord(
                            id=assistant_id,
                            chat_id=story.story_id,
                            role="assistant",
                            content=assistant_text,
                            created_at=created_at + timedelta(minutes=1),
                        ),
                    ]
                )
                db.flush()
                memory_id = f"{story.story_id}-m-{turn:02d}"
                memory_text = f"[第{turn}轮楼层摘要] {assistant_text}"
                db.add(
                    MemoryRecord(
                        id=memory_id,
                        chat_id=story.story_id,
                        kind=MemoryKind.EPISODIC.value,
                        content=memory_text,
                        importance=importance,
                        embedding_json=json_dumps(local_embedding(memory_text)),
                        source_message_id=assistant_id,
                        variant_id=None,
                        variant_ids_json="[]",
                        access_count=0,
                        last_accessed_at=None,
                        created_at=created_at + timedelta(minutes=1),
                    )
                )
                if event and event.get("fact"):
                    fact_memory_ids[story.story_id][str(event["fact"])] = memory_id
            db.commit()
    return fact_memory_ids


def build_services(settings: Settings) -> tuple[ContextBuilder, StateService]:
    memory = MemoryService(settings)
    state = StateService()
    narrative_memory = NarrativeMemoryService(settings, memory)
    context = ContextBuilder(
        settings,
        memory,
        state,
        narrative_memory,
        RoleplayGraphService(),
        WorldEngineService(),
    )
    return context, state


async def run_state_chain(
    database: Database,
    model: OpenAICompatibleClient,
    state_service: StateService,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    delta_service = NarrativeDeltaService()
    event_rows: list[dict[str, Any]] = []
    projection_rows: list[dict[str, Any]] = []
    with database.session_factory() as db:
        for story in STORIES:
            for item in story.state_events:
                turn = int(item["turn"])
                event = story.events[turn]
                payload = await delta_service._extract(
                    model,
                    str(event["user"]),
                    str(event["assistant"]),
                )
                actual = extracted_changes(payload)
                expected = list(item["expected"])
                tp, fp, fn = fact_counts(expected, actual)
                for change_index, change in enumerate(actual):
                    entity = str(change.get("entity", "")).strip()
                    key = str(change.get("key", "")).strip()
                    if not entity or not key:
                        continue
                    state_service.apply(
                        db,
                        story.story_id,
                        entity,
                        key,
                        change.get("new_value"),
                        reason=f"long-eval turn {turn}",
                        source_message_id=f"{story.story_id}-a-{turn:02d}",
                        event_fingerprint=f"{story.story_id}-{turn}-{change_index}",
                    )
                event_rows.append(
                    {
                        "story_id": story.story_id,
                        "turn": turn,
                        "expected": expected,
                        "actual": actual,
                        "tp": tp,
                        "fp": fp,
                        "fn": fn,
                        "exact_case": fp == 0 and fn == 0,
                    }
                )
                print(
                    f"state {story.story_id} turn {turn}: "
                    f"{'pass' if fp == 0 and fn == 0 else 'fail'}",
                    flush=True,
                )

            actual_projection = [
                {
                    "entity": entry.entity,
                    "key": entry.key,
                    "new_value": state_service.value(entry),
                }
                for entry in state_service.list_entries(db, story.story_id)
            ]
            expected_projection = list(story.final_state)
            tp, fp, fn = fact_counts(expected_projection, actual_projection)
            projection_rows.append(
                {
                    "story_id": story.story_id,
                    "expected": expected_projection,
                    "actual": actual_projection,
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "exact": fp == 0 and fn == 0,
                }
            )
    return event_rows, projection_rows


async def answer_question(
    model: OpenAICompatibleClient,
    messages: list[dict[str, Any]],
    query: str,
) -> str:
    prompt = list(messages)
    prompt.append({"role": "user", "content": query})
    reply = await model.complete(prompt)
    return (reply.content or "").strip()


async def run_questions(
    database: Database,
    model: OpenAICompatibleClient,
    context_builder: ContextBuilder,
    fact_memory_ids: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with database.session_factory() as db:
        for story in STORIES:
            chat = db.get(ChatRecord, story.story_id)
            if chat is None:
                raise RuntimeError(f"Missing seeded chat: {story.story_id}")
            recent_records = list(
                reversed(
                    db.scalars(
                        select(MessageRecord)
                        .where(MessageRecord.chat_id == story.story_id)
                        .order_by(MessageRecord.created_at.desc())
                        .limit(RECENT_MESSAGE_LIMIT)
                    ).all()
                )
            )
            baseline_messages: list[dict[str, Any]] = [
                {"role": "system", "content": chat.system_prompt}
            ]
            baseline_messages.extend(
                {"role": item.role, "content": item.content} for item in recent_records
            )

            for question in story.questions:
                query = str(question["query"])
                bundle = await context_builder.build(
                    db,
                    model,
                    chat,
                    query,
                    include_debug_content=False,
                )
                project_answer = await answer_question(model, bundle.messages, query)
                baseline_answer = await answer_question(model, baseline_messages, query)
                expected = list(question["expected"])
                forbidden = list(question["forbidden"])
                relevant_id = fact_memory_ids[story.story_id][str(question["relevant_fact"])]
                ranked_ids = [item.record.id for item in bundle.retrieved_memories]
                rank = next(
                    (index for index, memory_id in enumerate(ranked_ids, 1) if memory_id == relevant_id),
                    None,
                )
                row = {
                    "story_id": story.story_id,
                    "case_id": question["case_id"],
                    "category": question["category"],
                    "fact_turn": int(relevant_id.rsplit("-", 1)[1]),
                    "distance_to_query_turns": TURNS_PER_STORY - int(relevant_id.rsplit("-", 1)[1]),
                    "query": query,
                    "expected": expected,
                    "forbidden": forbidden,
                    "relevant_memory_id": relevant_id,
                    "retrieved_ids": ranked_ids,
                    "relevant_rank": rank,
                    "recall_at_1": int(rank == 1),
                    "recall_at_3": int(rank is not None and rank <= 3),
                    "recall_at_5": int(rank is not None and rank <= 5),
                    "project_answer": project_answer,
                    "project_passed": answer_passes(project_answer, expected, forbidden),
                    "project_forbidden_selected": selected_forbidden(project_answer, forbidden),
                    "recent_only_answer": baseline_answer,
                    "recent_only_passed": answer_passes(baseline_answer, expected, forbidden),
                    "recent_only_forbidden_selected": selected_forbidden(baseline_answer, forbidden),
                }
                rows.append(row)
                print(
                    f"qa {question['case_id']}: project="
                    f"{'pass' if row['project_passed'] else 'fail'}, recent="
                    f"{'pass' if row['recent_only_passed'] else 'fail'}, rank={rank}",
                    flush=True,
                )
    return rows


def rate(passed: int, total: int) -> dict[str, Any]:
    return {"passed": passed, "total": total, "rate": passed / total if total else 0.0}


def summarize_answers(rows: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for category in sorted({str(row["category"]) for row in rows}):
        selected = [row for row in rows if row["category"] == category]
        result[category] = rate(
            sum(bool(row[f"{prefix}_passed"]) for row in selected), len(selected)
        )
    result["overall"] = rate(
        sum(bool(row[f"{prefix}_passed"]) for row in rows), len(rows)
    )
    contradiction_rows = [
        row
        for row in rows
        if row["category"] in {"unsupported_item", "item_consistency", "location_consistency"}
    ]
    violations = sum(bool(row[f"{prefix}_forbidden_selected"]) for row in contradiction_rows)
    result["explicit_contradiction_rate"] = {
        "violations": violations,
        "total": len(contradiction_rows),
        "rate": violations / len(contradiction_rows) if contradiction_rows else 0.0,
    }
    return result


def summarize(
    question_rows: list[dict[str, Any]],
    state_rows: list[dict[str, Any]],
    projection_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    project = summarize_answers(question_rows, "project")
    recent = summarize_answers(question_rows, "recent_only")
    project_rate = float(project["overall"]["rate"])
    recent_rate = float(recent["overall"]["rate"])

    state_tp = sum(int(row["tp"]) for row in state_rows)
    state_fp = sum(int(row["fp"]) for row in state_rows)
    state_fn = sum(int(row["fn"]) for row in state_rows)
    precision = state_tp / (state_tp + state_fp) if state_tp + state_fp else 1.0
    recall = state_tp / (state_tp + state_fn) if state_tp + state_fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    projection_tp = sum(int(row["tp"]) for row in projection_rows)
    projection_fp = sum(int(row["fp"]) for row in projection_rows)
    projection_fn = sum(int(row["fn"]) for row in projection_rows)
    projection_precision = (
        projection_tp / (projection_tp + projection_fp)
        if projection_tp + projection_fp
        else 1.0
    )
    projection_recall = (
        projection_tp / (projection_tp + projection_fn)
        if projection_tp + projection_fn
        else 1.0
    )

    return {
        "long_dialogue": {
            "stories": len(STORIES),
            "turns_per_story": TURNS_PER_STORY,
            "total_turns": len(STORIES) * TURNS_PER_STORY,
            "total_messages": len(STORIES) * TURNS_PER_STORY * 2,
            "recent_message_limit": RECENT_MESSAGE_LIMIT,
            "questions": len(question_rows),
            "fact_turn_min": min(int(row["fact_turn"]) for row in question_rows),
            "fact_turn_max": max(int(row["fact_turn"]) for row in question_rows),
            "distance_to_query_turns_min": min(
                int(row["distance_to_query_turns"]) for row in question_rows
            ),
            "distance_to_query_turns_max": max(
                int(row["distance_to_query_turns"]) for row in question_rows
            ),
        },
        "retrieval": {
            "recall_at_1": sum(int(row["recall_at_1"]) for row in question_rows) / len(question_rows),
            "recall_at_3": sum(int(row["recall_at_3"]) for row in question_rows) / len(question_rows),
            "recall_at_5": sum(int(row["recall_at_5"]) for row in question_rows) / len(question_rows),
        },
        "project_context": project,
        "recent_only_baseline": recent,
        "project_vs_recent_only": {
            "absolute_improvement_points": (project_rate - recent_rate) * 100,
            "relative_improvement": (
                (project_rate - recent_rate) / recent_rate if recent_rate else None
            ),
        },
        "world_ledger_event_extraction": {
            "events": len(state_rows),
            "exact_events": sum(bool(row["exact_case"]) for row in state_rows),
            "exact_event_rate": sum(bool(row["exact_case"]) for row in state_rows) / len(state_rows),
            "tp": state_tp,
            "fp": state_fp,
            "fn": state_fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "world_ledger_final_projection": {
            "stories": len(projection_rows),
            "exact_stories": sum(bool(row["exact"]) for row in projection_rows),
            "exact_story_rate": sum(bool(row["exact"]) for row in projection_rows) / len(projection_rows),
            "tp": projection_tp,
            "fp": projection_fp,
            "fn": projection_fn,
            "precision": projection_precision,
            "recall": projection_recall,
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
        max_output_tokens=128,
        recent_message_limit=RECENT_MESSAGE_LIMIT,
        rag_limit=5,
        embedding_model=None,
        rerank_base_url=None,
        rerank_api_key=None,
        rerank_model=None,
        context_window_tokens=8192,
        settings_file=None,
        langgraph_checkpoint_path=None,
    )
    db_path = args.output.parent / "long-dialogue-eval.db"
    database = make_database(db_path)
    fact_memory_ids = seed_histories(database)
    context_builder, state_service = build_services(settings)
    model = OpenAICompatibleClient(settings)
    try:
        await model.check_connection()
        state_rows, projection_rows = await run_state_chain(database, model, state_service)
        question_rows = await run_questions(
            database,
            model,
            context_builder,
            fact_memory_ids,
        )
        result = {
            "metadata": {
                "generated_at": datetime.now(UTC).isoformat(),
                "suite": "Saraswati Long Dialogue Consistency Eval v1",
                "model": settings.llm_model,
                "temperature": settings.temperature,
                "dataset_type": "deterministic synthetic long-dialogue histories",
                "notice": (
                    "Two 50-turn synthetic histories; directional engineering result, "
                    "not an external product benchmark."
                ),
            },
            "metrics": summarize(question_rows, state_rows, projection_rows),
            "question_rows": question_rows,
            "state_rows": state_rows,
            "projection_rows": projection_rows,
        }
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
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
