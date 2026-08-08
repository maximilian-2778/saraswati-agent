"""结构化世界状态与人工审批账本。"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.models import StateChangeRecord, StateEntryRecord
from backend.schemas import ProposalStatus
from backend.utils import json_dumps, json_loads


class StateService:
    """查询当前状态、创建变更建议，并在批准后更新事实状态。"""

    def list_entries(
        self,
        db: Session,
        chat_id: str,
        entity: str | None = None,
        key: str | None = None,
    ) -> list[StateEntryRecord]:
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
    ) -> StateChangeRecord:
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
            source_message_id=source_message_id,
            status=ProposalStatus.PENDING.value,
            created_at=datetime.now(UTC),
            resolved_at=None,
        )
        db.add(record)
        db.commit()
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
            identity = (change.entity, change.key)
            previous = projected.get(identity)
            projected[identity] = {
                "value_json": change.new_value_json,
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
