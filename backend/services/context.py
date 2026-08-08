"""为单轮生成组装受控上下文。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.llm import ModelClient
from backend.models import (
    ChatRecord,
    MemoryRecord,
    MessageRecord,
    StateEntryRecord,
    StoryCharacterRecord,
    StoryWorldBookRecord,
)
from backend.schemas import MemoryKind
from backend.services.memory import MemoryService, RetrievedMemory
from backend.services.narrative_memory import NarrativeMemoryService
from backend.services.roleplay_graph import RoleplayGraphService
from backend.services.state import StateService
from backend.services.token_budget import TokenBudgetManager
from backend.utils import clean_story_text, json_loads


@dataclass(slots=True)
class ContextBundle:
    messages: list[dict[str, Any]]
    retrieved_memories: list[RetrievedMemory]
    state_count: int
    character_configured: bool
    world_entry_ids: list[str]
    diagnostics: dict[str, Any]


class ContextBuilder:
    """组合系统提示词、状态、记忆和近期原文。"""

    def __init__(
        self,
        settings: Settings,
        memory_service: MemoryService,
        state_service: StateService,
        narrative_memory_service: NarrativeMemoryService,
        graph_service: RoleplayGraphService,
    ) -> None:
        self.settings = settings
        self.memory_service = memory_service
        self.state_service = state_service
        self.narrative_memory_service = narrative_memory_service
        self.graph_service = graph_service
        self.budget_manager = TokenBudgetManager()

    async def build(
        self,
        db: Session,
        model: ModelClient,
        chat: ChatRecord,
        query: str,
        through: datetime | None = None,
    ) -> ContextBundle:
        state_entries = self.state_service.list_entries(db, chat.id)
        characters = db.scalars(
            select(StoryCharacterRecord)
            .where(StoryCharacterRecord.chat_id == chat.id)
            .order_by(StoryCharacterRecord.created_at)
        ).all()
        world_records = db.scalars(
            select(StoryWorldBookRecord)
            .where(
                StoryWorldBookRecord.chat_id == chat.id,
                StoryWorldBookRecord.enabled.is_(True),
            )
            .order_by(StoryWorldBookRecord.priority.desc())
        ).all()
        message_filters = [MessageRecord.chat_id == chat.id]
        if through is not None:
            message_filters.append(MessageRecord.created_at <= through)
        recent_desc = db.scalars(
            select(MessageRecord)
            .where(*message_filters)
            .order_by(MessageRecord.created_at.desc())
            .limit(self.settings.recent_message_limit)
        ).all()
        recent = list(reversed(recent_desc))
        retrieved = await self.memory_service.search(
            db,
            model,
            chat.id,
            query,
            self.settings.rag_limit,
            exclude_source_message_ids={record.id for record in recent},
            exclude_memory_ids=self.narrative_memory_service.invalid_memory_ids(
                db, chat.id
            ),
        )
        history_nodes = self.narrative_memory_service.selected_history(
            db,
            chat.id,
            {record.id for record in recent},
        )
        pinned_memories = list(
            db.scalars(
                select(MemoryRecord)
                .where(
                    MemoryRecord.chat_id == chat.id,
                    MemoryRecord.kind.in_([MemoryKind.SEMANTIC.value, MemoryKind.IMPLICIT.value]),
                    MemoryRecord.importance >= 0.9,
                )
                .order_by(MemoryRecord.importance.desc(), MemoryRecord.created_at.desc())
                .limit(5)
            ).all()
        )

        state_lines = [
            f"- {entry.entity}.{entry.key} = {json_loads(entry.value_json)!r}"
            for entry in _select_state_entries(state_entries, query)
        ]
        message_by_id = {record.id: record for record in recent}
        if retrieved:
            recalled_source_ids = {
                item.record.source_message_id
                for item in retrieved
                if item.record.source_message_id
            }
            recalled_messages = db.scalars(
                select(MessageRecord).where(MessageRecord.id.in_(recalled_source_ids))
            ).all()
            message_by_id.update({record.id: record for record in recalled_messages})
        memory_lines = []
        retrieved_ids = {item.record.id for item in retrieved}
        for record in pinned_memories:
            if record.id not in retrieved_ids and record.source_message_id not in {item.id for item in recent}:
                memory_lines.append(f"- [深层置顶] {record.content}")
        for item in retrieved:
            source = message_by_id.get(item.record.source_message_id or "")
            use_full_text = item.score >= 0.72 and source is not None
            body = clean_story_text(source.content) if use_full_text else item.record.content
            tier = "高相关原文" if use_full_text else "相关摘要"
            memory_lines.append(
                f"- [{tier}｜{item.score:.3f}] {body}（{item.reason}）"
            )

        character_lines: list[str] = []
        for character in characters:
            details = "；".join(
                item
                for item in [
                    f"身份与背景：{character.identity}" if character.identity else "",
                    f"性格：{character.personality}" if character.personality else "",
                    f"说话风格：{character.speaking_style}" if character.speaking_style else "",
                    f"当前情境：{character.scenario}" if character.scenario else "",
                ]
                if item
            )
            character_lines.append(f"- {character.name}" + (f"｜{details}" if details else ""))

        normalized_query = query.casefold()
        active_world_entries: list[StoryWorldBookRecord] = []
        for record in world_records:
            keywords = json_loads(record.keywords_json) or []
            if not keywords or any(
                str(keyword).casefold() in normalized_query for keyword in keywords
            ):
                active_world_entries.append(record)
        world_lines = [
            f"- [{record.title}｜优先级 {record.priority}] {record.content}"
            for record in active_world_entries[:12]
        ]
        roleplay_graph = self.graph_service.context_text(db, chat.id, query)

        system_prompt = "你正在进行长篇角色扮演。保持人物语气、剧情连贯和沉浸感。"
        if chat.system_prompt.strip():
            system_prompt += f"\n\n旧版补充设定：\n{chat.system_prompt.strip()}"
        system_prompt += (
            "\n\n当前角色档案：\n"
            + ("\n".join(character_lines) if character_lines else "- 暂未设置")
            + "\n\n本轮触发的世界书：\n"
            + ("\n".join(world_lines) if world_lines else "- 本轮没有触发词条")
            + "\n\n当前场景与人物关系：\n"
            + (roleplay_graph or "- 暂无结构化场景或 NPC 记录")
        )
        system_prompt += (
            "\n\n你可以调用工具查询记忆和精确状态。"
            "结构化状态是数值和物品的事实来源；不要擅自假设或覆盖。"
            "剧情发生明确状态变化时，调用 propose_state_change 提出建议，"
            "由用户审核后才会生效。"
            "需要持续追踪的物品、NPC、场景、计划或悬念也使用状态建议维护；"
            "实体名称分别以‘物品:’、‘NPC:’、‘场景:’、‘悬念:’开头，"
            "已完成的计划或悬念将 status 建议为 resolved。"
            "只有值得长期保留的信息才调用 write_memory。"
            "发现地点层级或当前位置变化时调用 upsert_scene；NPC 登离场、位置、状态或关系变化时调用 upsert_npc。"
            "\n\n当前已批准状态：\n"
            + ("\n".join(state_lines) if state_lines else "- 暂无")
            + "\n\n本轮召回记忆：\n"
            + ("\n".join(memory_lines) if memory_lines else "- 暂无")
            + "\n\n窗口外历史剧情（系统已选择最高可信摘要，禁止逐条复述）：\n"
            + (
                "\n\n".join(_format_history_node(item) for item in history_nodes)
                if history_nodes
                else "- 暂无需要注入的窗口外剧情"
            )
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        messages.extend(
            {"role": record.role, "content": record.content}
            for record in recent
            if record.role in {"user", "assistant", "system"}
        )
        section_texts = {
            "角色档案": "\n".join(character_lines),
            "世界书": "\n".join(world_lines),
            "场景与NPC": roleplay_graph,
            "精确状态": "\n".join(state_lines),
            "RAG召回": "\n".join(memory_lines),
            "窗口外摘要": "\n".join(_format_history_node(item) for item in history_nodes),
            "近期原文": "\n".join(record.content for record in recent),
        }
        input_budget = max(1024, self.settings.context_window_tokens - self.settings.max_output_tokens)
        messages, diagnostics = self.budget_manager.fit(messages, input_budget, section_texts)
        return ContextBundle(
            messages,
            retrieved,
            len(state_entries),
            bool(character_lines),
            [record.id for record in active_world_entries[:12]],
            diagnostics,
        )


def _select_state_entries(
    entries: list[StateEntryRecord], query: str, limit: int = 24
) -> list[StateEntryRecord]:
    """按当前话题选择台账，避免“记住的细节”在每轮都被模型看见。"""
    normalized = query.casefold()

    def score(entry: StateEntryRecord) -> tuple[int, datetime]:
        identity = f"{entry.entity} {entry.key}".casefold()
        value = json_loads(entry.value_json)
        points = 0
        if entry.entity.casefold() in normalized or entry.key.casefold() in normalized:
            points += 10
        if any(prefix in identity for prefix in ("物品:", "场景:", "悬念:")):
            points += 4
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            points += 3
        if "status" in entry.key.casefold() or "状态" in entry.key:
            points += 2
        return points, entry.updated_at

    return sorted(entries, key=score, reverse=True)[:limit]


def _format_history_node(node: object) -> str:
    level = getattr(node, "level")
    label = "楼层摘要" if level == 0 else f"剧情总结 L{level}"
    start = getattr(node, "time_start")
    end = getattr(node, "time_end")
    time_label = ""
    if start or end:
        time_label = f"｜时间：{start or '?'}" + (f" → {end}" if end and end != start else "")
    return f"[{label}{time_label}] {getattr(node, 'content')}"
