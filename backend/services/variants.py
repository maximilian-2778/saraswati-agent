"""Candidate-aware ownership and active-record filtering."""

from __future__ import annotations

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend.models import (
    MemoryRecord,
    MessageRecord,
    MessageVariantRecord,
    RoleplayGraphEventRecord,
    StateChangeRecord,
)
from backend.utils import json_loads


def active_variant_clause(column: ColumnElement[str | None]) -> ColumnElement[bool]:
    selected = select(MessageVariantRecord.id).where(MessageVariantRecord.selected.is_(True))
    return or_(column.is_(None), column.in_(selected))


def active_variant_ids(db: Session, chat_id: str) -> set[str]:
    return set(db.scalars(select(MessageVariantRecord.id).where(
        MessageVariantRecord.chat_id == chat_id,
        MessageVariantRecord.selected.is_(True),
    )).all())


def variant_scope_is_active(value: str, selected: set[str]) -> bool:
    return set(json_loads(value) or []).issubset(selected)


def selected_variant_id(db: Session, assistant_message_id: str) -> str:
    value = db.scalar(select(MessageVariantRecord.id).where(
        MessageVariantRecord.message_id == assistant_message_id,
        MessageVariantRecord.selected.is_(True),
    ))
    if value is None:
        raise ValueError("助手消息缺少当前候选回复。")
    return value


def selected_variant_for_source(db: Session, source_message_id: str | None) -> str | None:
    if not source_message_id:
        return None
    message = db.get(MessageRecord, source_message_id)
    if message is None:
        return None
    if message.role == "assistant":
        return db.scalar(select(MessageVariantRecord.id).where(
            MessageVariantRecord.message_id == message.id,
            MessageVariantRecord.selected.is_(True),
        ))
    assistant = db.scalar(select(MessageRecord).where(
        MessageRecord.chat_id == message.chat_id,
        MessageRecord.role == "assistant",
        MessageRecord.created_at > message.created_at,
    ).order_by(MessageRecord.created_at).limit(1))
    if assistant is None:
        return None
    return db.scalar(select(MessageVariantRecord.id).where(
        MessageVariantRecord.message_id == assistant.id,
        MessageVariantRecord.selected.is_(True),
    ))


def attach_turn_artifacts(
    db: Session,
    user_message_id: str,
    assistant_message_id: str,
    variant_id: str,
) -> None:
    source_ids = [user_message_id, assistant_message_id]
    for model in (StateChangeRecord, RoleplayGraphEventRecord, MemoryRecord):
        db.execute(update(model).where(
            model.source_message_id.in_(source_ids),
            model.variant_id.is_(None),
        ).values(variant_id=variant_id))
    db.commit()
