"""故事、设定副本、消息、分支和检查点。"""

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
    WorldBookBatchRequest,
    WorldBookBatchResult,
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
from backend.utils import json_dumps, json_loads

from backend.controller_helpers import (
    _chat_or_404,
    _memory_or_404,
    _timeline_or_404,
    _records_by_ids,
    _character_values,
    _apply_character,
    _copy_character_to_story,
    _world_values,
    _apply_world,
    _copy_world_to_story,
    _story_character_or_404,
    _message_or_404,
    _persona_values,
    _apply_persona,
    _copy_persona_to_story,
    _clean_string_list,
    _attach_linked_world_books,
    _agent_turn_read,
    _message_variant_read,
    _checkpoint_read,
    _ensure_message_variants,
    _preceding_user_message,
    _state_change_snapshots,
    _graph_event_snapshots,
    _apply_variant_effects,
    _invalidate_changed_message,
    _copy_story_branch,
    _story_world_or_404,
    _world_entry_or_404,
    _clean_keywords,
)

router = APIRouter()

@router.post(
    "/chats",
    response_model=ChatRead,
    status_code=status.HTTP_201_CREATED,
    tags=["chats"],
)
def create_chat(payload: ChatCreate, db: Session = Depends(get_db)) -> ChatRead:
    """创建故事，并把选中的角色与世界书模板复制为故事私有快照。"""
    now = datetime.now(UTC)
    character_templates = _records_by_ids(
        db, CharacterTemplateRecord, payload.character_template_ids, "角色模板"
    )
    persona_template = (
        db.get(PersonaTemplateRecord, str(payload.persona_template_id))
        if payload.persona_template_id
        else None
    )
    if payload.persona_template_id and not persona_template:
        raise HTTPException(status_code=404, detail="主控人物不存在")
    linked_world_ids = [str(item) for item in payload.world_book_template_ids]
    for template in character_templates:
        linked_world_ids.extend(json_loads(template.world_book_ids_json) or [])
    if persona_template:
        linked_world_ids.extend(json_loads(persona_template.world_book_ids_json) or [])
    world_templates = _records_by_ids(
        db,
        WorldBookTemplateRecord,
        [UUID(item) for item in dict.fromkeys(linked_world_ids)],
        "世界书模板",
    )
    record = ChatRecord(
        id=str(uuid4()),
        title=payload.title,
        system_prompt=payload.system_prompt,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    if persona_template:
        db.add(_copy_persona_to_story(persona_template, record.id, now))
    for template in character_templates:
        db.add(_copy_character_to_story(template, record.id, now))
    for template in world_templates:
        db.add(_copy_world_to_story(template, record.id, now))
    if character_templates and character_templates[0].first_message.strip():
        greeting = MessageRecord(
            id=str(uuid4()), chat_id=record.id, role="assistant",
            content=character_templates[0].first_message.strip(), created_at=now,
        )
        db.add(greeting)
        greetings = [
            character_templates[0].first_message.strip(),
            *_clean_string_list(json_loads(character_templates[0].alternate_greetings_json) or []),
        ]
        for position, content in enumerate(dict.fromkeys(greetings)):
            db.add(MessageVariantRecord(
                id=str(uuid4()), chat_id=record.id, message_id=greeting.id,
                position=position, content=content, selected=position == 0, created_at=now,
            ))
    db.commit()
    db.refresh(record)
    return chat_read(record)

@router.get("/chats", response_model=list[ChatRead], tags=["chats"])
def list_chats(db: Session = Depends(get_db)) -> list[ChatRead]:
    records = db.scalars(
        select(ChatRecord).order_by(ChatRecord.updated_at.desc())
    ).all()
    return [chat_read(record) for record in records]

@router.get("/chats/{chat_id}", response_model=ChatRead, tags=["chats"])
def get_chat(chat_id: UUID, db: Session = Depends(get_db)) -> ChatRead:
    return chat_read(_chat_or_404(db, chat_id))

@router.delete(
    "/chats/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["chats"],
)
def delete_chat(chat_id: UUID, db: Session = Depends(get_db)) -> Response:
    db.delete(_chat_or_404(db, chat_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get(
    "/chats/{chat_id}/persona",
    response_model=StoryPersonaRead | None,
    tags=["story-bindings"],
)
def get_story_persona(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> StoryPersonaRead | None:
    _chat_or_404(db, chat_id)
    record = db.scalar(
        select(StoryPersonaRecord).where(StoryPersonaRecord.chat_id == str(chat_id))
    )
    return story_persona_read(record) if record else None

@router.post(
    "/chats/{chat_id}/persona/from-template/{persona_id}",
    response_model=StoryPersonaRead,
    tags=["story-bindings"],
)
def attach_persona_template(
    chat_id: UUID,
    persona_id: UUID,
    db: Session = Depends(get_db),
) -> StoryPersonaRead:
    chat = _chat_or_404(db, chat_id)
    template = db.get(PersonaTemplateRecord, str(persona_id))
    if not template:
        raise HTTPException(status_code=404, detail="主控人物不存在")
    old = db.scalar(select(StoryPersonaRecord).where(StoryPersonaRecord.chat_id == str(chat_id)))
    if old:
        db.delete(old)
    now = datetime.now(UTC)
    record = _copy_persona_to_story(template, str(chat_id), now)
    db.add(record)
    _attach_linked_world_books(db, str(chat_id), template.world_book_ids_json, now)
    chat.updated_at = now
    db.commit()
    db.refresh(record)
    return story_persona_read(record)

@router.put(
    "/chats/{chat_id}/persona",
    response_model=StoryPersonaRead,
    tags=["story-bindings"],
)
def update_story_persona(
    chat_id: UUID,
    payload: PersonaCreate,
    db: Session = Depends(get_db),
) -> StoryPersonaRead:
    chat = _chat_or_404(db, chat_id)
    record = db.scalar(select(StoryPersonaRecord).where(StoryPersonaRecord.chat_id == str(chat_id)))
    if not record:
        now = datetime.now(UTC)
        record = StoryPersonaRecord(
            id=str(uuid4()), chat_id=str(chat_id), source_template_id=None,
            created_at=now, updated_at=now, **_persona_values(payload),
        )
        db.add(record)
    else:
        _apply_persona(record, payload)
        record.updated_at = datetime.now(UTC)
    chat.updated_at = record.updated_at
    db.commit()
    db.refresh(record)
    return story_persona_read(record)

@router.delete(
    "/chats/{chat_id}/persona",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["story-bindings"],
)
def delete_story_persona(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    chat = _chat_or_404(db, chat_id)
    record = db.scalar(
        select(StoryPersonaRecord).where(StoryPersonaRecord.chat_id == str(chat_id))
    )
    if not record:
        raise HTTPException(status_code=404, detail="当前故事没有主控人物")
    db.delete(record)
    chat.updated_at = datetime.now(UTC)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get(
    "/chats/{chat_id}/characters",
    response_model=list[StoryCharacterRead],
    tags=["story-bindings"],
)
def list_story_characters(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> list[StoryCharacterRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(StoryCharacterRecord)
        .where(StoryCharacterRecord.chat_id == str(chat_id))
        .order_by(StoryCharacterRecord.created_at)
    ).all()
    return [story_character_read(record) for record in records]

@router.post(
    "/chats/{chat_id}/characters/from-template/{template_id}",
    response_model=StoryCharacterRead,
    status_code=status.HTTP_201_CREATED,
    tags=["story-bindings"],
)
def attach_character_template(
    chat_id: UUID,
    template_id: UUID,
    db: Session = Depends(get_db),
) -> StoryCharacterRead:
    chat = _chat_or_404(db, chat_id)
    template = db.get(CharacterTemplateRecord, str(template_id))
    if not template:
        raise HTTPException(status_code=404, detail="角色模板不存在")
    now = datetime.now(UTC)
    record = _copy_character_to_story(template, str(chat_id), now)
    _attach_linked_world_books(db, str(chat_id), template.world_book_ids_json, now)
    chat.updated_at = now
    db.add(record)
    db.commit()
    db.refresh(record)
    return story_character_read(record)

@router.put(
    "/chats/{chat_id}/characters/{character_id}",
    response_model=StoryCharacterRead,
    tags=["story-bindings"],
)
def update_story_character(
    chat_id: UUID,
    character_id: UUID,
    payload: CharacterTemplateCreate,
    db: Session = Depends(get_db),
) -> StoryCharacterRead:
    chat = _chat_or_404(db, chat_id)
    record = _story_character_or_404(db, chat_id, character_id)
    _apply_character(record, payload)
    record.updated_at = datetime.now(UTC)
    chat.updated_at = record.updated_at
    db.commit()
    db.refresh(record)
    return story_character_read(record)

@router.delete(
    "/chats/{chat_id}/characters/{character_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["story-bindings"],
)
def delete_story_character(
    chat_id: UUID,
    character_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    _chat_or_404(db, chat_id)
    db.delete(_story_character_or_404(db, chat_id, character_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get(
    "/chats/{chat_id}/world-books",
    response_model=list[StoryWorldBookRead],
    tags=["story-bindings"],
)
def list_story_world_books(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> list[StoryWorldBookRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(StoryWorldBookRecord)
        .where(StoryWorldBookRecord.chat_id == str(chat_id))
        .order_by(StoryWorldBookRecord.priority.desc(), StoryWorldBookRecord.updated_at.desc())
    ).all()
    return [story_world_book_read(record) for record in records]

@router.post(
    "/chats/{chat_id}/world-books/batch",
    response_model=WorldBookBatchResult,
    tags=["story-bindings"],
)
def batch_story_world_books(
    chat_id: UUID,
    payload: WorldBookBatchRequest,
    db: Session = Depends(get_db),
) -> WorldBookBatchResult:
    chat = _chat_or_404(db, chat_id)
    ids = list(dict.fromkeys(str(item) for item in payload.ids))
    records = list(
        db.scalars(
            select(StoryWorldBookRecord).where(
                StoryWorldBookRecord.chat_id == str(chat_id),
                StoryWorldBookRecord.id.in_(ids),
            )
        ).all()
    )
    if len(records) != len(ids):
        raise HTTPException(status_code=404, detail="部分故事世界书不存在，请刷新后重试")

    now = datetime.now(UTC)
    if payload.action == "delete":
        for record in records:
            db.delete(record)
    else:
        enabled = payload.action == "enable"
        for record in records:
            record.enabled = enabled
            record.updated_at = now
    chat.updated_at = now
    db.commit()
    return WorldBookBatchResult(affected=len(records))

@router.post(
    "/chats/{chat_id}/world-books/from-template/{template_id}",
    response_model=StoryWorldBookRead,
    status_code=status.HTTP_201_CREATED,
    tags=["story-bindings"],
)
def attach_world_book_template(
    chat_id: UUID,
    template_id: UUID,
    db: Session = Depends(get_db),
) -> StoryWorldBookRead:
    chat = _chat_or_404(db, chat_id)
    template = db.get(WorldBookTemplateRecord, str(template_id))
    if not template:
        raise HTTPException(status_code=404, detail="世界书模板不存在")
    now = datetime.now(UTC)
    record = _copy_world_to_story(template, str(chat_id), now)
    chat.updated_at = now
    db.add(record)
    db.commit()
    db.refresh(record)
    return story_world_book_read(record)

@router.put(
    "/chats/{chat_id}/world-books/{entry_id}",
    response_model=StoryWorldBookRead,
    tags=["story-bindings"],
)
def update_story_world_book(
    chat_id: UUID,
    entry_id: UUID,
    payload: WorldBookEntryUpdate,
    db: Session = Depends(get_db),
) -> StoryWorldBookRead:
    chat = _chat_or_404(db, chat_id)
    record = _story_world_or_404(db, chat_id, entry_id)
    _apply_world(record, payload)
    record.updated_at = datetime.now(UTC)
    chat.updated_at = record.updated_at
    db.commit()
    db.refresh(record)
    return story_world_book_read(record)

@router.delete(
    "/chats/{chat_id}/world-books/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["story-bindings"],
)
def delete_story_world_book(
    chat_id: UUID,
    entry_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    _chat_or_404(db, chat_id)
    db.delete(_story_world_or_404(db, chat_id, entry_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get(
    "/chats/{chat_id}/character",
    response_model=CharacterProfileRead,
    tags=["character"],
)
def get_character(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> CharacterProfileRead:
    """读取角色档案；尚未创建时返回一个空档案。"""
    _chat_or_404(db, chat_id)
    record = db.scalar(
        select(CharacterProfileRecord).where(
            CharacterProfileRecord.chat_id == str(chat_id)
        )
    )
    if record:
        return character_read(record)
    return CharacterProfileRead(chat_id=chat_id)

@router.put(
    "/chats/{chat_id}/character",
    response_model=CharacterProfileRead,
    tags=["character"],
)
def update_character(
    chat_id: UUID,
    payload: CharacterProfileUpdate,
    db: Session = Depends(get_db),
) -> CharacterProfileRead:
    """创建或覆盖当前聊天存档的角色档案。"""
    chat = _chat_or_404(db, chat_id)
    record = db.scalar(
        select(CharacterProfileRecord).where(
            CharacterProfileRecord.chat_id == str(chat_id)
        )
    )
    now = datetime.now(UTC)
    if not record:
        record = CharacterProfileRecord(
            id=str(uuid4()),
            chat_id=str(chat_id),
            updated_at=now,
        )
        db.add(record)
    record.name = payload.name.strip()
    record.identity = payload.identity.strip()
    record.personality = payload.personality.strip()
    record.speaking_style = payload.speaking_style.strip()
    record.scenario = payload.scenario.strip()
    record.updated_at = now
    chat.updated_at = now
    db.commit()
    db.refresh(record)
    return character_read(record)

@router.get(
    "/chats/{chat_id}/world-book",
    response_model=list[WorldBookEntryRead],
    tags=["world-book"],
)
def list_world_book(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> list[WorldBookEntryRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(WorldBookEntryRecord)
        .where(WorldBookEntryRecord.chat_id == str(chat_id))
        .order_by(
            WorldBookEntryRecord.priority.desc(),
            WorldBookEntryRecord.updated_at.desc(),
        )
    ).all()
    return [world_book_read(record) for record in records]

@router.post(
    "/chats/{chat_id}/world-book",
    response_model=WorldBookEntryRead,
    status_code=status.HTTP_201_CREATED,
    tags=["world-book"],
)
def create_world_book_entry(
    chat_id: UUID,
    payload: WorldBookEntryCreate,
    db: Session = Depends(get_db),
) -> WorldBookEntryRead:
    chat = _chat_or_404(db, chat_id)
    now = datetime.now(UTC)
    record = WorldBookEntryRecord(
        id=str(uuid4()),
        chat_id=str(chat_id),
        created_at=now,
        updated_at=now,
        **_world_values(payload),
    )
    chat.updated_at = now
    db.add(record)
    db.commit()
    db.refresh(record)
    return world_book_read(record)

@router.put(
    "/chats/{chat_id}/world-book/{entry_id}",
    response_model=WorldBookEntryRead,
    tags=["world-book"],
)
def update_world_book_entry(
    chat_id: UUID,
    entry_id: UUID,
    payload: WorldBookEntryUpdate,
    db: Session = Depends(get_db),
) -> WorldBookEntryRead:
    chat = _chat_or_404(db, chat_id)
    record = _world_entry_or_404(db, chat_id, entry_id)
    now = datetime.now(UTC)
    _apply_world(record, payload)
    record.updated_at = now
    chat.updated_at = now
    db.commit()
    db.refresh(record)
    return world_book_read(record)

@router.delete(
    "/chats/{chat_id}/world-book/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["world-book"],
)
def delete_world_book_entry(
    chat_id: UUID,
    entry_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    _chat_or_404(db, chat_id)
    record = _world_entry_or_404(db, chat_id, entry_id)
    db.delete(record)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get(
    "/chats/{chat_id}/messages",
    response_model=list[MessageRead],
    tags=["messages"],
)
def list_messages(chat_id: UUID, db: Session = Depends(get_db)) -> list[MessageRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(MessageRecord)
        .where(MessageRecord.chat_id == str(chat_id))
        .order_by(MessageRecord.created_at)
    ).all()
    return [message_read(record) for record in records]

@router.put(
    "/chats/{chat_id}/messages/{message_id}",
    response_model=MessageRead,
    tags=["messages"],
)
def update_message(
    chat_id: UUID,
    message_id: UUID,
    payload: MessageUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageRead:
    """改写正文；相关记忆不会被静默修改，而会由原文指纹标记为失效。"""
    _chat_or_404(db, chat_id)
    record = db.scalar(
        select(MessageRecord).where(
            MessageRecord.id == str(message_id),
            MessageRecord.chat_id == str(chat_id),
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="消息不存在")
    affected_leaves = db.scalars(
        select(NarrativeLeafRecord).where(
            NarrativeLeafRecord.chat_id == str(chat_id),
            (
                (NarrativeLeafRecord.user_message_id == str(message_id))
                | (NarrativeLeafRecord.assistant_message_id == str(message_id))
            ),
        )
    ).all()
    affected_sources = {
        source_id
        for leaf in affected_leaves
        for source_id in (leaf.user_message_id, leaf.assistant_message_id)
    }
    if affected_sources:
        approved_changes = db.scalars(
            select(StateChangeRecord).where(
                StateChangeRecord.chat_id == str(chat_id),
                StateChangeRecord.source_message_id.in_(affected_sources),
                StateChangeRecord.status == ProposalStatus.APPROVED.value,
            )
        ).all()
        for change in approved_changes:
            change.status = ProposalStatus.REVERTED.value
            if not change.reason.startswith("源剧情已改写"):
                change.reason = f"源剧情已改写，原修改已撤销：{change.reason}"
    record.content = payload.content.strip()
    selected_variant = db.scalar(
        select(MessageVariantRecord).where(
            MessageVariantRecord.message_id == record.id,
            MessageVariantRecord.selected.is_(True),
        )
    )
    if selected_variant:
        selected_variant.content = record.content
    db.commit()
    runtime: AgentRuntime = request.app.state.runtime
    runtime.state_service.rebuild_entries(db, str(chat_id))
    runtime.graph_service.rebuild_projections(db, str(chat_id))
    db.refresh(record)
    return message_read(record)

@router.delete(
    "/chats/{chat_id}/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["messages"],
)
def delete_message_and_following(
    chat_id: UUID,
    message_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """删除选中消息以及它之后的剧情，避免留下断裂的上下文。"""
    chat = _chat_or_404(db, chat_id)
    record = _message_or_404(db, chat_id, message_id)
    doomed = list(
        db.scalars(
            select(MessageRecord).where(
                MessageRecord.chat_id == chat.id,
                MessageRecord.created_at >= record.created_at,
            )
        ).all()
    )
    source_ids = [item.id for item in doomed]
    if source_ids:
        db.execute(
            delete(StateChangeRecord).where(
                StateChangeRecord.chat_id == chat.id,
                StateChangeRecord.source_message_id.in_(source_ids),
            )
        )
        db.execute(
            delete(RoleplayGraphEventRecord).where(
                RoleplayGraphEventRecord.chat_id == chat.id,
                RoleplayGraphEventRecord.source_message_id.in_(source_ids),
            )
        )
        db.execute(
            delete(MemoryRecord).where(
                MemoryRecord.chat_id == chat.id,
                MemoryRecord.source_message_id.in_(source_ids),
            )
        )
        db.execute(
            delete(TimelineAnchorRecord).where(
                TimelineAnchorRecord.chat_id == chat.id,
                TimelineAnchorRecord.source_message_id.in_(source_ids),
            )
        )
        db.execute(delete(MessageRecord).where(MessageRecord.id.in_(source_ids)))
    previous = db.scalar(
        select(MessageRecord)
        .where(MessageRecord.chat_id == chat.id)
        .order_by(MessageRecord.created_at.desc())
    )
    chat.updated_at = previous.created_at if previous else chat.created_at
    db.commit()
    runtime: AgentRuntime = request.app.state.runtime
    runtime.state_service.rebuild_entries(db, chat.id)
    runtime.graph_service.rebuild_projections(db, chat.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get(
    "/chats/{chat_id}/message-variants",
    response_model=list[MessageVariantRead],
    tags=["messages"],
)
def list_message_variants(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> list[MessageVariantRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(MessageVariantRecord)
        .where(MessageVariantRecord.chat_id == str(chat_id))
        .order_by(MessageVariantRecord.message_id, MessageVariantRecord.position)
    ).all()
    return [_message_variant_read(item) for item in records]

@router.post(
    "/chats/{chat_id}/messages/{message_id}/regenerate",
    response_model=MessageVariantRead,
    tags=["messages"],
)
async def regenerate_message(
    chat_id: UUID,
    message_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageVariantRead:
    chat = _chat_or_404(db, chat_id)
    message = _message_or_404(db, chat_id, message_id)
    if message.role != MessageRole.ASSISTANT.value:
        raise HTTPException(status_code=409, detail="只能重新生成助手回复")
    _ensure_variant_target_is_latest(db, chat.id, message)
    user_message = db.scalar(
        select(MessageRecord)
        .where(
            MessageRecord.chat_id == chat.id,
            MessageRecord.role == MessageRole.USER.value,
            MessageRecord.created_at < message.created_at,
        )
        .order_by(MessageRecord.created_at.desc())
    )
    if not user_message:
        raise HTTPException(status_code=409, detail="没有找到这条回复对应的用户消息")
    variants = _ensure_message_variants(db, message)
    runtime: AgentRuntime = request.app.state.runtime
    try:
        content = await runtime.generate_candidate(db, chat, user_message)
    except ModelProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    previous = next((item for item in variants if item.selected), None)
    for item in variants:
        item.selected = False
    variant = MessageVariantRecord(
        id=str(uuid4()),
        chat_id=chat.id,
        message_id=message.id,
        position=len(variants),
        content=content,
        state_changes_json="[]",
        graph_events_json="[]",
        selected=True,
        created_at=datetime.now(UTC),
    )
    db.add(variant)
    message.content = content
    chat.updated_at = variant.created_at
    db.commit()
    runtime.state_service.rebuild_entries(db, chat.id)
    runtime.graph_service.rebuild_projections(db, chat.id)
    try:
        await runtime.process_candidate(db, chat, user_message, message)
    except ModelProviderError as exc:
        variant.selected = False
        if previous is not None:
            previous.selected = True
            message.content = previous.content
        db.commit()
        runtime.state_service.rebuild_entries(db, chat.id)
        runtime.graph_service.rebuild_projections(db, chat.id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    runtime.state_service.rebuild_entries(db, chat.id)
    runtime.graph_service.rebuild_projections(db, chat.id)
    db.refresh(variant)
    return _message_variant_read(variant)

@router.post(
    "/chats/{chat_id}/messages/{message_id}/variants/{variant_id}/select",
    response_model=MessageRead,
    tags=["messages"],
)
async def select_message_variant(
    chat_id: UUID,
    message_id: UUID,
    variant_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageRead:
    chat = _chat_or_404(db, chat_id)
    message = _message_or_404(db, chat_id, message_id)
    _ensure_variant_target_is_latest(db, chat.id, message)
    variants = _ensure_message_variants(db, message)
    previous = next((item for item in variants if item.selected), None)
    selected = next((item for item in variants if item.id == str(variant_id)), None)
    if not selected:
        raise HTTPException(status_code=404, detail="候选回复不存在")
    for item in variants:
        item.selected = item.id == selected.id
    message.content = selected.content
    chat.updated_at = datetime.now(UTC)
    db.commit()
    runtime: AgentRuntime = request.app.state.runtime
    runtime.state_service.rebuild_entries(db, chat.id)
    runtime.graph_service.rebuild_projections(db, chat.id)
    has_leaf = db.scalar(select(NarrativeLeafRecord.id).where(
        NarrativeLeafRecord.variant_id == selected.id
    ))
    has_delta = db.scalar(select(NarrativeDeltaRecord.id).where(
        NarrativeDeltaRecord.variant_id == selected.id
    ))
    user_message = _preceding_user_message(db, message)
    if user_message and (has_leaf is None or has_delta is None):
        try:
            await runtime.process_candidate(db, chat, user_message, message)
        except ModelProviderError as exc:
            selected.selected = False
            if previous is not None:
                previous.selected = True
                message.content = previous.content
            db.commit()
            runtime.state_service.rebuild_entries(db, chat.id)
            runtime.graph_service.rebuild_projections(db, chat.id)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    runtime.state_service.rebuild_entries(db, chat.id)
    runtime.graph_service.rebuild_projections(db, chat.id)
    db.refresh(message)
    return message_read(message)


def _ensure_variant_target_is_latest(
    db: Session, chat_id: str, message: MessageRecord
) -> None:
    later = db.scalar(select(MessageRecord.id).where(
        MessageRecord.chat_id == chat_id,
        MessageRecord.created_at > message.created_at,
    ).limit(1))
    if later is not None:
        raise HTTPException(
            status_code=409,
            detail="已有后续剧情时不能切换较早回复；请从该楼层创建故事分支。",
        )

@router.get(
    "/chats/{chat_id}/bookmarks",
    response_model=list[MessageBookmarkRead],
    tags=["messages"],
)
def list_message_bookmarks(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> list[MessageBookmarkRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(MessageBookmarkRecord).where(
            MessageBookmarkRecord.chat_id == str(chat_id)
        )
    ).all()
    return [MessageBookmarkRead(message_id=UUID(item.message_id), bookmarked=True) for item in records]

@router.post(
    "/chats/{chat_id}/messages/{message_id}/bookmark",
    response_model=MessageBookmarkRead,
    tags=["messages"],
)
def toggle_message_bookmark(
    chat_id: UUID,
    message_id: UUID,
    db: Session = Depends(get_db),
) -> MessageBookmarkRead:
    _chat_or_404(db, chat_id)
    message = _message_or_404(db, chat_id, message_id)
    existing = db.get(MessageBookmarkRecord, message.id)
    if existing:
        db.delete(existing)
        bookmarked = False
    else:
        db.add(
            MessageBookmarkRecord(
                message_id=message.id,
                chat_id=message.chat_id,
                created_at=datetime.now(UTC),
            )
        )
        bookmarked = True
    db.commit()
    return MessageBookmarkRead(message_id=message_id, bookmarked=bookmarked)

@router.post(
    "/chats/{chat_id}/branches",
    response_model=ChatRead,
    status_code=status.HTTP_201_CREATED,
    tags=["chats"],
)
def create_story_branch(
    chat_id: UUID,
    payload: StoryBranchCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> ChatRead:
    chat = _chat_or_404(db, chat_id)
    message = _message_or_404(db, chat_id, payload.message_id)
    runtime: AgentRuntime = request.app.state.runtime
    branch = _copy_story_branch(db, chat, message, payload.title, runtime)
    return chat_read(branch)

@router.get(
    "/chats/{chat_id}/checkpoints",
    response_model=list[CheckpointRead],
    tags=["chats"],
)
def list_checkpoints(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> list[CheckpointRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(StoryCheckpointRecord)
        .where(StoryCheckpointRecord.chat_id == str(chat_id))
        .order_by(StoryCheckpointRecord.created_at.desc())
    ).all()
    return [_checkpoint_read(item) for item in records]

@router.post(
    "/chats/{chat_id}/checkpoints",
    response_model=CheckpointRead,
    status_code=status.HTTP_201_CREATED,
    tags=["chats"],
)
def create_checkpoint(
    chat_id: UUID,
    payload: CheckpointCreate,
    db: Session = Depends(get_db),
) -> CheckpointRead:
    _chat_or_404(db, chat_id)
    _message_or_404(db, chat_id, payload.message_id)
    record = StoryCheckpointRecord(
        id=str(uuid4()),
        chat_id=str(chat_id),
        message_id=str(payload.message_id),
        name=payload.name.strip(),
        created_at=datetime.now(UTC),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _checkpoint_read(record)

@router.post(
    "/chats/{chat_id}/checkpoints/{checkpoint_id}/restore",
    response_model=ChatRead,
    status_code=status.HTTP_201_CREATED,
    tags=["chats"],
)
def restore_checkpoint_as_branch(
    chat_id: UUID,
    checkpoint_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> ChatRead:
    chat = _chat_or_404(db, chat_id)
    checkpoint = db.scalar(
        select(StoryCheckpointRecord).where(
            StoryCheckpointRecord.id == str(checkpoint_id),
            StoryCheckpointRecord.chat_id == chat.id,
        )
    )
    if not checkpoint:
        raise HTTPException(status_code=404, detail="检查点不存在")
    message = _message_or_404(db, chat_id, UUID(checkpoint.message_id))
    runtime: AgentRuntime = request.app.state.runtime
    branch = _copy_story_branch(
        db, chat, message, f"{chat.title} · {checkpoint.name}", runtime
    )
    return chat_read(branch)

@router.post(
    "/chats/{chat_id}/messages",
    response_model=AgentTurnRead,
    tags=["messages"],
)
async def send_message(
    chat_id: UUID,
    payload: MessageSend,
    request: Request,
    db: Session = Depends(get_db),
) -> AgentTurnRead:
    """保存用户消息，并运行一次完整 Agent 对话。"""
    runtime: AgentRuntime = request.app.state.runtime
    _require_connected_model(runtime)
    chat = _chat_or_404(db, chat_id)
    user_message = MessageRecord(
        id=str(uuid4()),
        chat_id=chat.id,
        role=MessageRole.USER.value,
        content=payload.content,
        created_at=datetime.now(UTC),
    )
    chat.updated_at = user_message.created_at
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    result = await runtime.run_turn(db, chat, user_message, context_debug=payload.context_debug)
    return _agent_turn_read(runtime, user_message, result)

@router.post(
    "/chats/{chat_id}/turns/stream",
    tags=["messages"],
)
async def stream_message(
    chat_id: UUID,
    payload: MessageSend,
    request: Request,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """通过 NDJSON 逐块返回模型正文，并在完成后发送整轮 Agent 结果。"""
    chat = _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    _require_connected_model(runtime)
    events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def on_token(token: str) -> None:
        await events.put({"type": "chunk", "content": token})

    async def on_progress(phase: str) -> None:
        await events.put({"type": "phase", "phase": phase})

    async def run() -> None:
        try:
            user_message = MessageRecord(
                id=str(uuid4()),
                chat_id=chat.id,
                role=MessageRole.USER.value,
                content=payload.content,
                created_at=datetime.now(UTC),
            )
            chat.updated_at = user_message.created_at
            db.add(user_message)
            db.commit()
            db.refresh(user_message)
            await events.put(
                {
                    "type": "user",
                    "message": message_read(user_message).model_dump(mode="json"),
                }
            )
            result = await runtime.run_turn(
                db,
                chat,
                user_message,
                on_token=on_token,
                on_progress=on_progress,
                context_debug=payload.context_debug,
            )
            turn = _agent_turn_read(runtime, user_message, result)
            await events.put(
                {"type": "done", "turn": turn.model_dump(mode="json")}
            )
        except asyncio.CancelledError:
            db.rollback()
            raise
        except Exception as exc:  # 流已经开始后只能通过事件传递错误。
            db.rollback()
            await events.put({"type": "error", "detail": str(exc)})
        finally:
            await events.put(None)

    async def body() -> AsyncIterator[str]:
        task = asyncio.create_task(run())
        try:
            while True:
                event = await events.get()
                if event is None:
                    break
                yield json_dumps(event) + "\n"
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(body(), media_type="application/x-ndjson")


def _require_connected_model(runtime: AgentRuntime) -> None:
    if runtime.model.mode == "unconfigured":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="尚未连接模型 API，请先在设置中完成配置。",
        )
