"""可复用的角色、主控人物与世界书模板。"""

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
        compatibility_data_json=source.compatibility_data_json,
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
