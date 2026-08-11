"""HTTP 控制器共享的查询、复制和回放辅助函数。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.llm import ModelProviderError
from backend.models import (
    AgentTraceRecord,
    AuditIssueRecord,
    ChatRecord,
    CharacterTemplateRecord,
    CharacterProfileRecord,
    MemoryRecord,
    MessageBookmarkRecord,
    MessageRecord,
    MessageVariantRecord,
    NarrativeLeafRecord,
    NarrativeDeltaRecord,
    NpcRecord,
    PersonaTemplateRecord,
    SceneNodeRecord,
    RoleplayGraphEventRecord,
    SettingChangeRecord,
    StateChangeRecord,
    StoryCheckpointRecord,
    StoryCharacterRecord,
    StoryPersonaRecord,
    StoryWorldBookRecord,
    TimelineAnchorRecord,
    WorldBookTemplateRecord,
    WorldBookEntryRecord,
)
from backend.schemas import (
    AgentTraceRead,
    AgentTurnRead,
    AuditIssueRead,
    AuditResolution,
    AuditStatus,
    ChatCreate,
    ChatRead,
    CheckpointCreate,
    CheckpointRead,
    CharacterTemplateCreate,
    CharacterTemplateRead,
    CharacterProfileRead,
    CharacterProfileUpdate,
    MemoryCreate,
    MemoryCoverageRead,
    MemoryKind,
    MemoryRead,
    MemorySearchRequest,
    MemorySearchResult,
    MemorySummaryRequest,
    MemoryMergeRequest,
    MemoryUpdate,
    NarrativeNodeRead,
    NarrativeDeltaRead,
    NpcRead,
    NpcUpsert,
    PersonaCreate,
    PersonaRead,
    MessageRead,
    MessageBookmarkRead,
    MessageRole,
    MessageSend,
    MessageUpdate,
    MessageVariantRead,
    ProposalStatus,
    SceneNodeRead,
    SceneNodeUpsert,
    StateChangeRead,
    StateEntryRead,
    StateProposalCreate,
    StateResolution,
    StoryCharacterRead,
    StoryPersonaRead,
    StoryBranchCreate,
    StoryWorldBookRead,
    TimelineAnchorCreate,
    TimelineAnchorRead,
    WorldBookTemplateRead,
    WorldBookEntryCreate,
    WorldBookEntryRead,
    WorldBookEntryUpdate,
)
from backend.serializers import (
    audit_read,
    chat_read,
    character_template_read,
    character_read,
    memory_read,
    message_read,
    npc_read,
    persona_template_read,
    scene_read,
    state_change_read,
    state_entry_read,
    story_character_read,
    story_persona_read,
    story_world_book_read,
    timeline_anchor_read,
    trace_read,
    world_book_read,
    world_book_template_read,
)
from backend.services.agent import AgentRuntime
from backend.services.roleplay_graph import RoleplayGraphService
from backend.services.variants import active_variant_clause
from backend.utils import json_dumps, json_loads

__all__ = [
    "_chat_or_404",
    "_memory_or_404",
    "_timeline_or_404",
    "_records_by_ids",
    "_character_values",
    "_apply_character",
    "_copy_character_to_story",
    "_world_values",
    "_apply_world",
    "_copy_world_to_story",
    "_story_character_or_404",
    "_message_or_404",
    "_persona_values",
    "_apply_persona",
    "_copy_persona_to_story",
    "_clean_string_list",
    "_attach_linked_world_books",
    "_agent_turn_read",
    "_message_variant_read",
    "_checkpoint_read",
    "_ensure_message_variants",
    "_preceding_user_message",
    "_state_change_snapshots",
    "_graph_event_snapshots",
    "_apply_variant_effects",
    "_invalidate_changed_message",
    "_copy_story_branch",
    "_story_world_or_404",
    "_world_entry_or_404",
    "_clean_keywords",
]

def _chat_or_404(db: Session, chat_id: UUID) -> ChatRecord:
    record = db.get(ChatRecord, str(chat_id))
    if not record:
        raise HTTPException(status_code=404, detail="聊天存档不存在")
    return record

def _memory_or_404(
    db: Session,
    chat_id: UUID,
    memory_id: UUID,
) -> MemoryRecord:
    record = db.scalar(
        select(MemoryRecord).where(
            MemoryRecord.id == str(memory_id),
            MemoryRecord.chat_id == str(chat_id),
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return record

def _timeline_or_404(
    db: Session,
    chat_id: UUID,
    anchor_id: UUID,
) -> TimelineAnchorRecord:
    record = db.scalar(
        select(TimelineAnchorRecord).where(
            TimelineAnchorRecord.id == str(anchor_id),
            TimelineAnchorRecord.chat_id == str(chat_id),
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="时间锚点不存在")
    return record

def _records_by_ids(
    db: Session,
    model: type[Any],
    ids: list[UUID],
    label: str,
) -> list[Any]:
    """按请求顺序读取模板，并在任意模板不存在时拒绝创建故事。"""
    unique_ids = list(dict.fromkeys(str(item) for item in ids))
    records = [db.get(model, item) for item in unique_ids]
    missing = [item for item, record in zip(unique_ids, records, strict=True) if not record]
    if missing:
        raise HTTPException(status_code=404, detail=f"{label}不存在：{', '.join(missing)}")
    return records

def _character_values(payload: CharacterProfileUpdate) -> dict[str, Any]:
    compatibility = dict(payload.compatibility_data)
    compatibility["saraswati_fields"] = {
        **dict(compatibility.get("saraswati_fields") or {}),
        "post_history_instructions": payload.post_history_instructions,
        "creator": payload.creator,
        "character_version": payload.character_version,
    }
    return {
        "name": payload.name.strip(),
        "identity": payload.identity.strip(),
        "personality": payload.personality.strip(),
        "speaking_style": payload.speaking_style.strip(),
        "scenario": payload.scenario.strip(),
        "avatar": payload.avatar.strip(),
        "appearance": payload.appearance.strip(),
        "first_message": payload.first_message.strip(),
        "alternate_greetings_json": json_dumps(_clean_string_list(payload.alternate_greetings)),
        "example_dialogue": payload.example_dialogue.strip(),
        "tags_json": json_dumps(_clean_string_list(payload.tags)),
        "creator_notes": payload.creator_notes.strip(),
        "system_prompt": payload.system_prompt.strip(),
        "favorite": payload.favorite,
        "world_book_ids_json": json_dumps([str(item) for item in payload.world_book_ids]),
        "compatibility_data_json": json_dumps(compatibility),
    }

def _apply_character(record: Any, payload: CharacterProfileUpdate) -> None:
    for field, value in _character_values(payload).items():
        setattr(record, field, value)

def _copy_character_to_story(
    template: CharacterTemplateRecord,
    chat_id: str,
    now: datetime,
) -> StoryCharacterRecord:
    return StoryCharacterRecord(
        id=str(uuid4()),
        chat_id=chat_id,
        source_template_id=template.id,
        name=template.name,
        identity=template.identity,
        personality=template.personality,
        speaking_style=template.speaking_style,
        scenario=template.scenario,
        avatar=template.avatar,
        appearance=template.appearance,
        first_message=template.first_message,
        alternate_greetings_json=template.alternate_greetings_json,
        example_dialogue=template.example_dialogue,
        tags_json=template.tags_json,
        creator_notes=template.creator_notes,
        system_prompt=template.system_prompt,
        favorite=template.favorite,
        world_book_ids_json=template.world_book_ids_json,
        compatibility_data_json=template.compatibility_data_json,
        created_at=now,
        updated_at=now,
    )

def _world_values(payload: WorldBookEntryCreate) -> dict[str, Any]:
    compatibility = dict(payload.compatibility_data)
    compatibility["saraswati_fields"] = {
        **dict(compatibility.get("saraswati_fields") or {}),
        "selective_logic": payload.selective_logic,
        "probability": payload.probability,
        "match_whole_words": payload.match_whole_words,
        "prevent_recursion": payload.prevent_recursion,
        "depth": payload.depth,
        "sticky": payload.sticky,
        "cooldown": payload.cooldown,
        "delay": payload.delay,
    }
    return {
        "title": payload.title.strip(),
        "keywords_json": json_dumps(_clean_keywords(payload.keywords)),
        "secondary_keywords_json": json_dumps(_clean_keywords(payload.secondary_keywords)),
        "content": payload.content.strip(),
        "priority": payload.priority,
        "enabled": payload.enabled,
        "constant": payload.constant,
        "case_sensitive": payload.case_sensitive,
        "scan_depth": payload.scan_depth,
        "insertion_position": payload.insertion_position,
        "group_name": payload.group_name.strip(),
        "recursive": payload.recursive,
        "token_budget": payload.token_budget,
        "scope": payload.scope,
        "compatibility_data_json": json_dumps(compatibility),
    }

def _apply_world(record: Any, payload: WorldBookEntryCreate) -> None:
    for field, value in _world_values(payload).items():
        setattr(record, field, value)

def _copy_world_to_story(
    template: WorldBookTemplateRecord,
    chat_id: str,
    now: datetime,
) -> StoryWorldBookRecord:
    return StoryWorldBookRecord(
        id=str(uuid4()),
        chat_id=chat_id,
        source_template_id=template.id,
        title=template.title,
        keywords_json=template.keywords_json,
        secondary_keywords_json=template.secondary_keywords_json,
        content=template.content,
        priority=template.priority,
        enabled=template.enabled,
        constant=template.constant,
        case_sensitive=template.case_sensitive,
        scan_depth=template.scan_depth,
        insertion_position=template.insertion_position,
        group_name=template.group_name,
        recursive=template.recursive,
        token_budget=template.token_budget,
        scope="story",
        compatibility_data_json=template.compatibility_data_json,
        created_at=now,
        updated_at=now,
    )

def _story_character_or_404(
    db: Session,
    chat_id: UUID,
    character_id: UUID,
) -> StoryCharacterRecord:
    record = db.scalar(
        select(StoryCharacterRecord).where(
            StoryCharacterRecord.id == str(character_id),
            StoryCharacterRecord.chat_id == str(chat_id),
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="故事角色不存在")
    return record

def _message_or_404(
    db: Session,
    chat_id: UUID,
    message_id: UUID,
) -> MessageRecord:
    record = db.scalar(
        select(MessageRecord).where(
            MessageRecord.id == str(message_id),
            MessageRecord.chat_id == str(chat_id),
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="消息不存在")
    return record

def _persona_values(payload: PersonaCreate) -> dict[str, Any]:
    return {
        "name": payload.name.strip(),
        "avatar": payload.avatar.strip(),
        "identity": payload.identity.strip(),
        "personality": payload.personality.strip(),
        "appearance": payload.appearance.strip(),
        "speaking_style": payload.speaking_style.strip(),
        "world_book_ids_json": json_dumps([str(item) for item in payload.world_book_ids]),
    }

def _apply_persona(record: Any, payload: PersonaCreate) -> None:
    for field, value in _persona_values(payload).items():
        setattr(record, field, value)

def _copy_persona_to_story(
    template: PersonaTemplateRecord,
    chat_id: str,
    now: datetime,
) -> StoryPersonaRecord:
    return StoryPersonaRecord(
        id=str(uuid4()), chat_id=chat_id, source_template_id=template.id,
        name=template.name, avatar=template.avatar, identity=template.identity,
        personality=template.personality, appearance=template.appearance,
        speaking_style=template.speaking_style,
        world_book_ids_json=template.world_book_ids_json,
        created_at=now, updated_at=now,
    )

def _clean_string_list(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))

def _attach_linked_world_books(
    db: Session,
    chat_id: str,
    world_book_ids_json: str,
    now: datetime,
) -> None:
    template_ids = _clean_string_list(json_loads(world_book_ids_json) or [])
    if not template_ids:
        return
    existing = set(db.scalars(
        select(StoryWorldBookRecord.source_template_id).where(
            StoryWorldBookRecord.chat_id == chat_id,
            StoryWorldBookRecord.source_template_id.in_(template_ids),
        )
    ).all())
    pending_ids = [template_id for template_id in template_ids if template_id not in existing]
    if not pending_ids:
        return
    templates = db.scalars(
        select(WorldBookTemplateRecord).where(WorldBookTemplateRecord.id.in_(pending_ids))
    ).all()
    db.add_all(_copy_world_to_story(template, chat_id, now) for template in templates)

def _agent_turn_read(
    runtime: AgentRuntime,
    user_message: MessageRecord,
    result: Any,
) -> AgentTurnRead:
    return AgentTurnRead(
        turn_id=UUID(result.turn_id),
        provider_mode=runtime.model.mode,
        user_message=message_read(user_message),
        assistant_message=message_read(result.assistant_message),
        retrieved_memories=[
            MemorySearchResult(
                memory=memory_read(item.record),
                score=item.score,
                retrieval_reason=item.reason,
            )
            for item in result.retrieved_memories
        ],
        state_proposals=[state_change_read(item) for item in result.state_proposals],
        audit_issues=[audit_read(item) for item in result.audit_issues],
        trace=[trace_read(item) for item in result.traces],
    )

def _message_variant_read(record: MessageVariantRecord) -> MessageVariantRead:
    return MessageVariantRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        message_id=UUID(record.message_id),
        position=record.position,
        content=record.content,
        selected=record.selected,
        created_at=record.created_at,
    )

def _checkpoint_read(record: StoryCheckpointRecord) -> CheckpointRead:
    return CheckpointRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        message_id=UUID(record.message_id),
        name=record.name,
        created_at=record.created_at,
    )

def _ensure_message_variants(
    db: Session,
    message: MessageRecord,
) -> list[MessageVariantRecord]:
    variants = list(
        db.scalars(
            select(MessageVariantRecord)
            .where(MessageVariantRecord.message_id == message.id)
            .order_by(MessageVariantRecord.position)
        ).all()
    )
    if variants:
        return variants
    user_message = _preceding_user_message(db, message)
    initial = MessageVariantRecord(
        id=str(uuid4()),
        chat_id=message.chat_id,
        message_id=message.id,
        position=0,
        content=message.content,
        state_changes_json=json_dumps(
            _state_change_snapshots(db, user_message.id if user_message else None)
        ),
        graph_events_json=json_dumps(
            _graph_event_snapshots(db, user_message.id if user_message else None)
        ),
        selected=True,
        created_at=message.created_at,
    )
    db.add(initial)
    db.commit()
    return [initial]

def _preceding_user_message(
    db: Session,
    message: MessageRecord,
) -> MessageRecord | None:
    return db.scalar(
        select(MessageRecord)
        .where(
            MessageRecord.chat_id == message.chat_id,
            MessageRecord.role == MessageRole.USER.value,
            MessageRecord.created_at < message.created_at,
        )
        .order_by(MessageRecord.created_at.desc())
    )

def _state_change_snapshots(
    db: Session,
    source_message_id: str | None,
) -> list[dict[str, Any]]:
    if not source_message_id:
        return []
    records = db.scalars(
        select(StateChangeRecord)
        .where(StateChangeRecord.source_message_id == source_message_id)
        .order_by(StateChangeRecord.created_at)
    ).all()
    return [
        {
            "entity": item.entity,
            "key": item.key,
            "old_value_json": item.old_value_json,
            "new_value_json": item.new_value_json,
            "reason": item.reason,
            "status": item.status,
            "created_at": item.created_at.isoformat(),
            "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        }
        for item in records
    ]

def _graph_event_snapshots(
    db: Session,
    source_message_id: str | None,
) -> list[dict[str, Any]]:
    if not source_message_id:
        return []
    records = db.scalars(
        select(RoleplayGraphEventRecord)
        .where(RoleplayGraphEventRecord.source_message_id == source_message_id)
        .order_by(RoleplayGraphEventRecord.created_at)
    ).all()
    return [
        {
            "event_type": item.event_type,
            "payload_json": item.payload_json,
            "source_hash": item.source_hash,
            "created_at": item.created_at.isoformat(),
        }
        for item in records
    ]

def _apply_variant_effects(
    db: Session,
    message: MessageRecord,
    variant: MessageVariantRecord,
) -> None:
    """切换正文时同步替换这一轮产生的状态事件和场景事件。"""
    user_message = _preceding_user_message(db, message)
    if not user_message:
        return
    db.execute(
        delete(StateChangeRecord).where(
            StateChangeRecord.chat_id == message.chat_id,
            StateChangeRecord.source_message_id == user_message.id,
        )
    )
    db.execute(
        delete(RoleplayGraphEventRecord).where(
            RoleplayGraphEventRecord.chat_id == message.chat_id,
            RoleplayGraphEventRecord.source_message_id == user_message.id,
        )
    )
    for item in json_loads(variant.state_changes_json) or []:
        db.add(
            StateChangeRecord(
                id=str(uuid4()),
                chat_id=message.chat_id,
                entity=str(item["entity"]),
                key=str(item["key"]),
                old_value_json=item.get("old_value_json"),
                new_value_json=str(item["new_value_json"]),
                reason=str(item["reason"]),
                source_message_id=user_message.id,
                status=str(item["status"]),
                created_at=datetime.fromisoformat(str(item["created_at"])),
                resolved_at=(
                    datetime.fromisoformat(str(item["resolved_at"]))
                    if item.get("resolved_at")
                    else None
                ),
            )
        )
    for item in json_loads(variant.graph_events_json) or []:
        db.add(
            RoleplayGraphEventRecord(
                id=str(uuid4()),
                chat_id=message.chat_id,
                event_type=str(item["event_type"]),
                payload_json=str(item["payload_json"]),
                source_message_id=user_message.id,
                source_hash=item.get("source_hash"),
                created_at=datetime.fromisoformat(str(item["created_at"])),
            )
        )

def _invalidate_changed_message(db: Session, chat_id: str, message_id: str) -> None:
    """撤销改写前产生的自动修改，投影稍后会按剩余事件重建。"""
    affected_leaves = db.scalars(
        select(NarrativeLeafRecord).where(
            NarrativeLeafRecord.chat_id == chat_id,
            (
                (NarrativeLeafRecord.user_message_id == message_id)
                | (NarrativeLeafRecord.assistant_message_id == message_id)
            ),
        )
    ).all()
    affected_sources = {
        source_id
        for leaf in affected_leaves
        for source_id in (leaf.user_message_id, leaf.assistant_message_id)
    }
    if not affected_sources:
        return
    db.execute(
        delete(RoleplayGraphEventRecord).where(
            RoleplayGraphEventRecord.chat_id == chat_id,
            RoleplayGraphEventRecord.source_message_id.in_(affected_sources),
        )
    )
    approved_changes = db.scalars(
        select(StateChangeRecord).where(
            StateChangeRecord.chat_id == chat_id,
            StateChangeRecord.source_message_id.in_(affected_sources),
            StateChangeRecord.status == ProposalStatus.APPROVED.value,
        )
    ).all()
    for change in approved_changes:
        change.status = ProposalStatus.REVERTED.value
        if not change.reason.startswith("源剧情已改写"):
            change.reason = f"源剧情已改写，原修改已撤销：{change.reason}"

def _copy_story_branch(
    db: Session,
    source: ChatRecord,
    through_message: MessageRecord,
    requested_title: str | None,
    runtime: AgentRuntime,
) -> ChatRecord:
    """复制指定消息之前的线性剧情；原故事始终保留。"""
    now = datetime.now(UTC)
    branch = ChatRecord(
        id=str(uuid4()),
        title=(requested_title or f"{source.title} · 分支").strip(),
        system_prompt=source.system_prompt,
        created_at=now,
        updated_at=now,
    )
    db.add(branch)
    characters = db.scalars(
        select(StoryCharacterRecord)
        .where(StoryCharacterRecord.chat_id == source.id)
        .order_by(StoryCharacterRecord.created_at)
    ).all()
    setting_target_ids: dict[str, str] = {}
    for item in characters:
        copied_character_id = str(uuid4())
        setting_target_ids[item.id] = copied_character_id
        db.add(
            StoryCharacterRecord(
                id=copied_character_id,
                chat_id=branch.id,
                source_template_id=item.source_template_id,
                name=item.name,
                identity=item.identity,
                personality=item.personality,
                speaking_style=item.speaking_style,
                scenario=item.scenario,
                avatar=item.avatar,
                appearance=item.appearance,
                first_message=item.first_message,
                alternate_greetings_json=item.alternate_greetings_json,
                example_dialogue=item.example_dialogue,
                tags_json=item.tags_json,
                creator_notes=item.creator_notes,
                system_prompt=item.system_prompt,
                favorite=item.favorite,
                world_book_ids_json=item.world_book_ids_json,
                compatibility_data_json=item.compatibility_data_json,
                created_at=now,
                updated_at=now,
            )
        )
    world_entries = db.scalars(
        select(StoryWorldBookRecord)
        .where(StoryWorldBookRecord.chat_id == source.id)
        .order_by(StoryWorldBookRecord.created_at)
    ).all()
    for item in world_entries:
        copied_world_id = str(uuid4())
        setting_target_ids[item.id] = copied_world_id
        db.add(
            StoryWorldBookRecord(
                id=copied_world_id,
                chat_id=branch.id,
                source_template_id=item.source_template_id,
                title=item.title,
                keywords_json=item.keywords_json,
                secondary_keywords_json=item.secondary_keywords_json,
                content=item.content,
                priority=item.priority,
                enabled=item.enabled,
                constant=item.constant,
                case_sensitive=item.case_sensitive,
                scan_depth=item.scan_depth,
                insertion_position=item.insertion_position,
                group_name=item.group_name,
                recursive=item.recursive,
                token_budget=item.token_budget,
                scope=item.scope,
                compatibility_data_json=item.compatibility_data_json,
                created_at=now,
                updated_at=now,
            )
        )
    persona = db.scalar(
        select(StoryPersonaRecord).where(StoryPersonaRecord.chat_id == source.id)
    )
    if persona:
        copied_persona_id = str(uuid4())
        setting_target_ids[persona.id] = copied_persona_id
        db.add(StoryPersonaRecord(
            id=copied_persona_id, chat_id=branch.id,
            source_template_id=persona.source_template_id, name=persona.name,
            avatar=persona.avatar, identity=persona.identity,
            personality=persona.personality, appearance=persona.appearance,
            speaking_style=persona.speaking_style,
            world_book_ids_json=persona.world_book_ids_json,
            created_at=now, updated_at=now,
        ))
    messages = db.scalars(
        select(MessageRecord)
        .where(
            MessageRecord.chat_id == source.id,
            MessageRecord.created_at <= through_message.created_at,
        )
        .order_by(MessageRecord.created_at)
    ).all()
    message_ids: dict[str, str] = {}
    variant_ids: dict[str, str] = {}
    for index, item in enumerate(messages):
        copied_id = str(uuid4())
        message_ids[item.id] = copied_id
        db.add(
            MessageRecord(
                id=copied_id,
                chat_id=branch.id,
                role=item.role,
                content=item.content,
                created_at=now + timedelta(microseconds=index),
            )
        )
        if item.role == MessageRole.ASSISTANT.value:
            source_variant = db.scalar(select(MessageVariantRecord).where(
                MessageVariantRecord.message_id == item.id,
                MessageVariantRecord.selected.is_(True),
            ))
            copied_variant_id = str(uuid4())
            if source_variant:
                variant_ids[source_variant.id] = copied_variant_id
            db.add(MessageVariantRecord(
                id=copied_variant_id, chat_id=branch.id, message_id=copied_id,
                position=0, content=item.content, state_changes_json="[]",
                graph_events_json="[]", selected=True,
                created_at=now + timedelta(microseconds=index),
            ))
    changes = db.scalars(
        select(StateChangeRecord)
        .where(
            StateChangeRecord.chat_id == source.id,
            StateChangeRecord.source_message_id.in_(message_ids),
            active_variant_clause(StateChangeRecord.variant_id),
        )
        .order_by(StateChangeRecord.created_at)
    ).all()
    for item in changes:
        db.add(
            StateChangeRecord(
                id=str(uuid4()),
                chat_id=branch.id,
                entity=item.entity,
                key=item.key,
                old_value_json=item.old_value_json,
                new_value_json=item.new_value_json,
                reason=item.reason,
                event_fingerprint=item.event_fingerprint,
                source_message_id=message_ids[item.source_message_id],
                variant_id=variant_ids.get(item.variant_id or ""),
                status=item.status,
                created_at=item.created_at,
                resolved_at=item.resolved_at,
            )
        )
    setting_changes = db.scalars(
        select(SettingChangeRecord)
        .where(
            SettingChangeRecord.chat_id == source.id,
            SettingChangeRecord.source_message_id.in_(message_ids),
            active_variant_clause(SettingChangeRecord.variant_id),
        )
        .order_by(SettingChangeRecord.created_at)
    ).all()
    for item in setting_changes:
        copied_target_id = setting_target_ids.get(item.target_id)
        if copied_target_id is None:
            continue
        db.add(SettingChangeRecord(
            id=str(uuid4()),
            chat_id=branch.id,
            target_type=item.target_type,
            target_id=copied_target_id,
            field=item.field,
            base_value=item.base_value,
            new_value=item.new_value,
            reason=item.reason,
            evidence=item.evidence,
            importance=item.importance,
            confidence=item.confidence,
            source_message_id=message_ids.get(item.source_message_id or ""),
            variant_id=variant_ids.get(item.variant_id or ""),
            status=item.status,
            created_at=item.created_at,
            resolved_at=item.resolved_at,
        ))
    graph_events = db.scalars(
        select(RoleplayGraphEventRecord)
        .where(
            RoleplayGraphEventRecord.chat_id == source.id,
            RoleplayGraphEventRecord.source_message_id.in_(message_ids),
            active_variant_clause(RoleplayGraphEventRecord.variant_id),
        )
        .order_by(RoleplayGraphEventRecord.created_at)
    ).all()
    for item in graph_events:
        db.add(
            RoleplayGraphEventRecord(
                id=str(uuid4()),
                chat_id=branch.id,
                event_type=item.event_type,
                payload_json=item.payload_json,
                source_message_id=message_ids[item.source_message_id],
                variant_id=variant_ids.get(item.variant_id or ""),
                source_hash=item.source_hash,
                created_at=item.created_at,
            )
        )
    branch.updated_at = now
    db.commit()
    runtime.state_service.rebuild_entries(db, branch.id)
    runtime.graph_service.rebuild_projections(db, branch.id)
    runtime.setting_evolution_service.rebuild(db, branch.id)
    db.refresh(branch)
    return branch

def _story_world_or_404(
    db: Session,
    chat_id: UUID,
    entry_id: UUID,
) -> StoryWorldBookRecord:
    record = db.scalar(
        select(StoryWorldBookRecord).where(
            StoryWorldBookRecord.id == str(entry_id),
            StoryWorldBookRecord.chat_id == str(chat_id),
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="故事世界书不存在")
    return record

def _world_entry_or_404(
    db: Session,
    chat_id: UUID,
    entry_id: UUID,
) -> WorldBookEntryRecord:
    record = db.scalar(
        select(WorldBookEntryRecord).where(
            WorldBookEntryRecord.id == str(entry_id),
            WorldBookEntryRecord.chat_id == str(chat_id),
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="世界书词条不存在")
    return record

def _clean_keywords(keywords: list[str]) -> list[str]:
    """清理空关键词并去重，避免同一触发词重复进入上下文。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw_keyword in keywords:
        keyword = raw_keyword.strip()[:100]
        normalized = keyword.casefold()
        if keyword and normalized not in seen:
            seen.add(normalized)
            result.append(keyword)
    return result
