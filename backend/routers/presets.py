"""写作预设与 SillyTavern JSON 兼容 API。"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import Settings, save_local_settings
from backend.database import get_db
from backend.llm import build_model_client
from backend.models import PromptPresetRecord
from backend.schemas import PromptPresetCreate, PromptPresetImport, PromptPresetRead
from backend.services.agent import AgentRuntime
from backend.services.presets import create_record, export_sillytavern, import_payload, preset_read
from backend.utils import json_dumps


router = APIRouter(prefix="/presets", tags=["presets"])


@router.get("", response_model=list[PromptPresetRead])
def list_presets(request: Request, db: Session = Depends(get_db)) -> list[PromptPresetRead]:
    active_id = request.app.state.settings.active_preset_id
    records = db.scalars(select(PromptPresetRecord).order_by(PromptPresetRecord.updated_at.desc())).all()
    return [preset_read(item, active_id) for item in records]


@router.post("", response_model=PromptPresetRead, status_code=status.HTTP_201_CREATED)
def create_preset(payload: PromptPresetCreate, request: Request, db: Session = Depends(get_db)) -> PromptPresetRead:
    record = create_record(payload)
    db.add(record)
    _commit(db)
    db.refresh(record)
    return preset_read(record, request.app.state.settings.active_preset_id)


@router.put("/{preset_id}", response_model=PromptPresetRead)
def update_preset(preset_id: UUID, payload: PromptPresetCreate, request: Request, db: Session = Depends(get_db)) -> PromptPresetRead:
    record = _preset(db, preset_id)
    record.name = payload.name.strip()
    record.description = payload.description.strip()
    record.temperature = payload.temperature
    record.top_p = payload.top_p
    record.max_output_tokens = payload.max_output_tokens
    record.presence_penalty = payload.presence_penalty
    record.frequency_penalty = payload.frequency_penalty
    record.context_window_tokens = payload.context_window_tokens
    record.prompts_json = json_dumps([item.model_dump(mode="json") for item in payload.prompts])
    record.extra_settings_json = json_dumps(payload.extra_settings)
    record.updated_at = datetime.now(UTC)
    _commit(db)
    db.refresh(record)
    return preset_read(record, request.app.state.settings.active_preset_id)


@router.post("/{preset_id}/duplicate", response_model=PromptPresetRead, status_code=status.HTTP_201_CREATED)
def duplicate_preset(preset_id: UUID, request: Request, db: Session = Depends(get_db)) -> PromptPresetRead:
    source = _preset(db, preset_id)
    payload = preset_read(source, None)
    values = payload.model_dump(exclude={"id", "active", "created_at", "updated_at"})
    values["name"] = f"{source.name} 副本"
    record = create_record(PromptPresetCreate(**values))
    db.add(record)
    _commit(db)
    db.refresh(record)
    return preset_read(record, request.app.state.settings.active_preset_id)


@router.post("/import", response_model=PromptPresetRead, status_code=status.HTTP_201_CREATED)
def import_preset(payload: PromptPresetImport, request: Request, db: Session = Depends(get_db)) -> PromptPresetRead:
    record = create_record(import_payload(payload.data, payload.name))
    db.add(record)
    _commit(db)
    db.refresh(record)
    return preset_read(record, request.app.state.settings.active_preset_id)


@router.get("/{preset_id}/export")
def export_preset(preset_id: UUID, db: Session = Depends(get_db)) -> dict:
    return export_sillytavern(_preset(db, preset_id))


@router.post("/{preset_id}/activate", response_model=PromptPresetRead)
async def activate_preset(preset_id: UUID, request: Request, db: Session = Depends(get_db)) -> PromptPresetRead:
    record = _preset(db, preset_id)
    current: Settings = request.app.state.settings
    updated = replace(
        current, active_preset_id=record.id,
    )
    model = build_model_client(updated)
    runtime = AgentRuntime(updated, model)
    await runtime.startup()
    previous: AgentRuntime = request.app.state.runtime
    request.app.state.settings = updated
    request.app.state.model = model
    request.app.state.runtime = runtime
    save_local_settings(updated)
    await previous.shutdown()
    return preset_read(record, record.id)


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preset(preset_id: UUID, request: Request, db: Session = Depends(get_db)) -> Response:
    record = _preset(db, preset_id)
    if request.app.state.settings.active_preset_id == record.id:
        raise HTTPException(status_code=409, detail="当前启用的预设不能删除，请先启用另一份预设")
    db.delete(record)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _preset(db: Session, preset_id: UUID) -> PromptPresetRecord:
    record = db.get(PromptPresetRecord, str(preset_id))
    if record is None:
        raise HTTPException(status_code=404, detail="预设不存在")
    return record


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="预设名称已存在") from exc
