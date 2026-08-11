"""为单轮生成组装受控上下文。"""

from dataclasses import dataclass
from datetime import datetime
import re
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.llm import ModelClient
from backend.models import (
    ChatRecord,
    MemoryRecord,
    MessageRecord,
    PromptPresetRecord,
    StateEntryRecord,
    StoryCharacterRecord,
    StoryPersonaRecord,
    StoryWorldBookRecord,
)
from backend.schemas import MemoryKind


# Per-process activation windows. They are deliberately ephemeral: lorebook timing
# affects generation, but does not become canonical story data or pollute exports.
_WORLD_ENTRY_WINDOWS: dict[str, tuple[int, int]] = {}
from backend.services.memory import MemoryService, RetrievedMemory
from backend.services.narrative_memory import NarrativeMemoryService
from backend.services.roleplay_graph import RoleplayGraphService
from backend.services.state import StateService
from backend.services.timeline import timeline_service
from backend.services.world_engine import WorldEngineService
from backend.services.token_budget import TokenBudgetManager
from backend.services.variants import (
    active_variant_clause,
    active_variant_ids,
    variant_scope_is_active,
)
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
        world_engine_service: WorldEngineService,
    ) -> None:
        self.settings = settings
        self.memory_service = memory_service
        self.state_service = state_service
        self.narrative_memory_service = narrative_memory_service
        self.graph_service = graph_service
        self.world_engine_service = world_engine_service
        self.budget_manager = TokenBudgetManager()

    async def build(
        self,
        db: Session,
        model: ModelClient,
        chat: ChatRecord,
        query: str,
        include_debug_content: bool = False,
        through: datetime | None = None,
    ) -> ContextBundle:
        state_entries = self.state_service.list_entries(db, chat.id)
        characters = db.scalars(
            select(StoryCharacterRecord)
            .where(StoryCharacterRecord.chat_id == chat.id)
            .order_by(StoryCharacterRecord.created_at)
        ).all()
        persona = db.scalar(
            select(StoryPersonaRecord).where(StoryPersonaRecord.chat_id == chat.id)
        )
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
                    active_variant_clause(MemoryRecord.variant_id),
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
                    f"外貌：{character.appearance}" if character.appearance else "",
                    f"说话风格：{character.speaking_style}" if character.speaking_style else "",
                    f"当前情境：{character.scenario}" if character.scenario else "",
                    f"示例对话：{character.example_dialogue}" if character.example_dialogue else "",
                ]
                if item
            )
            character_lines.append(f"- {character.name}" + (f"｜{details}" if details else ""))

        active_world_entries = _activate_world_entries(world_records, recent, query)
        world_trigger_log = _world_trigger_log(
            world_records,
            active_world_entries,
            recent,
            query,
        )
        world_lines = [
            f"- [{record.title}｜{record.insertion_position}｜优先级 {record.priority}] "
            f"{record.content[: record.token_budget * 4]}"
            for record in active_world_entries[:12]
        ]
        roleplay_graph = self.graph_service.context_text(db, chat.id, query)
        timeline_context = timeline_service.context_text(db, chat.id)
        evolving_world = self.world_engine_service.context_text(db, chat.id)

        system_prompt = "你正在进行长篇角色扮演。保持人物语气、剧情连贯和沉浸感。"
        if chat.system_prompt.strip():
            system_prompt += f"\n\n旧版补充设定：\n{chat.system_prompt.strip()}"
        if persona:
            persona_parts = [
                f"身份：{persona.identity}" if persona.identity else "",
                f"性格：{persona.personality}" if persona.personality else "",
                f"外貌：{persona.appearance}" if persona.appearance else "",
                f"说话方式：{persona.speaking_style}" if persona.speaking_style else "",
            ]
            system_prompt += "\n\n玩家身份：\n- " + persona.name
            details = "；".join(item for item in persona_parts if item)
            if details:
                system_prompt += f"｜{details}"
        character_prompts = [item.system_prompt.strip() for item in characters if item.system_prompt.strip()]
        if character_prompts:
            system_prompt += "\n\n角色专属指令：\n" + "\n".join(character_prompts)
        post_history_prompts = []
        for item in characters:
            compatibility = json_loads(item.compatibility_data_json) or {}
            value = str((compatibility.get("saraswati_fields") or {}).get("post_history_instructions", "")).strip()
            if value:
                post_history_prompts.append(value)
        if post_history_prompts:
            system_prompt += "\n\n对话历史后的角色指令：\n" + "\n".join(post_history_prompts)
        system_prompt += (
            "\n\n当前角色档案：\n"
            + ("\n".join(character_lines) if character_lines else "- 暂未设置")
            + "\n\n本轮触发的世界书：\n"
            + ("\n".join(world_lines) if world_lines else "- 本轮没有触发词条")
            + "\n\n当前场景与人物关系：\n"
            + (roleplay_graph or "- 暂无结构化场景或 NPC 记录")
            + "\n\n故事时间线：\n"
            + (timeline_context or "- 暂无明确的故事时间锚点")
            + "\n\n持续演化的世界状态：\n"
            + (evolving_world or "- 尚未启用世界推演")
        )
        system_prompt += (
            "\n\n你可以调用工具查询记忆和精确状态。"
            "结构化状态是数值和物品的事实来源；不要擅自假设或覆盖。"
            "剧情发生明确状态变化时，调用 propose_state_change 记录修改，系统会自动采用并保留撤销记录，"
            "需要持续追踪的物品、NPC、场景、计划或悬念也使用结构化状态维护；"
            "实体名称分别以‘物品:’、‘NPC:’、‘场景:’、‘悬念:’开头，"
            "已完成的计划或悬念将 status 建议为 resolved。"
            "只有值得长期保留的信息才调用 write_memory。"
            "发现地点层级或当前位置变化时调用 upsert_scene；同一地点出现简称或别称时复用现有节点，"
            "只有明确移动到另一个地方才创建新节点。NPC 登离场、位置、状态或关系变化时调用 upsert_npc。"
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
        persona_text = ""
        if persona:
            persona_text = "\n".join(
                item for item in [
                    f"名称：{persona.name}",
                    f"身份：{persona.identity}" if persona.identity else "",
                    f"性格：{persona.personality}" if persona.personality else "",
                    f"外貌：{persona.appearance}" if persona.appearance else "",
                    f"说话方式：{persona.speaking_style}" if persona.speaking_style else "",
                ] if item
            )
        latest_user = recent[-1] if recent and recent[-1].role == "user" else None
        recent_dialogue = recent[:-1] if latest_user else recent
        summary_text = "\n\n".join(_format_history_node(item) for item in history_nodes)
        section_definitions = [
            ("system", "系统规则", True, "角色扮演基础规则、故事补充规则和工具使用约束", _system_rules_preview(chat)),
            ("persona", "当前主控人物", bool(persona_text), "故事绑定的主控人物快照", persona_text),
            ("characters", "角色设定", bool(character_lines), "故事绑定的角色快照", "\n".join(character_lines)),
            ("world_book", "激活的世界书", bool(world_lines), "关键词、常驻、递归和互斥规则筛选后的词条", "\n".join(world_lines)),
            ("summary", "长期总结", bool(summary_text), "近期窗口之外的最高可信摘要节点", summary_text),
            ("rag", "RAG 召回记忆", bool(memory_lines), "与用户最新消息相关的长期记忆", "\n".join(memory_lines)),
            ("scene", "当前场景和人物", bool(roleplay_graph), "当前地点、在场 NPC 和相关人物关系", roleplay_graph),
            ("timeline", "故事时间线", bool(timeline_context), "当前故事时间、最近推进与时间矛盾", timeline_context),
            ("evolving_world", "世界演化状态", bool(evolving_world), "势力、持续事件和正在传播的信息", evolving_world),
            ("state", "数值与物品状态", bool(state_lines), "与本轮话题相关的已批准精确状态", "\n".join(state_lines)),
            ("recent", "最近对话", bool(recent_dialogue), "仍在原文窗口内的最近消息", "\n\n".join(f"{item.role}: {item.content}" for item in recent_dialogue)),
            ("latest_user", "用户最新消息", bool(latest_user), "触发本轮生成的消息", latest_user.content if latest_user else query),
        ]
        preset = db.get(PromptPresetRecord, self.settings.active_preset_id) if self.settings.active_preset_id else None
        if preset is not None:
            messages, preset_sections = _apply_writing_preset(
                preset=preset,
                messages=messages,
                persona=persona,
                characters=characters,
            )
            section_definitions = [section_definitions[0], *preset_sections, *section_definitions[1:]]
        section_texts = {label: content for _, label, _, _, content in section_definitions}
        input_budget = max(1024, self.settings.context_window_tokens - self.settings.max_output_tokens)
        messages, diagnostics = self.budget_manager.fit(
            messages,
            input_budget,
            section_texts,
            model_name=model.model_name,
            include_debug_content=include_debug_content,
        )
        for key, label, enabled, reason, content in section_definitions:
            section_diagnostics = diagnostics["sections"].get(label, {})
            section_diagnostics.update(
                {
                    "key": key,
                    "label": label,
                    "enabled": enabled,
                    "reason": reason if enabled else "本轮没有可加入的内容",
                }
            )
            if include_debug_content:
                section_diagnostics["content"] = content
        diagnostics["sections"] = [
            diagnostics["sections"][label]
            for _, label, _, _, _ in section_definitions
        ]
        diagnostics["world_book_triggers"] = (
            world_trigger_log
            if include_debug_content
            else [{"id": item["id"], "included": item["included"]} for item in world_trigger_log]
        )
        selected_variants = active_variant_ids(db, chat.id)
        pinned_memories = [
            item for item in pinned_memories
            if variant_scope_is_active(item.variant_ids_json, selected_variants)
        ]
        diagnostics["rag_retrieval"] = [
            {
                "memory_id": item.record.id,
                "score": round(item.score, 6),
                **({"reason": item.reason} if include_debug_content else {}),
                **({"preview": item.record.content[:240]} if include_debug_content else {}),
            }
            for item in retrieved
        ]
        diagnostics["debug_content_included"] = include_debug_content
        if include_debug_content:
            diagnostics["final_prompt"] = messages
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


def _activate_world_entries(
    records: list[StoryWorldBookRecord],
    recent: list[MessageRecord],
    query: str,
) -> list[StoryWorldBookRecord]:
    """按每条词条的扫描范围激活，并处理递归和互斥组。"""
    active: list[StoryWorldBookRecord] = []
    active_ids: set[str] = set()
    turn = len(recent)

    def matches(record: StoryWorldBookRecord, extra: str = "") -> bool:
        compatibility = json_loads(record.compatibility_data_json) or {}
        options = compatibility.get("saraswati_fields") or {}
        active_until, cooldown_until = _WORLD_ENTRY_WINDOWS.get(record.id, (-1, -1))
        if turn <= active_until:
            return True
        if turn <= cooldown_until or turn < max(0, int(options.get("delay", 0))):
            return False
        history = "\n".join(item.content for item in recent[-record.scan_depth:])
        haystack = f"{history}\n{query}\n{extra}"
        if not record.case_sensitive:
            haystack = haystack.casefold()
        primary = [str(item) for item in (json_loads(record.keywords_json) or [])]
        secondary = [str(item) for item in (json_loads(record.secondary_keywords_json) or [])]

        def contains(value: str) -> bool:
            needle = value if record.case_sensitive else value.casefold()
            if options.get("match_whole_words"):
                return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None
            return needle in haystack

        primary_ok = record.constant or not primary or any(contains(item) for item in primary)
        matches_secondary = [contains(item) for item in secondary]
        logic = options.get("selective_logic", "and_any")
        secondary_ok = (
            not secondary
            or (logic == "and_all" and all(matches_secondary))
            or (logic == "not_any" and not any(matches_secondary))
            or (logic == "not_all" and not all(matches_secondary))
            or (logic == "and_any" and any(matches_secondary))
        )
        probability = max(0, min(100, int(options.get("probability", 100))))
        return primary_ok and secondary_ok and (probability >= 100 or secrets.randbelow(100) < probability)

    def mark_activation(record: StoryWorldBookRecord) -> None:
        options = (json_loads(record.compatibility_data_json) or {}).get("saraswati_fields") or {}
        sticky = max(0, int(options.get("sticky", 0)))
        cooldown = max(0, int(options.get("cooldown", 0)))
        _WORLD_ENTRY_WINDOWS[record.id] = (turn + sticky, turn + sticky + cooldown)

    for record in records:
        if matches(record):
            active.append(record)
            active_ids.add(record.id)
            mark_activation(record)

    changed = True
    while changed:
        changed = False
        recursive_text = "\n".join(
            item.content for item in active
            if item.recursive and not (json_loads(item.compatibility_data_json) or {}).get("saraswati_fields", {}).get("prevent_recursion", False)
        )
        if not recursive_text:
            break
        for record in records:
            if record.id not in active_ids and matches(record, recursive_text):
                active.append(record)
                active_ids.add(record.id)
                mark_activation(record)
                changed = True

    grouped: dict[str, StoryWorldBookRecord] = {}
    ungrouped: list[StoryWorldBookRecord] = []
    for record in active:
        if record.group_name:
            current = grouped.get(record.group_name)
            if current is None or record.priority > current.priority:
                grouped[record.group_name] = record
        else:
            ungrouped.append(record)
    return sorted([*ungrouped, *grouped.values()], key=lambda item: item.priority, reverse=True)


def _world_trigger_log(
    records: list[StoryWorldBookRecord],
    active: list[StoryWorldBookRecord],
    recent: list[MessageRecord],
    query: str,
) -> list[dict[str, Any]]:
    active_ids = {record.id for record in active}
    history = "\n".join(item.content for item in recent)
    result: list[dict[str, Any]] = []
    for record in records:
        haystack = f"{history}\n{query}"
        if not record.case_sensitive:
            haystack = haystack.casefold()
        keywords = [str(item) for item in (json_loads(record.keywords_json) or [])]
        matched = [
            keyword for keyword in keywords
            if (keyword if record.case_sensitive else keyword.casefold()) in haystack
        ]
        included = record.id in active_ids
        if included and record.constant:
            reason = "常驻条目"
        elif included and matched:
            reason = f"命中关键词：{'、'.join(matched[:5])}"
        elif included:
            reason = "由递归激活或无主关键词"
        elif matched:
            reason = "命中但因次要关键词或互斥组未加入"
        else:
            reason = "未命中本轮内容"
        result.append(
            {
                "id": record.id,
                "title": record.title,
                "included": included,
                "priority": record.priority,
                "reason": reason,
            }
        )
    return result


def _format_history_node(node: object) -> str:
    level = getattr(node, "level")
    label = "楼层摘要" if level == 0 else f"剧情总结 L{level}"
    start = getattr(node, "time_start")
    end = getattr(node, "time_end")
    time_label = ""
    if start or end:
        time_label = f"｜时间：{start or '?'}" + (f" → {end}" if end and end != start else "")
    return f"[{label}{time_label}] {getattr(node, 'content')}"


def _system_rules_preview(chat: ChatRecord) -> str:
    parts = ["你正在进行长篇角色扮演。保持人物语气、剧情连贯和沉浸感。"]
    if chat.system_prompt.strip():
        parts.append(f"旧版补充设定：\n{chat.system_prompt.strip()}")
    parts.append(
        "可以调用工具查询记忆和精确状态。结构化状态是数值和物品的事实来源；"
        "明确状态变化会自动记录，并保留可撤销的修改历史。只有值得长期保留的信息才写入记忆；"
        "场景层级、当前位置、NPC 状态和关系变化使用对应工具维护。"
    )
    return "\n\n".join(parts)


_PRESET_DYNAMIC_SLOTS = {
    "worldInfoBefore",
    "worldInfoAfter",
    "personaDescription",
    "charDescription",
    "charPersonality",
    "scenario",
    "dialogueExamples",
    "longTermMemory",
    "ragMemory",
    "roleplayState",
    "chatHistory",
}


def _apply_writing_preset(
    *,
    preset: PromptPresetRecord,
    messages: list[dict[str, Any]],
    persona: StoryPersonaRecord | None,
    characters: list[StoryCharacterRecord],
) -> tuple[list[dict[str, Any]], list[tuple[str, str, bool, str, str]]]:
    """把写作提示词加入标准上下文，不接管角色、世界书或聊天记录。"""
    prompts = json_loads(preset.prompts_json) or []
    char_names = "、".join(item.name for item in characters) or "角色"
    user_name = persona.name if persona else "用户"
    result = [dict(item) for item in messages]
    diagnostics: list[tuple[str, str, bool, str, str]] = []
    relative: list[dict[str, Any]] = []
    in_chat: list[tuple[int, dict[str, Any]]] = []
    for index, raw in enumerate(prompts):
        identifier = str(raw.get("identifier") or f"custom-{index}")
        if bool(raw.get("marker", False)) or identifier in _PRESET_DYNAMIC_SLOTS:
            continue
        name = str(raw.get("name") or identifier)
        enabled = bool(raw.get("enabled", True))
        content = str(raw.get("content") or "")
        content = _preset_macros(content, char_names, user_name)
        diagnostics.append(
            (
                f"preset:{identifier}",
                f"预设 · {name}",
                enabled and bool(content),
                f"写作预设：{preset.name}",
                content,
            )
        )
        if not enabled or not content:
            continue
        role = str(raw.get("role") or "system")
        if role not in {"system", "user", "assistant"}:
            role = "system"
        message = {"role": role, "content": content}
        if raw.get("position") == "in_chat":
            in_chat.append((max(0, int(raw.get("depth", 0) or 0)), message))
        else:
            relative.append(message)
    result[1:1] = relative
    for depth, message in in_chat:
        result.insert(max(1, len(result) - depth), message)
    return result, diagnostics


def _preset_macros(content: str, char_name: str, user_name: str) -> str:
    return content.replace("{{char}}", char_name).replace("{{user}}", user_name)
