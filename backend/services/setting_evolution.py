"""Controlled, auditable evolution of story-local character and world settings."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.models import (
    SettingChangeRecord,
    StoryCharacterRecord,
    StoryPersonaRecord,
    StoryWorldBookRecord,
)
from backend.schemas import ProposalStatus
from backend.services.variants import active_variant_clause, selected_variant_for_source


TARGET_MODELS = {
    "character": StoryCharacterRecord,
    "persona": StoryPersonaRecord,
    "world_book": StoryWorldBookRecord,
}

ALLOWED_FIELDS: dict[str, tuple[str, ...]] = {
    "character": ("identity", "personality", "speaking_style", "scenario", "appearance"),
    "persona": ("identity", "personality", "speaking_style", "appearance"),
    "world_book": ("content",),
}


class SettingEvolutionService:
    """Treat setting changes as the source of truth and story copies as projections."""

    def propose(
        self,
        db: Session,
        chat_id: str,
        target_type: str,
        target_id: str,
        field: str,
        new_value: str,
        reason: str,
        evidence: str,
        importance: str,
        confidence: float,
        source_message_id: str | None,
    ) -> SettingChangeRecord | None:
        target_type = target_type.strip().lower()
        field = field.strip()
        target = self._target(db, chat_id, target_type, target_id)
        if target is None or field not in ALLOWED_FIELDS.get(target_type, ()):
            return None
        cleaned = new_value.strip()
        if not cleaned or len(cleaned) > 30_000:
            return None
        current_value = str(getattr(target, field, ""))
        if cleaned == current_value.strip():
            return None

        history = list(db.scalars(
            select(SettingChangeRecord)
            .where(
                SettingChangeRecord.chat_id == chat_id,
                SettingChangeRecord.target_type == target_type,
                SettingChangeRecord.target_id == target_id,
                SettingChangeRecord.field == field,
            )
            .order_by(SettingChangeRecord.created_at, SettingChangeRecord.id)
        ).all())
        base_value = history[0].base_value if history else current_value
        variant_id = selected_variant_for_source(db, source_message_id)
        duplicate = next((
            item for item in history
            if item.source_message_id == source_message_id
            and item.variant_id == variant_id
            and item.new_value == cleaned
            and item.status != ProposalStatus.REJECTED.value
        ), None)
        if duplicate is not None:
            return duplicate

        # Only explicit, irreversible, high-confidence outcomes are auto-applied.
        auto_approve = importance == "critical" and confidence >= 0.9 and bool(evidence.strip())
        now = datetime.now(UTC)
        record = SettingChangeRecord(
            id=str(uuid4()),
            chat_id=chat_id,
            target_type=target_type,
            target_id=target_id,
            field=field,
            base_value=base_value,
            new_value=cleaned,
            reason=reason.strip()[:2_000] or "剧情产生了长期且重大的设定变化",
            evidence=evidence.strip()[:4_000],
            importance=importance if importance in {"major", "critical"} else "major",
            confidence=max(0.0, min(1.0, float(confidence))),
            source_message_id=source_message_id,
            variant_id=variant_id,
            status=(ProposalStatus.APPROVED.value if auto_approve else ProposalStatus.PENDING.value),
            created_at=now,
            resolved_at=now if auto_approve else None,
        )
        db.add(record)
        db.commit()
        if auto_approve:
            self.rebuild(db, chat_id)
        db.refresh(record)
        return record

    def apply_manual_field(
        self,
        db: Session,
        chat_id: str,
        target_type: str,
        target_id: str,
        field: str,
        new_value: str,
    ) -> SettingChangeRecord | None:
        """Record an explicit user edit as a global authoritative setting event."""
        target = self._target(db, chat_id, target_type, target_id)
        if target is None or field not in ALLOWED_FIELDS.get(target_type, ()):
            return None
        cleaned = new_value.strip()
        current = str(getattr(target, field, ""))
        if cleaned == current.strip():
            return None
        history = list(db.scalars(
            select(SettingChangeRecord)
            .where(
                SettingChangeRecord.chat_id == chat_id,
                SettingChangeRecord.target_type == target_type,
                SettingChangeRecord.target_id == target_id,
                SettingChangeRecord.field == field,
            )
            .order_by(SettingChangeRecord.created_at, SettingChangeRecord.id)
        ).all())
        now = datetime.now(UTC)
        for item in history:
            if item.status == ProposalStatus.APPROVED.value:
                item.status = ProposalStatus.REVERTED.value
                item.resolved_at = now
            elif item.status == ProposalStatus.PENDING.value:
                item.status = ProposalStatus.REJECTED.value
                item.resolved_at = now
        record = SettingChangeRecord(
            id=str(uuid4()), chat_id=chat_id, target_type=target_type,
            target_id=target_id, field=field,
            base_value=history[0].base_value if history else current,
            new_value=cleaned, reason="用户手动编辑故事设定副本",
            evidence="用户在故事设定编辑器中明确保存了该内容",
            importance="critical", confidence=1.0,
            source_message_id=None, variant_id=None,
            status=ProposalStatus.APPROVED.value,
            created_at=now, resolved_at=now,
        )
        db.add(record)
        db.commit()
        self.rebuild(db, chat_id)
        db.refresh(record)
        return record

    def delete_target_history(
        self,
        db: Session,
        chat_id: str,
        target_type: str,
        target_id: str,
    ) -> None:
        db.execute(delete(SettingChangeRecord).where(
            SettingChangeRecord.chat_id == chat_id,
            SettingChangeRecord.target_type == target_type,
            SettingChangeRecord.target_id == target_id,
        ))
        db.commit()

    def list(
        self,
        db: Session,
        chat_id: str,
        status: str | None = None,
    ) -> list[SettingChangeRecord]:
        statement = select(SettingChangeRecord).where(
            SettingChangeRecord.chat_id == chat_id,
            active_variant_clause(SettingChangeRecord.variant_id),
        )
        if status:
            statement = statement.where(SettingChangeRecord.status == status)
        return list(db.scalars(statement.order_by(SettingChangeRecord.created_at.desc())).all())

    def resolve(
        self,
        db: Session,
        record: SettingChangeRecord,
        approve: bool,
    ) -> SettingChangeRecord:
        if record.status != ProposalStatus.PENDING.value:
            raise ValueError("该设定变更已经处理，不能重复操作")
        record.status = ProposalStatus.APPROVED.value if approve else ProposalStatus.REJECTED.value
        record.resolved_at = datetime.now(UTC)
        db.commit()
        self.rebuild(db, record.chat_id)
        db.refresh(record)
        return record

    def undo(self, db: Session, record: SettingChangeRecord) -> SettingChangeRecord:
        if record.status != ProposalStatus.APPROVED.value:
            raise ValueError("只有已采用的设定变更可以撤销")
        record.status = ProposalStatus.REVERTED.value
        record.resolved_at = datetime.now(UTC)
        db.commit()
        self.rebuild(db, record.chat_id)
        db.refresh(record)
        return record

    def rebuild(self, db: Session, chat_id: str) -> None:
        all_changes = list(db.scalars(
            select(SettingChangeRecord)
            .where(SettingChangeRecord.chat_id == chat_id)
            .order_by(SettingChangeRecord.created_at, SettingChangeRecord.id)
        ).all())
        if not all_changes:
            return

        baselines: dict[tuple[str, str, str], str] = {}
        for change in all_changes:
            baselines.setdefault(
                (change.target_type, change.target_id, change.field),
                change.base_value,
            )
        touched: dict[str, Any] = {}
        for (target_type, target_id, field), base_value in baselines.items():
            target = self._target(db, chat_id, target_type, target_id)
            if target is None or field not in ALLOWED_FIELDS.get(target_type, ()):
                continue
            setattr(target, field, base_value)
            touched[target_id] = target

        active = list(db.scalars(
            select(SettingChangeRecord)
            .where(
                SettingChangeRecord.chat_id == chat_id,
                SettingChangeRecord.status == ProposalStatus.APPROVED.value,
                active_variant_clause(SettingChangeRecord.variant_id),
            )
            .order_by(SettingChangeRecord.resolved_at, SettingChangeRecord.created_at, SettingChangeRecord.id)
        ).all())
        for change in active:
            target = self._target(db, chat_id, change.target_type, change.target_id)
            if target is None or change.field not in ALLOWED_FIELDS.get(change.target_type, ()):
                continue
            setattr(target, change.field, change.new_value)
            target.updated_at = change.resolved_at or change.created_at
            touched[target.id] = target
        db.commit()

    def target_catalog(self, db: Session, chat_id: str) -> str:
        """Compact ID-addressed catalog supplied to the delta extractor."""
        items: list[dict[str, Any]] = []
        characters = db.scalars(
            select(StoryCharacterRecord)
            .where(StoryCharacterRecord.chat_id == chat_id)
            .order_by(StoryCharacterRecord.created_at)
        ).all()
        persona = db.scalar(select(StoryPersonaRecord).where(StoryPersonaRecord.chat_id == chat_id))
        books = db.scalars(
            select(StoryWorldBookRecord)
            .where(StoryWorldBookRecord.chat_id == chat_id, StoryWorldBookRecord.enabled.is_(True))
            .order_by(StoryWorldBookRecord.priority.desc())
            .limit(20)
        ).all()
        for target_type, records in (
            ("character", characters),
            ("persona", [persona] if persona else []),
            ("world_book", books),
        ):
            for record in records:
                items.append({
                    "target_type": target_type,
                    "target_id": record.id,
                    "name": getattr(record, "name", getattr(record, "title", "")),
                    "fields": {
                        field: {
                            "value": str(getattr(record, field, ""))[:4_000],
                            "complete": len(str(getattr(record, field, ""))) <= 4_000,
                        }
                        for field in ALLOWED_FIELDS[target_type]
                    },
                })
        return json.dumps(items, ensure_ascii=False, indent=2)

    @staticmethod
    def _target(
        db: Session,
        chat_id: str,
        target_type: str,
        target_id: str,
    ) -> Any | None:
        model = TARGET_MODELS.get(target_type)
        if model is None:
            return None
        return db.scalar(select(model).where(model.id == target_id, model.chat_id == chat_id))
