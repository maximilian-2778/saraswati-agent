"""原生世界推演状态与手动推进 API。"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import UUID

from backend.database import get_db
from backend.llm import ModelProviderError
from backend.models import ChatRecord, MessageRecord
from backend.schemas import MessageRole
from backend.services.world_engine import WorldEngineService, WorldEngineSnapshot, WorldState


router = APIRouter(prefix="/chats/{chat_id}/world-engine", tags=["world-engine"])


class WorldEngineConfigUpdate(BaseModel):
    auto_evolve: bool


@router.get("", response_model=WorldEngineSnapshot)
def get_world_engine(chat_id: UUID, db: Session = Depends(get_db)) -> WorldEngineSnapshot:
    _chat_or_404(db, chat_id)
    return WorldEngineService().snapshot(db, str(chat_id))


@router.put("/config", response_model=WorldEngineSnapshot)
def update_world_engine_config(
    chat_id: UUID,
    payload: WorldEngineConfigUpdate,
    db: Session = Depends(get_db),
) -> WorldEngineSnapshot:
    _chat_or_404(db, chat_id)
    return WorldEngineService().set_auto_evolve(db, str(chat_id), payload.auto_evolve)


@router.put("/state", response_model=WorldEngineSnapshot)
def update_world_engine_state(
    chat_id: UUID,
    payload: WorldState,
    db: Session = Depends(get_db),
) -> WorldEngineSnapshot:
    _chat_or_404(db, chat_id)
    return WorldEngineService().save_manual(db, str(chat_id), payload)


@router.post("/evolve", response_model=WorldEngineSnapshot)
async def evolve_world(
    chat_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> WorldEngineSnapshot:
    _chat_or_404(db, chat_id)
    messages = list(db.scalars(
        select(MessageRecord)
        .where(MessageRecord.chat_id == str(chat_id))
        .order_by(MessageRecord.created_at.desc())
        .limit(20)
    ).all())
    assistant = next((item for item in messages if item.role == MessageRole.ASSISTANT.value), None)
    user = None
    if assistant is not None:
        user = next(
            (item for item in messages if item.role == MessageRole.USER.value and item.created_at <= assistant.created_at),
            None,
        )
    try:
        runtime = request.app.state.runtime
        return await runtime.world_engine_service.evolve(
            db,
            runtime.model,
            str(chat_id),
            user,
            assistant,
            mode="manual",
        )
    except ModelProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _chat_or_404(db: Session, chat_id: UUID) -> ChatRecord:
    chat = db.get(ChatRecord, str(chat_id))
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="故事不存在")
    return chat
