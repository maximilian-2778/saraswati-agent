"""为单轮生成组装受控上下文。"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.llm import ModelClient
from backend.models import (
    ChatRecord,
    MessageRecord,
    StoryCharacterRecord,
    StoryWorldBookRecord,
)
from backend.services.memory import MemoryService, RetrievedMemory
from backend.services.state import StateService
from backend.utils import json_loads


@dataclass(slots=True)
class ContextBundle:
    messages: list[dict[str, Any]]
    retrieved_memories: list[RetrievedMemory]
    state_count: int
    character_configured: bool
    world_entry_ids: list[str]


class ContextBuilder:
    """组合系统提示词、状态、记忆和近期原文。"""

    def __init__(
        self,
        settings: Settings,
        memory_service: MemoryService,
        state_service: StateService,
    ) -> None:
        self.settings = settings
        self.memory_service = memory_service
        self.state_service = state_service

    async def build(
        self,
        db: Session,
        model: ModelClient,
        chat: ChatRecord,
        query: str,
    ) -> ContextBundle:
        retrieved = await self.memory_service.search(
            db,
            model,
            chat.id,
            query,
            self.settings.rag_limit,
        )
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
        recent_desc = db.scalars(
            select(MessageRecord)
            .where(MessageRecord.chat_id == chat.id)
            .order_by(MessageRecord.created_at.desc())
            .limit(self.settings.recent_message_limit)
        ).all()
        recent = list(reversed(recent_desc))

        state_lines = [
            f"- {entry.entity}.{entry.key} = {json_loads(entry.value_json)!r}"
            for entry in state_entries
        ]
        memory_lines = [
            (
                f"- [{item.record.kind}] {item.record.content} "
                f"(来源消息: {item.record.source_message_id or '无'}, "
                f"召回分数: {item.score:.3f})"
            )
            for item in retrieved
        ]

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

        system_prompt = "你正在进行长篇角色扮演。保持人物语气、剧情连贯和沉浸感。"
        if chat.system_prompt.strip():
            system_prompt += f"\n\n旧版补充设定：\n{chat.system_prompt.strip()}"
        system_prompt += (
            "\n\n当前角色档案：\n"
            + ("\n".join(character_lines) if character_lines else "- 暂未设置")
            + "\n\n本轮触发的世界书：\n"
            + ("\n".join(world_lines) if world_lines else "- 本轮没有触发词条")
        )
        system_prompt += (
            "\n\n你可以调用工具查询记忆和精确状态。"
            "结构化状态是数值和物品的事实来源；不要擅自假设或覆盖。"
            "剧情发生明确状态变化时，调用 propose_state_change 提出建议，"
            "由用户审核后才会生效。"
            "只有值得长期保留的信息才调用 write_memory。"
            "\n\n当前已批准状态：\n"
            + ("\n".join(state_lines) if state_lines else "- 暂无")
            + "\n\n本轮召回记忆：\n"
            + ("\n".join(memory_lines) if memory_lines else "- 暂无")
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        messages.extend(
            {"role": record.role, "content": record.content}
            for record in recent
            if record.role in {"user", "assistant", "system"}
        )
        return ContextBundle(
            messages,
            retrieved,
            len(state_entries),
            bool(character_lines),
            [record.id for record in active_world_entries[:12]],
        )
