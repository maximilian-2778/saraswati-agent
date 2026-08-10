"""可追溯、可撤销的结构化世界状态。"""

from datetime import UTC, datetime
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.models import StateChangeRecord, StateEntryRecord
from backend.schemas import ProposalStatus
from backend.utils import json_dumps, json_loads


class StateService:
    """以事件方式记录状态变化，并重建当前投影。"""

    def list_entries(
        self,
        db: Session,
        chat_id: str,
        entity: str | None = None,
        key: str | None = None,
    ) -> list[StateEntryRecord]:
        entity = self._canonical_entity(entity) if entity else None
        key = self._canonical_key(entity, key) if key else None
        all_entries = list(db.scalars(
            select(StateEntryRecord).where(StateEntryRecord.chat_id == chat_id)
        ).all())
        identities = [self._canonical_identity(item.entity, item.key) for item in all_entries]
        if any(
            identity != (item.entity, item.key)
            for item, identity in zip(all_entries, identities, strict=True)
        ) or len(set(identities)) != len(identities):
            self.rebuild_entries(db, chat_id)

        statement = select(StateEntryRecord).where(
            StateEntryRecord.chat_id == chat_id
        )
        if entity:
            statement = statement.where(StateEntryRecord.entity == entity)
        if key:
            statement = statement.where(StateEntryRecord.key == key)
        return list(
            db.scalars(
                statement.order_by(StateEntryRecord.entity, StateEntryRecord.key)
            ).all()
        )

    def propose(
        self,
        db: Session,
        chat_id: str,
        entity: str,
        key: str,
        new_value: Any,
        reason: str,
        source_message_id: str | None = None,
        event_fingerprint: str | None = None,
    ) -> StateChangeRecord:
        entity, key = self._canonical_identity(entity, key)
        if event_fingerprint:
            duplicate_event = db.scalar(select(StateChangeRecord).where(
                StateChangeRecord.chat_id == chat_id,
                StateChangeRecord.event_fingerprint == event_fingerprint,
                StateChangeRecord.status == ProposalStatus.APPROVED.value,
            ))
            if duplicate_event is not None:
                return duplicate_event
        current = db.scalar(
            select(StateEntryRecord).where(
                StateEntryRecord.chat_id == chat_id,
                StateEntryRecord.entity == entity,
                StateEntryRecord.key == key,
            )
        )
        record = StateChangeRecord(
            id=str(uuid4()),
            chat_id=chat_id,
            entity=entity,
            key=key,
            old_value_json=current.value_json if current else None,
            new_value_json=json_dumps(new_value),
            reason=reason,
            event_fingerprint=event_fingerprint,
            source_message_id=source_message_id,
            status=ProposalStatus.PENDING.value,
            created_at=datetime.now(UTC),
            resolved_at=None,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def apply(
        self,
        db: Session,
        chat_id: str,
        entity: str,
        key: str,
        new_value: Any,
        reason: str,
        source_message_id: str | None = None,
        event_fingerprint: str | None = None,
    ) -> StateChangeRecord:
        """自动采用一条变化，同时保留可撤销的事件记录。"""
        entity, key = self._canonical_identity(entity, key)
        if event_fingerprint:
            duplicate_event = db.scalar(select(StateChangeRecord).where(
                StateChangeRecord.chat_id == chat_id,
                StateChangeRecord.event_fingerprint == event_fingerprint,
                StateChangeRecord.status == ProposalStatus.APPROVED.value,
            ))
            if duplicate_event is not None:
                return duplicate_event
        current = db.scalar(
            select(StateEntryRecord).where(
                StateEntryRecord.chat_id == chat_id,
                StateEntryRecord.entity == entity,
                StateEntryRecord.key == key,
            )
        )
        if current is not None:
            new_value = self._merge_item_state(
                entity, key, json_loads(current.value_json), new_value
            )
        serialized = json_dumps(new_value)
        duplicate = db.scalar(
            select(StateChangeRecord).where(
                StateChangeRecord.chat_id == chat_id,
                StateChangeRecord.entity == entity,
                StateChangeRecord.key == key,
                StateChangeRecord.new_value_json == serialized,
                StateChangeRecord.source_message_id == source_message_id,
                StateChangeRecord.status == ProposalStatus.APPROVED.value,
            )
        )
        if duplicate is not None:
            return duplicate

        now = datetime.now(UTC)
        record = StateChangeRecord(
            id=str(uuid4()),
            chat_id=chat_id,
            entity=entity,
            key=key,
            old_value_json=current.value_json if current else None,
            new_value_json=serialized,
            reason=reason,
            event_fingerprint=event_fingerprint,
            source_message_id=source_message_id,
            status=ProposalStatus.APPROVED.value,
            created_at=now,
            resolved_at=now,
        )
        db.add(record)
        db.commit()
        self.rebuild_entries(db, chat_id)
        db.refresh(record)
        return record

    def resolve(
        self,
        db: Session,
        proposal: StateChangeRecord,
        approve: bool,
    ) -> StateChangeRecord:
        if proposal.status != ProposalStatus.PENDING.value:
            raise ValueError("该状态建议已经处理，不能重复操作")

        now = datetime.now(UTC)
        if approve:
            proposal.status = ProposalStatus.APPROVED.value
        else:
            proposal.status = ProposalStatus.REJECTED.value

        proposal.resolved_at = now
        db.commit()
        if approve:
            self.rebuild_entries(db, proposal.chat_id)
        db.refresh(proposal)
        return proposal

    def undo(self, db: Session, change: StateChangeRecord) -> StateChangeRecord:
        """撤销一条已采用事件，再由剩余事件重建当前状态。"""
        if change.status != ProposalStatus.APPROVED.value:
            raise ValueError("只有已采用的修改可以撤销")
        change.status = ProposalStatus.REVERTED.value
        db.commit()
        self.rebuild_entries(db, change.chat_id)
        db.refresh(change)
        return change

    def remove_entry(self, db: Session, chat_id: str, entry_id: str) -> None:
        entry = db.get(StateEntryRecord, entry_id)
        if not entry or entry.chat_id != chat_id:
            raise ValueError("状态记录不存在")
        identity = self._canonical_identity(entry.entity, entry.key)
        changes = db.scalars(
            select(StateChangeRecord).where(
                StateChangeRecord.chat_id == chat_id,
                StateChangeRecord.status == ProposalStatus.APPROVED.value,
            )
        ).all()
        for change in changes:
            if self._canonical_identity(change.entity, change.key) == identity:
                change.status = ProposalStatus.REVERTED.value
        db.commit()
        self.rebuild_entries(db, chat_id)

    def rebuild_entries(self, db: Session, chat_id: str) -> None:
        """按已批准事件重建当前状态；state_changes 是真源，state_entries 是投影视图。"""
        changes = list(
            db.scalars(
                select(StateChangeRecord)
                .where(
                    StateChangeRecord.chat_id == chat_id,
                    StateChangeRecord.status == ProposalStatus.APPROVED.value,
                )
                .order_by(StateChangeRecord.resolved_at, StateChangeRecord.created_at)
            ).all()
        )
        projected: dict[tuple[str, str], dict[str, Any]] = {}
        for change in changes:
            identity = self._canonical_identity(change.entity, change.key)
            previous = projected.get(identity)
            next_value = json_loads(change.new_value_json)
            if previous is not None:
                next_value = self._merge_item_state(
                    identity[0],
                    identity[1],
                    json_loads(str(previous["value_json"])),
                    next_value,
                )
            projected[identity] = {
                "value_json": json_dumps(next_value),
                "source_message_id": change.source_message_id,
                "version": (int(previous["version"]) + 1) if previous else 1,
                "updated_at": change.resolved_at or change.created_at,
            }

        db.execute(delete(StateEntryRecord).where(StateEntryRecord.chat_id == chat_id))
        for (entity, key), value in projected.items():
            db.add(
                StateEntryRecord(
                    id=str(uuid4()),
                    chat_id=chat_id,
                    entity=entity,
                    key=key,
                    value_json=str(value["value_json"]),
                    source_message_id=(
                        str(value["source_message_id"])
                        if value["source_message_id"]
                        else None
                    ),
                    version=int(value["version"]),
                    updated_at=value["updated_at"],
                )
            )
        db.commit()

    @staticmethod
    def value(entry: StateEntryRecord) -> Any:
        return json_loads(entry.value_json)

    @classmethod
    def _canonical_identity(cls, entity: str, key: str) -> tuple[str, str]:
        canonical_entity = cls._canonical_entity(entity)
        return canonical_entity, cls._canonical_key(canonical_entity, key)

    @staticmethod
    def _canonical_entity(entity: str) -> str:
        cleaned = entity.strip()
        match = re.match(r"^(?:物品|item)\s*[:：]\s*(.+)$", cleaned, re.IGNORECASE)
        if not match:
            return cleaned
        # “形状”只描述外观，不应让同一件物品产生新的主键。
        name = re.sub(r"\s+|形状", "", match.group(1)).strip("：:")
        return f"物品:{name}"

    @staticmethod
    def _canonical_key(entity: str | None, key: str) -> str:
        cleaned = key.strip()
        if entity and entity.startswith("物品:") and cleaned.casefold() in {"status", "状态"}:
            return "状态"
        return cleaned

    @staticmethod
    def _merge_item_state(entity: str, key: str, previous: Any, current: Any) -> Any:
        if not entity.startswith("物品:") or key != "状态":
            return current
        if isinstance(previous, str) and isinstance(current, dict):
            merged = dict(current)
            if not str(merged.get("status", "")).strip():
                merged["status"] = previous
            return merged
        if isinstance(previous, dict) and isinstance(current, str):
            return {**previous, "status": current}
        if isinstance(previous, dict) and isinstance(current, dict):
            return {
                **previous,
                **{
                    item_key: item_value
                    for item_key, item_value in current.items()
                    if item_value not in (None, "")
                },
            }
        return current
