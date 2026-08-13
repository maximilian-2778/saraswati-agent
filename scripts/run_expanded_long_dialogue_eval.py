"""Expand the long-dialogue evaluation to ten independent 50-turn stories.

The existing two-story result can be reused, while eight new stories are run
through the production ContextBuilder, MemoryService, NarrativeDeltaService,
and StateService. The expanded public output intentionally contains no
recent-window baseline. Credentials are never serialized.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import run_long_dialogue_eval as base  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.database import Base, Database  # noqa: E402
from backend.llm import local_embedding  # noqa: E402
from backend.models import ChatRecord, MemoryRecord, MessageRecord  # noqa: E402
from backend.providers.openai_compatible import OpenAICompatibleClient  # noqa: E402
from backend.schemas import MemoryKind  # noqa: E402
from backend.services.context import ContextBuilder  # noqa: E402
from backend.services.narrative_delta import NarrativeDeltaService  # noqa: E402
from backend.services.state import StateService  # noqa: E402
from backend.utils import json_dumps  # noqa: E402


TURNS_PER_STORY = 50
CONCURRENCY = 3


@dataclass(frozen=True, slots=True)
class Blueprint:
    story_id: str
    title: str
    actor: str
    early_question: str
    early_fact: str
    early_query: str
    early_answer: str
    persona_fact: str
    persona_query: str
    persona_answer: str
    persona_forbidden: str
    identity_fact: str
    identity_query: str
    identity_answer: str
    identity_forbidden: str
    old_faction: str
    faction: str
    item: str
    custodian: str
    old_location: str
    location: str
    promise_question: str
    promise_fact: str
    promise_query: str
    promise_answer: str
    absent_item: str
    resource_entity: str
    resource_key: str
    resource_unit: str
    resource_old: int
    resource_current: int
    attribute_key: str
    attribute_value: int
    quest: str


BLUEPRINTS = (
    Blueprint(
        "frost-bridge", "霜桥烽火", "寒露",
        "旧烽台约定的求援灯号是什么？", "守军约定的求援灯号是三短一长，任何其他节奏都不算正式求援。",
        "旧烽台的求援灯号是什么？只回答灯号。", "三短一长",
        "寒露从不拆阅他人的封缄信件，即使可能错过情报也会拒绝拆封。",
        "有人把不属于寒露的封缄信交给她，她会怎么做？只回答“拒绝拆封”或“立即拆封”。", "拒绝拆封", "立即拆封",
        "寒露的真实身份是霜桥巡守官，她此前伪装成赏金猎人。",
        "寒露的真实身份是什么？只回答身份名称。", "霜桥巡守官", "赏金猎人",
        "北岭佣兵团", "霜桥守军", "寒星号角", "烽台司号员", "北侧栈道", "霜桥烽台",
        "寒露和烽台司号员约定了什么撤离信号？", "双方约定：日落后升起两面白旗，就是伤员已经撤离的信号。",
        "伤员已经撤离的约定信号是什么？只回答信号。", "日落后升起两面白旗", "黑曜石匕首",
        "守军", "口粮", "份", 36, 24, "耐力值", 71, "霜桥救援",
    ),
    Blueprint(
        "white-oasis", "白石绿洲", "苏筝",
        "沙海中唯一稳定的淡水源在哪里？", "向导确认，沙海唯一稳定的淡水源是白石井，其他水洼都会季节性干涸。",
        "沙海唯一稳定的淡水源是什么？只回答名称。", "白石井",
        "苏筝绝不偷取平民的财物，即使补给短缺也会拒绝偷窃。",
        "补给不足时有人建议苏筝偷走平民的水袋，她会怎么做？只回答“拒绝偷窃”或“接受偷窃”。", "拒绝偷窃", "接受偷窃",
        "苏筝的真实身份是沙海医师，并非受雇佣兵。",
        "苏筝的真实身份是什么？只回答身份名称。", "沙海医师", "受雇佣兵",
        "赤沙商队", "绿洲救护会", "琉璃罗盘", "白石井守", "盐碱滩", "白石井营地",
        "苏筝和井守约定了什么安全信号？", "双方约定：正午在井栏系一条蓝布，表示饮水已经检验安全。",
        "饮水检验安全的约定信号是什么？只回答信号。", "正午在井栏系一条蓝布", "黄金圣杯",
        "救护会", "净水", "袋", 28, 19, "生命值", 82, "绿洲净化",
    ),
    Blueprint(
        "cloud-engine", "浮城云机", "云眠",
        "浮城主引擎缺失的启动部件是什么？", "旧图纸标明，浮城主引擎必须装入云铜齿轮才能启动。",
        "浮城主引擎需要什么部件才能启动？只回答部件名称。", "云铜齿轮",
        "云眠患有严重恐高，不会主动走上没有护栏的高台。",
        "有人建议云眠从无护栏高台抄近路，她会怎么做？只回答“拒绝登高”或“走上高台”。", "拒绝登高", "走上高台",
        "云眠的真实身份是浮城机械师，并非天空骑士。",
        "云眠的真实身份是什么？只回答身份名称。", "浮城机械师", "天空骑士",
        "苍羽骑团", "云机工坊", "云铜齿轮", "主机库管理员", "东侧吊桥", "主引擎舱",
        "云眠与管理员约定的停机完成信号是什么？", "双方约定：主轴停稳后亮起三盏绿灯，表示检修人员可以进入。",
        "检修人员可以进入的约定信号是什么？只回答信号。", "主轴停稳后亮起三盏绿灯", "雷晶长枪",
        "工坊", "能量晶体", "枚", 25, 14, "专注值", 76, "主轴修复",
    ),
    Blueprint(
        "deep-current", "深潮遗城", "临雾",
        "开启遗城海门的古代口令是什么？", "石碑译文确认，开启遗城海门的口令是“潮落见星”。",
        "遗城海门的古代口令是什么？只回答口令。", "潮落见星",
        "临雾把真实航海记录视为底线，绝不会伪造潜航数据。",
        "船长要求临雾伪造潜航数据，她会怎么做？只回答“拒绝伪造”或“接受伪造”。", "拒绝伪造", "接受伪造",
        "临雾的真实身份是深海测绘师，并非海盗。",
        "临雾的真实身份是什么？只回答身份名称。", "深海测绘师", "海盗",
        "黑帆舰队", "深潮考察团", "潮汐刻盘", "遗城译码员", "沉船甲板", "遗城海门前厅",
        "临雾与译码员约定的返航信号是什么？", "双方约定：连续释放两枚紫色浮标，表示测绘队已经返航。",
        "测绘队已经返航的约定信号是什么？只回答信号。", "连续释放两枚紫色浮标", "海皇三叉戟",
        "考察团", "氧气瓶", "瓶", 22, 13, "压力服完整度", 88, "海门测绘",
    ),
    Blueprint(
        "silver-forest", "银叶密林", "青黛",
        "腐心菇中毒需要什么解药？", "药典记载，腐心菇中毒只能用银叶苔解毒，普通解毒草无效。",
        "腐心菇中毒需要什么解药？只回答名称。", "银叶苔",
        "青黛从不使用活体做药剂实验，会拒绝任何伤害无辜者的试验。",
        "有人要求青黛用活体村民试药，她会怎么做？只回答“拒绝试药”或“接受试药”。", "拒绝试药", "接受试药",
        "青黛的真实身份是森林药剂师，并非神殿祭司。",
        "青黛的真实身份是什么？只回答身份名称。", "森林药剂师", "神殿祭司",
        "枯木教团", "银叶守林会", "月纹药杵", "守林会药库", "黑松谷", "银叶药圃",
        "青黛与药库约定的解药完成信号是什么？", "双方约定：在药圃门口挂起四束白花，表示解药已经配成。",
        "解药已经配成的约定信号是什么？只回答信号。", "在药圃门口挂起四束白花", "翡翠王冠",
        "药库", "银叶苔", "束", 32, 21, "声望值", 17, "腐心解药",
    ),
    Blueprint(
        "midnight-clock", "午夜钟城", "重光",
        "让失控钟塔停止的控制短语是什么？", "首席钟匠留下的控制短语是“午夜停摆”，说出后主钟才会锁止。",
        "钟塔的控制短语是什么？只回答短语。", "午夜停摆",
        "重光拒绝使用禁术驱动机械，任何情况下都不会主动施展禁术。",
        "有人建议重光用禁术启动机械，他会怎么做？只回答“拒绝施法”或“使用禁术”。", "拒绝施法", "使用禁术",
        "重光的真实身份是钟城工程师，并非宫廷魔法师。",
        "重光的真实身份是什么？只回答身份名称。", "钟城工程师", "宫廷魔法师",
        "王室工造局", "自由钟匠会", "黄铜擒纵器", "钟匠会会长", "旧报时厅", "主钟控制室",
        "重光与会长约定的复机信号是什么？", "双方约定：主钟连续报时五响，表示齿轮组已经恢复同步。",
        "齿轮组恢复同步的约定信号是什么？只回答信号。", "主钟连续报时五响", "时间水晶",
        "钟匠会", "备用齿轮", "枚", 40, 27, "机械稳定度", 91, "主钟复位",
    ),
    Blueprint(
        "star-academy", "星穹学院", "夕叶",
        "禁书库的隐蔽入口在哪里？", "旧院志写明，禁书库的隐蔽入口位于西侧旋梯之后。",
        "禁书库的隐蔽入口在哪里？只回答地点。", "西侧旋梯之后",
        "夕叶承诺保护已经投降的人，不会继续攻击放下武器的对手。",
        "对手已经放下武器并投降，夕叶会怎么做？只回答“停止攻击”或“继续攻击”。", "停止攻击", "继续攻击",
        "夕叶的真实身份是学院档案官，并非普通学生。",
        "夕叶的真实身份是什么？只回答身份名称。", "学院档案官", "普通学生",
        "旧校董会", "星穹研究会", "银星目录", "禁书库管理员", "东庭讲堂", "禁书库内厅",
        "夕叶与管理员约定的封库信号是什么？", "双方约定：午夜熄灭七盏廊灯，表示禁书已经重新封存。",
        "禁书重新封存的约定信号是什么？只回答信号。", "午夜熄灭七盏廊灯", "贤者法杖",
        "研究会", "封印符", "张", 30, 18, "知识完整度", 84, "禁书封存",
    ),
    Blueprint(
        "north-fortress", "北境冰堡", "白芦",
        "穿越冰洞时可信的安全标记是什么？", "巡逻手册规定，冰洞中只有红色绳结是可信的安全标记。",
        "冰洞中可信的安全标记是什么？只回答标记。", "红色绳结",
        "白芦极度惧怕明火，不会主动触碰燃烧中的物品。",
        "火盆里有一封信，白芦会徒手拿取吗？只回答“不会触碰”或“会徒手拿取”。", "不会触碰", "会徒手拿取",
        "白芦的真实身份是冰堡军需官，并非前线指挥官。",
        "白芦的真实身份是什么？只回答身份名称。", "冰堡军需官", "前线指挥官",
        "南境远征军", "北境守备队", "霜纹军令", "冰堡副官", "外墙哨塔", "地下军需库",
        "白芦与副官约定的补给安全信号是什么？", "双方约定：清晨在库门放置三块黑石，表示补给已经清点安全。",
        "补给清点安全的约定信号是什么？只回答信号。", "清晨在库门放置三块黑石", "炎龙盾牌",
        "守备队", "弩箭", "支", 48, 33, "士气值", 74, "冬季补给",
    ),
)


def make_story(spec: Blueprint) -> base.StorySpec:
    events: dict[int, dict[str, Any]] = {
        2: {"user": spec.early_question, "assistant": spec.early_fact, "importance": 0.98, "fact": "early"},
        4: {"user": f"请记住{spec.actor}最重要的行为原则。", "assistant": spec.persona_fact, "importance": 0.96, "fact": "persona"},
        6: {"user": f"{spec.actor}公开自己的真实身份。", "assistant": spec.identity_fact, "importance": 0.96, "fact": "identity"},
        10: {
            "user": f"第一次清点{spec.resource_entity}的{spec.resource_key}。",
            "assistant": f"清点完成，{spec.resource_entity}{spec.resource_key}明确变为{spec.resource_old}{spec.resource_unit}。",
            "importance": 0.92,
            "fact": "resource_old",
        },
        12: {
            "user": f"{spec.actor}离开{spec.old_faction}后加入了哪里？",
            "assistant": f"{spec.actor}已经离开{spec.old_faction}，当前所属阵营是{spec.faction}。",
            "importance": 0.97,
            "fact": "faction",
        },
        14: {
            "user": f"{spec.custodian}暂时把{spec.item}交给{spec.actor}使用。",
            "assistant": f"{spec.actor}接过{spec.item}并暂时随身保管。",
            "importance": 0.78,
            "fact": "item_old",
        },
        18: {
            "user": f"我们先到{spec.old_location}处理例行事务。",
            "assistant": f"{spec.actor}到达{spec.old_location}并完成现场检查。",
            "importance": 0.72,
            "fact": "location_old",
        },
        20: {
            "user": f"行动结束后检查{spec.actor}的{spec.attribute_key}。",
            "assistant": f"检查完成，{spec.actor}当前{spec.attribute_key}明确为{spec.attribute_value}点。",
            "importance": 0.92,
            "fact": "attribute",
        },
        22: {"user": spec.promise_question, "assistant": spec.promise_fact, "importance": 0.97, "fact": "promise"},
        24: {
            "user": f"任务结束，把{spec.item}归还原保管方。",
            "assistant": f"{spec.actor}已经归还{spec.item}。现在{spec.item}由{spec.custodian}保管，{spec.actor}不再持有。",
            "importance": 0.99,
            "fact": "item_current",
        },
        28: {
            "user": f"检查{spec.actor}是否拥有{spec.absent_item}。",
            "assistant": f"清单确认，{spec.actor}从未获得{spec.absent_item}，当前也没有这件物品。",
            "importance": 0.95,
            "fact": "absent_item",
        },
        30: {
            "user": f"离开{spec.old_location}后，我们转移到哪里？",
            "assistant": f"队伍已经离开{spec.old_location}，{spec.actor}当前位于{spec.location}。",
            "importance": 0.99,
            "fact": "location_current",
        },
        35: {
            "user": f"任务“{spec.quest}”进展如何？",
            "assistant": f"目标已经全部达成，任务“{spec.quest}”的状态变为已完成。",
            "importance": 0.94,
            "fact": "quest",
        },
        40: {
            "user": f"发生消耗后，再次核对{spec.resource_entity}的{spec.resource_key}。",
            "assistant": (
                f"重新核对后，{spec.resource_entity}{spec.resource_key}从{spec.resource_old}{spec.resource_unit}"
                f"变为{spec.resource_current}{spec.resource_unit}，当前数量是{spec.resource_current}{spec.resource_unit}。"
            ),
            "importance": 0.99,
            "fact": "resource_current",
        },
    }
    questions = (
        question(spec, "early", "early_plot", spec.early_query, spec.early_answer),
        question(spec, "persona", "persona_adherence", spec.persona_query, spec.persona_answer, spec.persona_forbidden),
        question(spec, "identity", "identity_consistency", spec.identity_query, spec.identity_answer, spec.identity_forbidden),
        question(
            spec, "faction", "faction_consistency",
            f"{spec.actor}当前属于哪个阵营？只回答阵营名称。", spec.faction, spec.old_faction,
        ),
        question(
            spec, "item_current", "item_consistency",
            f"{spec.item}现在由谁保管？只回答名称。", spec.custodian, spec.actor,
        ),
        question(
            spec, "location_current", "location_consistency",
            f"{spec.actor}当前在哪里？只回答地点名称。", spec.location, spec.old_location,
        ),
        question(spec, "promise", "promise_consistency", spec.promise_query, spec.promise_answer),
        question(
            spec, "absent_item", "unsupported_item",
            f"{spec.actor}现在拥有{spec.absent_item}吗？只回答“有”或“没有”。", "没有", "有",
        ),
        question(
            spec, "resource_current", "state_value",
            f"{spec.resource_entity}当前有多少{spec.resource_unit}{spec.resource_key}？只回答数字。",
            str(spec.resource_current), str(spec.resource_old),
        ),
    )
    state_events = (
        {"turn": 10, "expected": [{"entity": spec.resource_entity, "key": spec.resource_key, "new_value": spec.resource_old}]},
        {"turn": 20, "expected": [{"entity": spec.actor, "key": spec.attribute_key, "new_value": spec.attribute_value}]},
        {"turn": 35, "expected": [{"entity": f"任务:{spec.quest}", "key": "状态", "new_value": "已完成"}]},
        {"turn": 40, "expected": [{"entity": spec.resource_entity, "key": spec.resource_key, "new_value": spec.resource_current}]},
    )
    final_state = (
        {"entity": spec.resource_entity, "key": spec.resource_key, "new_value": spec.resource_current},
        {"entity": spec.actor, "key": spec.attribute_key, "new_value": spec.attribute_value},
        {"entity": f"任务:{spec.quest}", "key": "状态", "new_value": "已完成"},
    )
    return base.StorySpec(spec.story_id, spec.title, events, questions, state_events, final_state)


def question(
    spec: Blueprint,
    fact: str,
    category: str,
    query: str,
    expected: str,
    forbidden: str | None = None,
) -> dict[str, Any]:
    return {
        "case_id": f"{spec.story_id}-{fact}",
        "category": category,
        "query": query,
        "expected": [expected],
        "forbidden": [forbidden] if forbidden else [],
        "relevant_fact": fact,
    }


EXTRA_STORIES = tuple(make_story(item) for item in BLUEPRINTS)
ALL_STORIES = (*base.STORIES, *EXTRA_STORIES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmark-results" / "long-dialogue-expanded.json",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Rerun all ten stories instead of reusing the audited first two.",
    )
    return parser.parse_args()


def make_database(path: Path) -> Database:
    if path.exists():
        path.unlink()
    database = Database(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(bind=database.engine)
    return database


def filler_turn(story: base.StorySpec, turn: int) -> tuple[str, str]:
    topics = ("天气", "值班表", "普通商队", "食物", "地图", "鸟鸣", "照明", "次日行程")
    topic = topics[(turn - 1) % len(topics)]
    return (
        f"第{turn}轮，我们处理{topic}方面的例行事务，不推进关键线索。",
        f"第{turn}轮的{topic}事务已经处理完毕，没有获得新物品，也没有改变身份、阵营、约定、位置或精确状态。",
    )


def seed_histories(
    database: Database, stories: tuple[base.StorySpec, ...]
) -> dict[str, dict[str, str]]:
    start = datetime.now(UTC) - timedelta(days=50)
    fact_ids: dict[str, dict[str, str]] = {}
    with database.session_factory() as db:
        for story_index, story in enumerate(stories):
            story_start = start + timedelta(hours=story_index)
            db.add(
                ChatRecord(
                    id=story.story_id,
                    title=story.title,
                    system_prompt=(
                        "只依据本故事中已经确认的事实回答最终核对问题。不得猜测，"
                        "不得补充未出现的物品、地点、身份或数值。严格遵守问题指定的输出格式。"
                    ),
                    created_at=story_start,
                    updated_at=story_start + timedelta(hours=TURNS_PER_STORY),
                )
            )
            db.flush()
            fact_ids[story.story_id] = {}
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
                    fact_ids[story.story_id][str(event["fact"])] = memory_id
            db.commit()
    return fact_ids


async def gather_limited(coros: list[Any], limit: int = CONCURRENCY) -> list[Any]:
    semaphore = asyncio.Semaphore(limit)

    async def guarded(coro: Any) -> Any:
        async with semaphore:
            return await coro

    return await asyncio.gather(*(guarded(coro) for coro in coros))


async def run_state_chain(
    database: Database,
    model: OpenAICompatibleClient,
    state_service: StateService,
    stories: tuple[base.StorySpec, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    delta = NarrativeDeltaService()
    jobs: list[tuple[base.StorySpec, dict[str, Any], Any]] = []
    for story in stories:
        for state_event in story.state_events:
            turn = int(state_event["turn"])
            event = story.events[turn]
            jobs.append(
                (
                    story,
                    state_event,
                    delta._extract(model, str(event["user"]), str(event["assistant"])),
                )
            )
    payloads = await gather_limited([item[2] for item in jobs])
    rows: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []
    with database.session_factory() as db:
        for (story, state_event, _), payload in zip(jobs, payloads, strict=True):
            turn = int(state_event["turn"])
            actual = base.extracted_changes(payload)
            expected = list(state_event["expected"])
            tp, fp, fn = base.fact_counts(expected, actual)
            for index, change in enumerate(actual):
                entity = str(change.get("entity", "")).strip()
                key = str(change.get("key", "")).strip()
                if entity and key:
                    state_service.apply(
                        db,
                        story.story_id,
                        entity,
                        key,
                        change.get("new_value"),
                        reason=f"expanded-long-eval turn {turn}",
                        source_message_id=f"{story.story_id}-a-{turn:02d}",
                        event_fingerprint=f"{story.story_id}-{turn}-{index}",
                    )
            rows.append(
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
            print(f"state {story.story_id} turn {turn}: {'pass' if fp == 0 and fn == 0 else 'fail'}", flush=True)
        for story in stories:
            actual_projection = [
                {"entity": item.entity, "key": item.key, "new_value": state_service.value(item)}
                for item in state_service.list_entries(db, story.story_id)
            ]
            expected_projection = list(story.final_state)
            tp, fp, fn = base.fact_counts(expected_projection, actual_projection)
            projections.append(
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
    return rows, projections


async def run_questions(
    database: Database,
    model: OpenAICompatibleClient,
    context_builder: ContextBuilder,
    stories: tuple[base.StorySpec, ...],
    fact_ids: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    with database.session_factory() as db:
        for story in stories:
            chat = db.get(ChatRecord, story.story_id)
            if chat is None:
                raise RuntimeError(f"Missing chat {story.story_id}")
            for case in story.questions:
                query = str(case["query"])
                bundle = await context_builder.build(db, model, chat, query)
                relevant_id = fact_ids[story.story_id][str(case["relevant_fact"])]
                ranked = [item.record.id for item in bundle.retrieved_memories]
                rank = next((i for i, item_id in enumerate(ranked, 1) if item_id == relevant_id), None)
                fact_turn = int(relevant_id.rsplit("-", 1)[1])
                prepared.append(
                    {
                        "story_id": story.story_id,
                        "case_id": case["case_id"],
                        "category": case["category"],
                        "fact_turn": fact_turn,
                        "distance_to_query_turns": TURNS_PER_STORY - fact_turn,
                        "query": query,
                        "expected": list(case["expected"]),
                        "forbidden": list(case["forbidden"]),
                        "relevant_memory_id": relevant_id,
                        "retrieved_ids": ranked,
                        "relevant_rank": rank,
                        "recall_at_1": int(rank == 1),
                        "recall_at_3": int(rank is not None and rank <= 3),
                        "recall_at_5": int(rank is not None and rank <= 5),
                        "prompt": [*bundle.messages, {"role": "user", "content": query}],
                    }
                )

    replies = await gather_limited([model.complete(item["prompt"]) for item in prepared])
    rows: list[dict[str, Any]] = []
    for item, reply in zip(prepared, replies, strict=True):
        answer = (reply.content or "").strip()
        item.pop("prompt")
        item["answer"] = answer
        item["passed"] = base.answer_passes(answer, item["expected"], item["forbidden"])
        item["forbidden_selected"] = base.selected_forbidden(answer, item["forbidden"])
        rows.append(item)
        print(
            f"qa {item['case_id']}: {'pass' if item['passed'] else 'fail'}, rank={item['relevant_rank']}",
            flush=True,
        )
    return rows


def prior_rows(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = []
    for old in data["question_rows"]:
        questions.append(
            {
                "story_id": old["story_id"],
                "case_id": old["case_id"],
                "category": old["category"],
                "fact_turn": old["fact_turn"],
                "distance_to_query_turns": old["distance_to_query_turns"],
                "query": old["query"],
                "expected": old["expected"],
                "forbidden": old["forbidden"],
                "relevant_memory_id": old["relevant_memory_id"],
                "retrieved_ids": old["retrieved_ids"],
                "relevant_rank": old["relevant_rank"],
                "recall_at_1": old["recall_at_1"],
                "recall_at_3": old["recall_at_3"],
                "recall_at_5": old["recall_at_5"],
                "answer": old["project_answer"],
                "passed": old["project_passed"],
                "forbidden_selected": old["project_forbidden_selected"],
            }
        )
    return questions, list(data["state_rows"]), list(data["projection_rows"])


def wilson(passed: int, total: int) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    p = passed / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def score_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(bool(item["passed"]) for item in rows)
    return {
        "passed": passed,
        "total": len(rows),
        "rate": passed / len(rows) if rows else 0.0,
        "wilson_95_ci": wilson(passed, len(rows)),
    }


def summarize(
    questions: list[dict[str, Any]],
    states: list[dict[str, Any]],
    projections: list[dict[str, Any]],
) -> dict[str, Any]:
    by_category = {
        category: score_block([row for row in questions if row["category"] == category])
        for category in sorted({str(row["category"]) for row in questions})
    }
    tp = sum(int(row["tp"]) for row in states)
    fp = sum(int(row["fp"]) for row in states)
    fn = sum(int(row["fn"]) for row in states)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    project_tp = sum(int(row["tp"]) for row in projections)
    project_fp = sum(int(row["fp"]) for row in projections)
    project_fn = sum(int(row["fn"]) for row in projections)
    return {
        "long_dialogue": {
            "stories": len({row["story_id"] for row in questions}),
            "turns_per_story": TURNS_PER_STORY,
            "total_turns": len({row["story_id"] for row in questions}) * TURNS_PER_STORY,
            "total_messages": len({row["story_id"] for row in questions}) * TURNS_PER_STORY * 2,
            "questions": len(questions),
            "fact_turn_min": min(int(row["fact_turn"]) for row in questions),
            "fact_turn_max": max(int(row["fact_turn"]) for row in questions),
            "distance_to_query_turns_min": min(int(row["distance_to_query_turns"]) for row in questions),
            "distance_to_query_turns_max": max(int(row["distance_to_query_turns"]) for row in questions),
        },
        "answer_accuracy": {"overall": score_block(questions), "by_category": by_category},
        "retrieval": {
            "recall_at_1": sum(int(row["recall_at_1"]) for row in questions) / len(questions),
            "recall_at_3": sum(int(row["recall_at_3"]) for row in questions) / len(questions),
            "recall_at_5": sum(int(row["recall_at_5"]) for row in questions) / len(questions),
        },
        "explicit_contradiction": {
            "violations": sum(bool(row["forbidden_selected"]) for row in questions),
            "total": sum(bool(row["forbidden"]) for row in questions),
        },
        "world_ledger_event_extraction": {
            "events": len(states),
            "exact_events": sum(bool(row["exact_case"]) for row in states),
            "exact_event_rate": sum(bool(row["exact_case"]) for row in states) / len(states),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "world_ledger_final_projection": {
            "stories": len(projections),
            "exact_stories": sum(bool(row["exact"]) for row in projections),
            "exact_story_rate": sum(bool(row["exact"]) for row in projections) / len(projections),
            "tp": project_tp,
            "fp": project_fp,
            "fn": project_fn,
            "precision": project_tp / (project_tp + project_fp) if project_tp + project_fp else 1.0,
            "recall": project_tp / (project_tp + project_fn) if project_tp + project_fn else 1.0,
        },
    }


async def async_main() -> int:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    prior_path = ROOT / "benchmark-results" / "long-dialogue-eval.json"
    reuse_prior = prior_path.exists() and not args.fresh
    stories = EXTRA_STORIES if reuse_prior else ALL_STORIES

    settings = Settings.from_env()
    if settings.provider_mode == "unconfigured":
        raise RuntimeError("No configured model in data/settings.json or environment")
    settings = replace(
        settings,
        temperature=0.0,
        max_output_tokens=128,
        recent_message_limit=16,
        rag_limit=5,
        embedding_model=None,
        rerank_base_url=None,
        rerank_api_key=None,
        rerank_model=None,
        context_window_tokens=8192,
        settings_file=None,
        langgraph_checkpoint_path=None,
    )
    db_path = args.output.parent / "long-dialogue-expanded.db"
    database = make_database(db_path)
    fact_ids = seed_histories(database, stories)
    context_builder, state_service = base.build_services(settings)
    model = OpenAICompatibleClient(settings)
    try:
        await model.check_connection()
        state_rows, projection_rows = await run_state_chain(database, model, state_service, stories)
        question_rows = await run_questions(database, model, context_builder, stories, fact_ids)
        if reuse_prior:
            old_questions, old_states, old_projections = prior_rows(prior_path)
            question_rows = [*old_questions, *question_rows]
            state_rows = [*old_states, *state_rows]
            projection_rows = [*old_projections, *projection_rows]
        result = {
            "metadata": {
                "generated_at": datetime.now(UTC).isoformat(),
                "suite": "Saraswati Expanded Long Dialogue Consistency Eval v2",
                "model": settings.llm_model,
                "temperature": settings.temperature,
                "dataset_type": "ten deterministic synthetic 50-turn histories",
                "reused_audited_v1_stories": 2 if reuse_prior else 0,
                "newly_executed_stories": len(stories),
                "notice": "Synthetic in-project evaluation; paper results use different datasets and are reference-only.",
            },
            "metrics": summarize(question_rows, state_rows, projection_rows),
            "question_rows": question_rows,
            "state_rows": state_rows,
            "projection_rows": projection_rows,
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
