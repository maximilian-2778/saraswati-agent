"""长期记忆、时间线、场景树与 NPC 关系。"""

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
    NarrativeFloorSummaryRequest,
    NarrativeNodeUpdate,
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
    SceneMergeRequest,
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

def _narrative_node_read(item) -> NarrativeNodeRead:
    return NarrativeNodeRead(
        id=UUID(item.id), node_type=item.node_type, level=item.level,
        content=item.content, child_ids=[UUID(child) for child in item.child_ids],
        source_message_id=UUID(item.source_message_id) if item.source_message_id else None,
        time_start=item.time_start, time_end=item.time_end, valid=item.valid,
        active=item.active, created_at=item.created_at,
    )

@router.post("/chats/{chat_id}/memory-graph/floors/{message_id}/summarize", response_model=NarrativeNodeRead, tags=["memory-hub"])
async def summarize_narrative_floor(chat_id: UUID, message_id: UUID, payload: NarrativeFloorSummaryRequest, request: Request, db: Session = Depends(get_db)) -> NarrativeNodeRead:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    try:
        node = await runtime.narrative_memory_service.summarize_floor(db, runtime.model, str(chat_id), str(message_id), payload.detail_mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _narrative_node_read(node)

@router.put("/chats/{chat_id}/memory-graph/{node_id}", response_model=NarrativeNodeRead, tags=["memory-hub"])
async def update_narrative_node(chat_id: UUID, node_id: UUID, payload: NarrativeNodeUpdate, request: Request, db: Session = Depends(get_db)) -> NarrativeNodeRead:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    try:
        node = await runtime.narrative_memory_service.update_node(db, runtime.model, str(chat_id), str(node_id), payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _narrative_node_read(node)

@router.delete("/chats/{chat_id}/memory-graph/{node_id}", status_code=204, tags=["memory-hub"])
def delete_narrative_node(chat_id: UUID, node_id: UUID, request: Request, db: Session = Depends(get_db)) -> Response:
    _chat_or_404(db, chat_id)
    try:
        request.app.state.runtime.narrative_memory_service.delete_node(db, str(chat_id), str(node_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)

@router.post("/chats/{chat_id}/memory-graph/{node_id}/rebuild", response_model=NarrativeNodeRead | None, tags=["memory-hub"])
async def rebuild_narrative_node(chat_id: UUID, node_id: UUID, payload: NarrativeFloorSummaryRequest, request: Request, db: Session = Depends(get_db)) -> NarrativeNodeRead | None:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    try:
        node = await runtime.narrative_memory_service.rebuild_node(db, runtime.model, str(chat_id), str(node_id), payload.detail_mode)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _narrative_node_read(node) if node else None

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
            aliases=payload.aliases,
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
            aliases=payload.aliases,
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


@router.post(
    "/chats/{chat_id}/scenes/{scene_id}/merge",
    response_model=SceneNodeRead,
    tags=["roleplay-graph"],
)
def merge_scene(
    chat_id: UUID,
    scene_id: UUID,
    payload: SceneMergeRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> SceneNodeRead:
    _chat_or_404(db, chat_id)
    service = request.app.state.runtime.graph_service
    try:
        target = service.merge_scene(
            db, str(chat_id), str(scene_id), str(payload.target_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    records = service.list_scenes(db, str(chat_id))
    return scene_read(
        target, service.scene_path(target, {item.id: item for item in records})
    )

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
    from backend.services.timeline import timeline_service
    record = timeline_service.create(
        db, str(chat_id), payload.story_time, payload.description,
        str(payload.source_message_id) if payload.source_message_id else None,
    )
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
    from backend.services.timeline import parse_story_time, timeline_service
    previous_time = None
    for item in timeline_service.list(db, str(chat_id)):
        if item.id == record.id or item.is_conflict:
            continue
        previous_time = parse_story_time(item.story_time, previous_time) or previous_time
        if item.created_at >= record.created_at:
            break
    proposed = parse_story_time(record.story_time, previous_time)
    record.is_conflict = bool(proposed and previous_time and proposed < previous_time)
    record.conflict_reason = "该时间早于此前的有效时间锚点。" if record.is_conflict else ""
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
