"""Saraswati Agent 的 HTTP API 路由。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.config import Settings, save_local_settings
from backend.llm import ModelProviderError, build_model_client
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
    HealthRead,
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
    RuntimeInfo,
    SettingsRead,
    SettingsTestResult,
    SettingsUpdate,
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
from backend.utils import json_dumps, json_loads


router = APIRouter()

# 系统级路由负责健康检查、运行状态和本机设置管理。


@router.get("/health", response_model=HealthRead, tags=["system"])
def health_check() -> HealthRead:
    """确认后端进程已经启动。"""
    return HealthRead()


@router.get("/runtime", response_model=RuntimeInfo, tags=["system"])
def runtime_info(request: Request) -> RuntimeInfo:
    """返回当前模型模式和 Agent 运行参数，不暴露 API Key。"""
    settings = request.app.state.settings
    model = request.app.state.model
    return RuntimeInfo(
        provider_mode=model.mode,
        model=model.model_name,
        embedding_model=settings.embedding_model,
        max_agent_steps=settings.max_agent_steps,
    )


@router.get("/settings", response_model=SettingsRead, tags=["system"])
def read_settings(request: Request) -> SettingsRead:
    """读取设置中心需要的数据，同时隐藏 API Key 明文。"""
    return _settings_read(request.app.state.settings)


@router.put("/settings", response_model=SettingsRead, tags=["system"])
async def update_settings(payload: SettingsUpdate, request: Request) -> SettingsRead:
    """保存设置并立即重建模型客户端和 Agent Runtime。"""
    current: Settings = request.app.state.settings
    api_key = current.llm_api_key
    if payload.clear_api_key:
        api_key = None
    elif payload.api_key and payload.api_key.strip():
        api_key = payload.api_key.strip()
    rerank_api_key = current.rerank_api_key
    if payload.clear_rerank_api_key:
        rerank_api_key = None
    elif payload.rerank_api_key and payload.rerank_api_key.strip():
        rerank_api_key = payload.rerank_api_key.strip()

    weights = (
        payload.vector_weight
        + payload.keyword_weight
        + payload.importance_weight
        + payload.recency_weight
    )
    if weights <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="RAG 权重之和必须大于 0。",
        )

    updated = replace(
        current,
        llm_base_url=_clean_optional(payload.llm_base_url),
        llm_api_key=api_key,
        llm_model=_clean_optional(payload.llm_model),
        embedding_model=_clean_optional(payload.embedding_model),
        temperature=payload.temperature,
        top_p=payload.top_p,
        max_output_tokens=payload.max_output_tokens,
        presence_penalty=payload.presence_penalty,
        frequency_penalty=payload.frequency_penalty,
        request_timeout=payload.request_timeout,
        max_agent_steps=payload.max_agent_steps,
        recent_message_limit=payload.recent_message_limit,
        rag_limit=payload.rag_limit,
        vector_weight=payload.vector_weight,
        keyword_weight=payload.keyword_weight,
        importance_weight=payload.importance_weight,
        recency_weight=payload.recency_weight,
        auto_summary_enabled=payload.auto_summary_enabled,
        summary_detail_mode=payload.summary_detail_mode,
        chapter_summary_size=payload.chapter_summary_size,
        arc_summary_size=payload.arc_summary_size,
        rerank_base_url=_clean_optional(payload.rerank_base_url),
        rerank_api_key=rerank_api_key,
        rerank_model=_clean_optional(payload.rerank_model),
        rerank_candidates=payload.rerank_candidates,
        context_window_tokens=payload.context_window_tokens,
    )
    model = build_model_client(updated)
    runtime = AgentRuntime(updated, model)
    await runtime.startup()
    save_local_settings(updated)
    previous_runtime: AgentRuntime = request.app.state.runtime
    request.app.state.settings = updated
    request.app.state.model = model
    request.app.state.runtime = runtime
    await previous_runtime.shutdown()
    return _settings_read(updated)


@router.post("/settings/test", response_model=SettingsTestResult, tags=["system"])
async def test_settings(request: Request) -> SettingsTestResult:
    """发送一条最小请求，确认当前模型配置能够正常响应。"""
    model = request.app.state.model
    if model.mode == "demo":
        return SettingsTestResult(
            ok=True,
            provider_mode=model.mode,
            model=model.model_name,
            message="当前为演示模式；填写完整的地址、密钥和模型名后可测试真实连接。",
        )
    try:
        reply = await model.complete(
            [
                {"role": "system", "content": "只回复 OK。"},
                {"role": "user", "content": "连接测试"},
            ],
            None,
        )
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型连接失败：{exc}",
        ) from exc
    return SettingsTestResult(
        ok=True,
        provider_mode=model.mode,
        model=model.model_name,
        message=f"连接成功，模型返回：{(reply.content or '空响应')[:100]}",
    )


@router.get(
    "/character-templates",
    response_model=list[CharacterTemplateRead],
    tags=["libraries"],
)
def list_character_templates(db: Session = Depends(get_db)) -> list[CharacterTemplateRead]:
    records = db.scalars(
        select(CharacterTemplateRecord).order_by(CharacterTemplateRecord.updated_at.desc())
    ).all()
    return [character_template_read(record) for record in records]


@router.post(
    "/character-templates",
    response_model=CharacterTemplateRead,
    status_code=status.HTTP_201_CREATED,
    tags=["libraries"],
)
def create_character_template(
    payload: CharacterTemplateCreate,
    db: Session = Depends(get_db),
) -> CharacterTemplateRead:
    now = datetime.now(UTC)
    record = CharacterTemplateRecord(
        id=str(uuid4()),
        created_at=now,
        updated_at=now,
        **_character_values(payload),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return character_template_read(record)


@router.put(
    "/character-templates/{template_id}",
    response_model=CharacterTemplateRead,
    tags=["libraries"],
)
def update_character_template(
    template_id: UUID,
    payload: CharacterTemplateCreate,
    db: Session = Depends(get_db),
) -> CharacterTemplateRead:
    record = db.get(CharacterTemplateRecord, str(template_id))
    if not record:
        raise HTTPException(status_code=404, detail="角色模板不存在")
    _apply_character(record, payload)
    record.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(record)
    return character_template_read(record)


@router.delete(
    "/character-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["libraries"],
)
def delete_character_template(
    template_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    record = db.get(CharacterTemplateRecord, str(template_id))
    if not record:
        raise HTTPException(status_code=404, detail="角色模板不存在")
    db.delete(record)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/world-book-templates",
    response_model=list[WorldBookTemplateRead],
    tags=["libraries"],
)
def list_world_book_templates(db: Session = Depends(get_db)) -> list[WorldBookTemplateRead]:
    records = db.scalars(
        select(WorldBookTemplateRecord).order_by(
            WorldBookTemplateRecord.priority.desc(),
            WorldBookTemplateRecord.updated_at.desc(),
        )
    ).all()
    return [world_book_template_read(record) for record in records]


@router.post(
    "/world-book-templates",
    response_model=WorldBookTemplateRead,
    status_code=status.HTTP_201_CREATED,
    tags=["libraries"],
)
def create_world_book_template(
    payload: WorldBookEntryCreate,
    db: Session = Depends(get_db),
) -> WorldBookTemplateRead:
    now = datetime.now(UTC)
    record = WorldBookTemplateRecord(
        id=str(uuid4()),
        created_at=now,
        updated_at=now,
        **_world_values(payload),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return world_book_template_read(record)


@router.put(
    "/world-book-templates/{template_id}",
    response_model=WorldBookTemplateRead,
    tags=["libraries"],
)
def update_world_book_template(
    template_id: UUID,
    payload: WorldBookEntryUpdate,
    db: Session = Depends(get_db),
) -> WorldBookTemplateRead:
    record = db.get(WorldBookTemplateRecord, str(template_id))
    if not record:
        raise HTTPException(status_code=404, detail="世界书模板不存在")
    _apply_world(record, payload)
    record.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(record)
    return world_book_template_read(record)


@router.delete(
    "/world-book-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["libraries"],
)
def delete_world_book_template(
    template_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    record = db.get(WorldBookTemplateRecord, str(template_id))
    if not record:
        raise HTTPException(status_code=404, detail="世界书模板不存在")
    db.delete(record)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@router.post(
    "/character-templates/{template_id}/duplicate",
    response_model=CharacterTemplateRead,
    status_code=status.HTTP_201_CREATED,
    tags=["libraries"],
)
def duplicate_character_template(
    template_id: UUID,
    db: Session = Depends(get_db),
) -> CharacterTemplateRead:
    source = db.get(CharacterTemplateRecord, str(template_id))
    if not source:
        raise HTTPException(status_code=404, detail="角色模板不存在")
    now = datetime.now(UTC)
    record = CharacterTemplateRecord(
        id=str(uuid4()), name=f"{source.name} 副本",
        identity=source.identity, personality=source.personality,
        speaking_style=source.speaking_style, scenario=source.scenario,
        avatar=source.avatar, appearance=source.appearance,
        first_message=source.first_message,
        alternate_greetings_json=source.alternate_greetings_json,
        example_dialogue=source.example_dialogue, tags_json=source.tags_json,
        creator_notes=source.creator_notes, system_prompt=source.system_prompt,
        favorite=False, world_book_ids_json=source.world_book_ids_json,
        created_at=now, updated_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return character_template_read(record)


@router.get(
    "/persona-templates",
    response_model=list[PersonaRead],
    tags=["libraries"],
)
def list_persona_templates(db: Session = Depends(get_db)) -> list[PersonaRead]:
    records = db.scalars(
        select(PersonaTemplateRecord).order_by(PersonaTemplateRecord.updated_at.desc())
    ).all()
    return [persona_template_read(item) for item in records]


@router.post(
    "/persona-templates",
    response_model=PersonaRead,
    status_code=status.HTTP_201_CREATED,
    tags=["libraries"],
)
def create_persona_template(
    payload: PersonaCreate,
    db: Session = Depends(get_db),
) -> PersonaRead:
    now = datetime.now(UTC)
    record = PersonaTemplateRecord(
        id=str(uuid4()),
        created_at=now,
        updated_at=now,
        **_persona_values(payload),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return persona_template_read(record)


@router.put(
    "/persona-templates/{persona_id}",
    response_model=PersonaRead,
    tags=["libraries"],
)
def update_persona_template(
    persona_id: UUID,
    payload: PersonaCreate,
    db: Session = Depends(get_db),
) -> PersonaRead:
    record = db.get(PersonaTemplateRecord, str(persona_id))
    if not record:
        raise HTTPException(status_code=404, detail="主控人物不存在")
    _apply_persona(record, payload)
    record.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(record)
    return persona_template_read(record)


@router.delete(
    "/persona-templates/{persona_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["libraries"],
)
def delete_persona_template(
    persona_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    record = db.get(PersonaTemplateRecord, str(persona_id))
    if not record:
        raise HTTPException(status_code=404, detail="主控人物不存在")
    db.delete(record)
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
    affected_sources = {leaf.user_message_id for leaf in affected_leaves}
    if affected_sources:
        approved_changes = db.scalars(
            select(StateChangeRecord).where(
                StateChangeRecord.chat_id == str(chat_id),
                StateChangeRecord.source_message_id.in_(affected_sources),
                StateChangeRecord.status == ProposalStatus.APPROVED.value,
            )
        ).all()
        for change in approved_changes:
            change.status = ProposalStatus.PENDING.value
            change.resolved_at = None
            if not change.reason.startswith("源剧情已改写"):
                change.reason = f"源剧情已改写，请重新确认：{change.reason}"
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
    _apply_variant_effects(db, message, variant)
    db.commit()
    runtime.state_service.rebuild_entries(db, chat.id)
    runtime.graph_service.rebuild_projections(db, chat.id)
    db.refresh(variant)
    return _message_variant_read(variant)


@router.post(
    "/chats/{chat_id}/messages/{message_id}/variants/{variant_id}/select",
    response_model=MessageRead,
    tags=["messages"],
)
def select_message_variant(
    chat_id: UUID,
    message_id: UUID,
    variant_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageRead:
    chat = _chat_or_404(db, chat_id)
    message = _message_or_404(db, chat_id, message_id)
    variants = _ensure_message_variants(db, message)
    selected = next((item for item in variants if item.id == str(variant_id)), None)
    if not selected:
        raise HTTPException(status_code=404, detail="候选回复不存在")
    for item in variants:
        item.selected = item.id == selected.id
    message.content = selected.content
    chat.updated_at = datetime.now(UTC)
    _apply_variant_effects(db, message, selected)
    db.commit()
    runtime: AgentRuntime = request.app.state.runtime
    runtime.state_service.rebuild_entries(db, chat.id)
    runtime.graph_service.rebuild_projections(db, chat.id)
    db.refresh(message)
    return message_read(message)


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


@router.get(
    "/chats/{chat_id}/narrative-deltas",
    response_model=list[NarrativeDeltaRead],
    tags=["memory-hub"],
)
def list_narrative_deltas(
    chat_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> list[NarrativeDeltaRead]:
    """查看每轮结构化剧情变化及其原文指纹是否仍然有效。"""
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    return [
        NarrativeDeltaRead(
            id=UUID(record.id),
            chat_id=UUID(record.chat_id),
            user_message_id=UUID(record.user_message_id),
            assistant_message_id=UUID(record.assistant_message_id),
            payload=json_loads(record.payload_json),
            valid=valid,
            created_at=record.created_at,
        )
        for record, valid in runtime.narrative_delta_service.list_with_validity(
            db, str(chat_id)
        )
    ]


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

    runtime: AgentRuntime = request.app.state.runtime
    result = await runtime.run_turn(db, chat, user_message)
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
    events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def on_token(token: str) -> None:
        await events.put({"type": "chunk", "content": token})

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
            result = await runtime.run_turn(db, chat, user_message, on_token=on_token)
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


@router.get(
    "/chats/{chat_id}/memories",
    response_model=list[MemoryRead],
    tags=["memory"],
)
def list_memories(chat_id: UUID, db: Session = Depends(get_db)) -> list[MemoryRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(MemoryRecord)
        .where(MemoryRecord.chat_id == str(chat_id))
        .order_by(MemoryRecord.created_at.desc())
    ).all()
    return [memory_read(record) for record in records]


@router.get(
    "/chats/{chat_id}/memory-graph",
    response_model=list[NarrativeNodeRead],
    tags=["memory-hub"],
)
def memory_graph(
    chat_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> list[NarrativeNodeRead]:
    """返回摘要森林，并标记当前真正会注入主模型的节点。"""
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    recent = db.scalars(
        select(MessageRecord)
        .where(MessageRecord.chat_id == str(chat_id))
        .order_by(MessageRecord.created_at.desc())
        .limit(runtime.settings.recent_message_limit)
    ).all()
    nodes = runtime.narrative_memory_service.inspect_nodes(
        db, str(chat_id), {item.id for item in recent}
    )
    return [
        NarrativeNodeRead(
            id=UUID(item.id),
            node_type=item.node_type,
            level=item.level,
            content=item.content,
            child_ids=[UUID(child_id) for child_id in item.child_ids],
            source_message_id=(UUID(item.source_message_id) if item.source_message_id else None),
            time_start=item.time_start,
            time_end=item.time_end,
            valid=item.valid,
            active=item.active,
            created_at=item.created_at,
        )
        for item in nodes
    ]


@router.get(
    "/chats/{chat_id}/memory-coverage",
    response_model=MemoryCoverageRead,
    tags=["memory-hub"],
)
def memory_coverage(
    chat_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryCoverageRead:
    """报告漏摘和因原文变化而失效的楼层。"""
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    coverage = runtime.narrative_memory_service.coverage(db, str(chat_id))
    return MemoryCoverageRead(
        total_ai_floors=coverage.total_ai_floors,
        summarized_floors=coverage.summarized_floors,
        valid_floors=coverage.valid_floors,
        coverage_ratio=coverage.coverage_ratio,
        missing_message_ids=[UUID(item) for item in coverage.missing_message_ids],
        invalid_message_ids=[UUID(item) for item in coverage.invalid_message_ids],
        selected_node_ids=[UUID(item) for item in coverage.selected_node_ids],
    )


@router.post(
    "/chats/{chat_id}/memory-coverage/backfill",
    response_model=MemoryCoverageRead,
    tags=["memory-hub"],
)
async def backfill_memory_coverage(
    chat_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryCoverageRead:
    """为升级前的旧故事补齐楼层叶子；可能产生多次摘要模型调用。"""
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    await runtime.narrative_memory_service.backfill_missing(
        db, runtime.model, str(chat_id)
    )
    coverage = runtime.narrative_memory_service.coverage(db, str(chat_id))
    return MemoryCoverageRead(
        total_ai_floors=coverage.total_ai_floors,
        summarized_floors=coverage.summarized_floors,
        valid_floors=coverage.valid_floors,
        coverage_ratio=coverage.coverage_ratio,
        missing_message_ids=[UUID(item) for item in coverage.missing_message_ids],
        invalid_message_ids=[UUID(item) for item in coverage.invalid_message_ids],
        selected_node_ids=[UUID(item) for item in coverage.selected_node_ids],
    )


@router.get("/chats/{chat_id}/scenes", response_model=list[SceneNodeRead], tags=["roleplay-graph"])
def list_scenes(
    chat_id: UUID, request: Request, db: Session = Depends(get_db)
) -> list[SceneNodeRead]:
    _chat_or_404(db, chat_id)
    service = request.app.state.runtime.graph_service
    records = service.list_scenes(db, str(chat_id))
    by_id = {item.id: item for item in records}
    return [scene_read(item, service.scene_path(item, by_id)) for item in records]


@router.post(
    "/chats/{chat_id}/scenes",
    response_model=SceneNodeRead,
    status_code=status.HTTP_201_CREATED,
    tags=["roleplay-graph"],
)
def create_scene(
    chat_id: UUID,
    payload: SceneNodeUpsert,
    request: Request,
    db: Session = Depends(get_db),
) -> SceneNodeRead:
    _chat_or_404(db, chat_id)
    service = request.app.state.runtime.graph_service
    try:
        record = service.upsert_scene(
            db, str(chat_id), payload.name,
            str(payload.parent_id) if payload.parent_id else None,
            payload.description, payload.is_current,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    records = service.list_scenes(db, str(chat_id))
    return scene_read(record, service.scene_path(record, {item.id: item for item in records}))


@router.put("/chats/{chat_id}/scenes/{scene_id}", response_model=SceneNodeRead, tags=["roleplay-graph"])
def update_scene(
    chat_id: UUID,
    scene_id: UUID,
    payload: SceneNodeUpsert,
    request: Request,
    db: Session = Depends(get_db),
) -> SceneNodeRead:
    _chat_or_404(db, chat_id)
    service = request.app.state.runtime.graph_service
    try:
        record = service.upsert_scene(
            db, str(chat_id), payload.name,
            str(payload.parent_id) if payload.parent_id else None,
            payload.description, payload.is_current, scene_id=str(scene_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    records = service.list_scenes(db, str(chat_id))
    return scene_read(record, service.scene_path(record, {item.id: item for item in records}))


@router.delete("/chats/{chat_id}/scenes/{scene_id}", status_code=204, tags=["roleplay-graph"])
def delete_scene(chat_id: UUID, scene_id: UUID, db: Session = Depends(get_db)) -> Response:
    _chat_or_404(db, chat_id)
    try:
        RoleplayGraphService().delete_scene(db, str(chat_id), str(scene_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/chats/{chat_id}/npcs", response_model=list[NpcRead], tags=["roleplay-graph"])
def list_npcs(chat_id: UUID, request: Request, db: Session = Depends(get_db)) -> list[NpcRead]:
    _chat_or_404(db, chat_id)
    return [npc_read(item) for item in request.app.state.runtime.graph_service.list_npcs(db, str(chat_id))]


@router.post(
    "/chats/{chat_id}/npcs", response_model=NpcRead,
    status_code=status.HTTP_201_CREATED, tags=["roleplay-graph"],
)
def create_npc(
    chat_id: UUID, payload: NpcUpsert, request: Request, db: Session = Depends(get_db)
) -> NpcRead:
    _chat_or_404(db, chat_id)
    try:
        record = request.app.state.runtime.graph_service.upsert_npc(
            db, str(chat_id), payload.name, payload.description, payload.relation_to_user,
            [item.model_dump() for item in payload.relations], payload.importance, payload.presence,
            str(payload.location_scene_id) if payload.location_scene_id else None,
            payload.outfit, payload.condition,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return npc_read(record)


@router.put("/chats/{chat_id}/npcs/{npc_id}", response_model=NpcRead, tags=["roleplay-graph"])
def update_npc(
    chat_id: UUID, npc_id: UUID, payload: NpcUpsert,
    request: Request, db: Session = Depends(get_db),
) -> NpcRead:
    _chat_or_404(db, chat_id)
    try:
        record = request.app.state.runtime.graph_service.upsert_npc(
            db, str(chat_id), payload.name, payload.description, payload.relation_to_user,
            [item.model_dump() for item in payload.relations], payload.importance, payload.presence,
            str(payload.location_scene_id) if payload.location_scene_id else None,
            payload.outfit, payload.condition, npc_id=str(npc_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return npc_read(record)


@router.delete("/chats/{chat_id}/npcs/{npc_id}", status_code=204, tags=["roleplay-graph"])
def delete_npc(chat_id: UUID, npc_id: UUID, db: Session = Depends(get_db)) -> Response:
    _chat_or_404(db, chat_id)
    try:
        RoleplayGraphService().delete_npc(db, str(chat_id), str(npc_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post(
    "/chats/{chat_id}/memories",
    response_model=MemoryRead,
    status_code=status.HTTP_201_CREATED,
    tags=["memory"],
)
async def create_memory(
    chat_id: UUID,
    payload: MemoryCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryRead:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    record = await runtime.memory_service.create(
        db,
        runtime.model,
        str(chat_id),
        payload.kind,
        payload.content,
        payload.importance,
        str(payload.source_message_id) if payload.source_message_id else None,
    )
    return memory_read(record)


@router.post(
    "/chats/{chat_id}/memories/search",
    response_model=list[MemorySearchResult],
    tags=["memory"],
)
async def search_memories(
    chat_id: UUID,
    payload: MemorySearchRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> list[MemorySearchResult]:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    results = await runtime.memory_service.search(
        db,
        runtime.model,
        str(chat_id),
        payload.query,
        payload.limit,
    )
    return [
        MemorySearchResult(
            memory=memory_read(item.record),
            score=item.score,
            retrieval_reason=item.reason,
        )
        for item in results
    ]


@router.post(
    "/chats/{chat_id}/memories/merge",
    response_model=MemoryRead,
    tags=["memory"],
)
async def merge_memories(
    chat_id: UUID,
    payload: MemoryMergeRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryRead:
    _chat_or_404(db, chat_id)
    records = [_memory_or_404(db, chat_id, item) for item in payload.memory_ids]
    runtime: AgentRuntime = request.app.state.runtime
    record = await runtime.narrative_memory_service.merge_memories(
        db,
        runtime.model,
        str(chat_id),
        records,
        payload.detail_mode,
    )
    return memory_read(record)


@router.post(
    "/chats/{chat_id}/memories/summarize",
    response_model=MemoryRead,
    tags=["memory"],
)
async def summarize_memories(
    chat_id: UUID,
    payload: MemorySummaryRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryRead:
    """把最近一段对话压缩成可检索的摘要记忆。"""
    _chat_or_404(db, chat_id)
    records_desc = db.scalars(
        select(MessageRecord)
        .where(MessageRecord.chat_id == str(chat_id))
        .order_by(MessageRecord.created_at.desc())
        .limit(payload.max_messages)
    ).all()
    records = list(reversed(records_desc))
    if not records:
        raise HTTPException(status_code=400, detail="当前存档还没有可总结的消息")

    transcript = "\n".join(
        f"{record.role}: {record.content}" for record in records
    )
    runtime: AgentRuntime = request.app.state.runtime
    reply = await runtime.model.complete(
        [
            {
                "role": "system",
                "content": (
                    "生成剧情摘要。保留关键事件、人物关系、承诺、伏笔、"
                    "时间变化和重要状态，不补充原文没有的信息。"
                    + (
                        "使用详细模式，保留重要动作和关系变化。"
                        if payload.detail_mode == "detailed"
                        else "使用精简模式，只保留影响后续剧情的信息。"
                    )
                ),
            },
            {"role": "user", "content": transcript},
        ]
    )
    summary = f"[手动总结] {reply.content or '未能生成摘要。'}"
    record = await runtime.memory_service.create(
        db,
        runtime.model,
        str(chat_id),
        MemoryKind.SUMMARY,
        summary,
        importance=0.8,
        source_message_id=records[-1].id,
    )
    return memory_read(record)


@router.put(
    "/chats/{chat_id}/memories/{memory_id}",
    response_model=MemoryRead,
    tags=["memory"],
)
async def update_memory(
    chat_id: UUID,
    memory_id: UUID,
    payload: MemoryUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryRead:
    _chat_or_404(db, chat_id)
    record = _memory_or_404(db, chat_id, memory_id)
    runtime: AgentRuntime = request.app.state.runtime
    record.content = payload.content.strip()
    record.importance = payload.importance
    record.embedding_json = json_dumps(await runtime.model.embed(record.content))
    db.commit()
    db.refresh(record)
    return memory_read(record)


@router.delete(
    "/chats/{chat_id}/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["memory"],
)
def delete_memory(
    chat_id: UUID,
    memory_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    _chat_or_404(db, chat_id)
    db.delete(_memory_or_404(db, chat_id, memory_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/chats/{chat_id}/timeline",
    response_model=list[TimelineAnchorRead],
    tags=["memory-hub"],
)
def list_timeline(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> list[TimelineAnchorRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(TimelineAnchorRecord)
        .where(TimelineAnchorRecord.chat_id == str(chat_id))
        .order_by(TimelineAnchorRecord.created_at)
    ).all()
    return [timeline_anchor_read(record) for record in records]


@router.post(
    "/chats/{chat_id}/timeline",
    response_model=TimelineAnchorRead,
    status_code=status.HTTP_201_CREATED,
    tags=["memory-hub"],
)
def create_timeline_anchor(
    chat_id: UUID,
    payload: TimelineAnchorCreate,
    db: Session = Depends(get_db),
) -> TimelineAnchorRead:
    _chat_or_404(db, chat_id)
    now = datetime.now(UTC)
    record = TimelineAnchorRecord(
        id=str(uuid4()),
        chat_id=str(chat_id),
        story_time=payload.story_time.strip(),
        description=payload.description.strip(),
        source_message_id=(str(payload.source_message_id) if payload.source_message_id else None),
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return timeline_anchor_read(record)


@router.put(
    "/chats/{chat_id}/timeline/{anchor_id}",
    response_model=TimelineAnchorRead,
    tags=["memory-hub"],
)
def update_timeline_anchor(
    chat_id: UUID,
    anchor_id: UUID,
    payload: TimelineAnchorCreate,
    db: Session = Depends(get_db),
) -> TimelineAnchorRead:
    _chat_or_404(db, chat_id)
    record = _timeline_or_404(db, chat_id, anchor_id)
    record.story_time = payload.story_time.strip()
    record.description = payload.description.strip()
    record.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(record)
    return timeline_anchor_read(record)


@router.delete(
    "/chats/{chat_id}/timeline/{anchor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["memory-hub"],
)
def delete_timeline_anchor(
    chat_id: UUID,
    anchor_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    _chat_or_404(db, chat_id)
    db.delete(_timeline_or_404(db, chat_id, anchor_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/chats/{chat_id}/state",
    response_model=list[StateEntryRead],
    tags=["state"],
)
def list_state(
    chat_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> list[StateEntryRead]:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    return [
        state_entry_read(item)
        for item in runtime.state_service.list_entries(db, str(chat_id))
    ]


@router.post(
    "/chats/{chat_id}/state/proposals",
    response_model=StateChangeRead,
    status_code=status.HTTP_201_CREATED,
    tags=["state"],
)
def create_state_proposal(
    chat_id: UUID,
    payload: StateProposalCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> StateChangeRead:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    record = runtime.state_service.propose(
        db,
        str(chat_id),
        payload.entity,
        payload.key,
        payload.new_value,
        payload.reason,
        str(payload.source_message_id) if payload.source_message_id else None,
    )
    return state_change_read(record)


@router.get(
    "/chats/{chat_id}/state/proposals",
    response_model=list[StateChangeRead],
    tags=["state"],
)
def list_state_proposals(
    chat_id: UUID,
    proposal_status: ProposalStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[StateChangeRead]:
    _chat_or_404(db, chat_id)
    statement = select(StateChangeRecord).where(
        StateChangeRecord.chat_id == str(chat_id)
    )
    if proposal_status:
        statement = statement.where(StateChangeRecord.status == proposal_status.value)
    records = db.scalars(statement.order_by(StateChangeRecord.created_at.desc())).all()
    return [state_change_read(record) for record in records]


@router.post(
    "/chats/{chat_id}/state/proposals/{proposal_id}/resolve",
    response_model=StateChangeRead,
    tags=["state"],
)
def resolve_state_proposal(
    chat_id: UUID,
    proposal_id: UUID,
    payload: StateResolution,
    request: Request,
    db: Session = Depends(get_db),
) -> StateChangeRead:
    _chat_or_404(db, chat_id)
    proposal = db.scalar(
        select(StateChangeRecord).where(
            StateChangeRecord.id == str(proposal_id),
            StateChangeRecord.chat_id == str(chat_id),
        )
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="状态变更建议不存在")
    runtime: AgentRuntime = request.app.state.runtime
    try:
        resolved = runtime.state_service.resolve(
            db,
            proposal,
            approve=payload.action == "approve",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return state_change_read(resolved)


@router.get(
    "/chats/{chat_id}/audits",
    response_model=list[AuditIssueRead],
    tags=["audit"],
)
def list_audits(chat_id: UUID, db: Session = Depends(get_db)) -> list[AuditIssueRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(AuditIssueRecord)
        .where(AuditIssueRecord.chat_id == str(chat_id))
        .order_by(AuditIssueRecord.created_at.desc())
    ).all()
    return [audit_read(record) for record in records]


@router.post(
    "/chats/{chat_id}/audits/{audit_id}/resolve",
    response_model=AuditIssueRead,
    tags=["audit"],
)
def resolve_audit(
    chat_id: UUID,
    audit_id: UUID,
    payload: AuditResolution,
    db: Session = Depends(get_db),
) -> AuditIssueRead:
    _chat_or_404(db, chat_id)
    record = db.scalar(
        select(AuditIssueRecord).where(
            AuditIssueRecord.id == str(audit_id),
            AuditIssueRecord.chat_id == str(chat_id),
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="审计问题不存在")
    record.status = (
        AuditStatus.RESOLVED.value
        if payload.action == "resolve"
        else AuditStatus.DISMISSED.value
    )
    db.commit()
    db.refresh(record)
    return audit_read(record)


@router.get(
    "/chats/{chat_id}/traces",
    response_model=list[AgentTraceRead],
    tags=["trace"],
)
def list_traces(
    chat_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AgentTraceRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(AgentTraceRecord)
        .where(AgentTraceRecord.chat_id == str(chat_id))
        .order_by(AgentTraceRecord.created_at.desc())
        .limit(limit)
    ).all()
    return [trace_read(record) for record in records]


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
        created_at=now,
        updated_at=now,
    )


def _world_values(payload: WorldBookEntryCreate) -> dict[str, Any]:
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
    existing = set(db.scalars(
        select(StoryWorldBookRecord.source_template_id).where(
            StoryWorldBookRecord.chat_id == chat_id
        )
    ).all())
    for template_id in _clean_string_list(json_loads(world_book_ids_json) or []):
        if template_id in existing:
            continue
        template = db.get(WorldBookTemplateRecord, template_id)
        if template:
            db.add(_copy_world_to_story(template, chat_id, now))
            existing.add(template_id)
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
    """让改写前产生的状态提议回到待审核，投影稍后会按指纹重建。"""
    affected_leaves = db.scalars(
        select(NarrativeLeafRecord).where(
            NarrativeLeafRecord.chat_id == chat_id,
            (
                (NarrativeLeafRecord.user_message_id == message_id)
                | (NarrativeLeafRecord.assistant_message_id == message_id)
            ),
        )
    ).all()
    affected_sources = {leaf.user_message_id for leaf in affected_leaves}
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
        change.status = ProposalStatus.PENDING.value
        change.resolved_at = None
        if not change.reason.startswith("源剧情已改写"):
            change.reason = f"源剧情已改写，请重新确认：{change.reason}"


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
    for item in characters:
        db.add(
            StoryCharacterRecord(
                id=str(uuid4()),
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
        db.add(
            StoryWorldBookRecord(
                id=str(uuid4()),
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
                created_at=now,
                updated_at=now,
            )
        )
    persona = db.scalar(
        select(StoryPersonaRecord).where(StoryPersonaRecord.chat_id == source.id)
    )
    if persona:
        db.add(StoryPersonaRecord(
            id=str(uuid4()), chat_id=branch.id,
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
    changes = db.scalars(
        select(StateChangeRecord)
        .where(
            StateChangeRecord.chat_id == source.id,
            StateChangeRecord.source_message_id.in_(message_ids),
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
                source_message_id=message_ids[item.source_message_id],
                status=item.status,
                created_at=item.created_at,
                resolved_at=item.resolved_at,
            )
        )
    graph_events = db.scalars(
        select(RoleplayGraphEventRecord)
        .where(
            RoleplayGraphEventRecord.chat_id == source.id,
            RoleplayGraphEventRecord.source_message_id.in_(message_ids),
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
                source_hash=item.source_hash,
                created_at=item.created_at,
            )
        )
    branch.updated_at = now
    db.commit()
    runtime.state_service.rebuild_entries(db, branch.id)
    runtime.graph_service.rebuild_projections(db, branch.id)
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


def _settings_read(settings: Settings) -> SettingsRead:
    key = settings.llm_api_key or ""
    hint = f"••••{key[-4:]}" if key else None
    rerank_key = settings.rerank_api_key or ""
    rerank_hint = f"••••{rerank_key[-4:]}" if rerank_key else None
    return SettingsRead(
        provider_mode=settings.provider_mode,
        llm_base_url=settings.llm_base_url,
        api_key_configured=bool(key),
        api_key_hint=hint,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        temperature=settings.temperature,
        top_p=settings.top_p,
        max_output_tokens=settings.max_output_tokens,
        presence_penalty=settings.presence_penalty,
        frequency_penalty=settings.frequency_penalty,
        request_timeout=settings.request_timeout,
        max_agent_steps=settings.max_agent_steps,
        recent_message_limit=settings.recent_message_limit,
        rag_limit=settings.rag_limit,
        vector_weight=settings.vector_weight,
        keyword_weight=settings.keyword_weight,
        importance_weight=settings.importance_weight,
        recency_weight=settings.recency_weight,
        auto_summary_enabled=settings.auto_summary_enabled,
        summary_detail_mode=settings.summary_detail_mode,
        chapter_summary_size=settings.chapter_summary_size,
        arc_summary_size=settings.arc_summary_size,
        rerank_base_url=settings.rerank_base_url,
        rerank_api_key_configured=bool(rerank_key),
        rerank_api_key_hint=rerank_hint,
        rerank_model=settings.rerank_model,
        rerank_candidates=settings.rerank_candidates,
        context_window_tokens=settings.context_window_tokens,
    )


def _clean_optional(value: str | None) -> str | None:
    text = value.strip() if value else ""
    return text or None
