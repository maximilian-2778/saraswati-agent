"""精确状态、修改历史、一致性检查与运行记录。"""

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

@router.post(
    "/chats/{chat_id}/state/proposals/{proposal_id}/undo",
    response_model=StateChangeRead,
    tags=["state"],
)
def undo_state_change(
    chat_id: UUID,
    proposal_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> StateChangeRead:
    _chat_or_404(db, chat_id)
    change = db.scalar(
        select(StateChangeRecord).where(
            StateChangeRecord.id == str(proposal_id),
            StateChangeRecord.chat_id == str(chat_id),
        )
    )
    if not change:
        raise HTTPException(status_code=404, detail="状态修改不存在")
    runtime: AgentRuntime = request.app.state.runtime
    try:
        reverted = runtime.state_service.undo(db, change)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return state_change_read(reverted)


@router.delete(
    "/chats/{chat_id}/state/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["state"],
)
def delete_state_entry(
    chat_id: UUID,
    entry_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    _chat_or_404(db, chat_id)
    try:
        request.app.state.runtime.state_service.remove_entry(
            db, str(chat_id), str(entry_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

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
