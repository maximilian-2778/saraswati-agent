"""把生成后提取的剧情 Delta 应用到可回放的故事状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import (
    NarrativeDeltaRecord,
    NpcRecord,
    RoleplayGraphEventRecord,
    StateChangeRecord,
    TimelineAnchorRecord,
)
from backend.services.narrative_delta import NarrativeDeltaPayload
from backend.services.roleplay_graph import RoleplayGraphService
from backend.services.state import StateService
from backend.services.timeline import timeline_service
from backend.services.variants import active_variant_clause
from backend.utils import json_dumps, json_loads


@dataclass(slots=True)
class DeltaApplyResult:
    state_changes: list[StateChangeRecord] = field(default_factory=list)
    scene_count: int = 0
    npc_count: int = 0
    timeline_count: int = 0
    skipped_count: int = 0


class NarrativeDeltaApplier:
    """补齐主模型遗漏的结构化变化，并跳过已经实时写入的内容。"""

    def __init__(self, state_service: StateService, graph_service: RoleplayGraphService) -> None:
        self.state_service = state_service
        self.graph_service = graph_service

    def apply(self, db: Session, record: NarrativeDeltaRecord) -> DeltaApplyResult:
        raw = json_loads(record.payload_json) or {}
        allowed = set(NarrativeDeltaPayload.model_fields)
        payload = NarrativeDeltaPayload.model_validate({key: value for key, value in raw.items() if key in allowed})
        result = DeltaApplyResult()
        source_id = record.assistant_message_id

        if payload.time_change.strip():
            before = len(timeline_service.list(db, record.chat_id))
            timeline_service.create(
                db, record.chat_id, payload.time_change,
                payload.summary or "本轮剧情时间发生变化", source_id,
            )
            if len(timeline_service.list(db, record.chat_id)) > before:
                result.timeline_count += 1
            else:
                result.skipped_count += 1

        for change in payload.scene_changes:
            existing = self._scene_by_path(db, record.chat_id, change.path)
            if existing and (not change.description or existing.description == change.description) and (
                not change.is_current or existing.is_current
            ):
                result.skipped_count += 1
                continue
            self.graph_service.upsert_scene_path(
                db, record.chat_id, change.path, change.description,
                change.is_current, source_id,
            )
            result.scene_count += 1

        for change in payload.npc_changes:
            location_id = None
            if change.location_path:
                location_id = self.graph_service.upsert_scene_path(
                    db, record.chat_id, change.location_path,
                    source_message_id=source_id,
                    record_event=False,
                ).id
            existing = db.scalar(select(NpcRecord).where(
                NpcRecord.chat_id == record.chat_id,
                NpcRecord.name == change.name.strip(),
            ))
            relations = [item.model_dump() for item in change.relations]
            intended = change.model_dump()
            intended["importance"] = change.importance or (existing.importance if existing else "supporting")
            intended["presence"] = change.presence or (existing.presence if existing else "unknown")
            if existing and self._npc_matches(existing, intended, relations, location_id):
                result.skipped_count += 1
                continue
            self.graph_service.upsert_npc(
                db, record.chat_id, change.name, change.description,
                change.relation_to_user, relations, intended["importance"],
                intended["presence"], location_id, change.outfit, change.condition,
                source_id,
            )
            result.npc_count += 1

        for item in payload.item_changes:
            value = {
                "owner": item.owner,
                "quantity": item.quantity,
                "status": item.status,
                "location": item.location,
            }
            current_item = next(iter(self.state_service.list_entries(
                db, record.chat_id, f"物品:{item.item}", "状态"
            )), None)
            if current_item is not None and isinstance(self.state_service.value(current_item), dict):
                value = {
                    **self.state_service.value(current_item),
                    **{key: item_value for key, item_value in value.items() if item_value != ""},
                }
            self._apply_state(
                db, record, result, f"物品:{item.item}", "状态", value,
                item.reason or f"本轮更新了物品“{item.item}”",
            )

        for number in payload.numbers:
            key = number.key
            if not key.strip():
                continue
            value: Any = {"value": number.value, "unit": number.unit} if number.unit else number.value
            self._apply_state(
                db, record, result, number.entity or "剧情数值", key, value,
                f"本轮正文明确出现数值：{number.name}",
            )

        for change in payload.state_changes:
            self._apply_state(
                db, record, result, change.entity, change.key,
                change.new_value, change.reason,
            )

        stored = payload.model_dump(mode="json")
        stored["application"] = {
            "scene_count": result.scene_count,
            "npc_count": result.npc_count,
            "timeline_count": result.timeline_count,
            "state_change_ids": list(dict.fromkeys(item.id for item in result.state_changes)),
            "skipped_count": result.skipped_count,
        }
        graph_events = list(db.scalars(
            select(RoleplayGraphEventRecord).where(
                RoleplayGraphEventRecord.chat_id == record.chat_id,
                RoleplayGraphEventRecord.source_message_id.in_([
                    record.user_message_id,
                    record.assistant_message_id,
                ]),
                active_variant_clause(RoleplayGraphEventRecord.variant_id),
            ).order_by(RoleplayGraphEventRecord.created_at)
        ).all())
        stored["graph_event_ids"] = [item.id for item in graph_events]
        stored["graph_changes"] = [json_loads(item.payload_json) for item in graph_events]
        record.payload_json = json_dumps(stored)
        record.updated_at = datetime.now(UTC)
        db.commit()
        return result

    def _apply_state(
        self,
        db: Session,
        record: NarrativeDeltaRecord,
        result: DeltaApplyResult,
        entity: str,
        key: str,
        value: Any,
        reason: str,
    ) -> None:
        current = next(iter(self.state_service.list_entries(db, record.chat_id, entity, key)), None)
        if current is not None and json_dumps(self.state_service.value(current)) == json_dumps(value):
            result.skipped_count += 1
            return
        result.state_changes.append(self.state_service.apply(
            db, record.chat_id, entity, key, value, reason,
            record.assistant_message_id,
            event_fingerprint=hashlib.sha256(json_dumps({
                "source": record.assistant_message_id,
                "entity": entity.strip().casefold(),
                "key": key.strip().casefold(),
                "value": value,
                "reason": reason.strip().casefold(),
            }).encode("utf-8")).hexdigest(),
        ))

    def _scene_by_path(self, db: Session, chat_id: str, path: list[str]):
        cleaned = [item.strip() for item in path if item.strip()]
        parent_id = None
        current = None
        for name in cleaned:
            current = self.graph_service.resolve_scene(db, chat_id, name, parent_id)
            if current is None:
                return None
            parent_id = current.id
        return current

    @staticmethod
    def _npc_matches(existing: NpcRecord, change: dict[str, Any], relations: list[dict[str, str]], location_id: str | None) -> bool:
        checks = [
            not change["description"] or existing.description == change["description"],
            not change["relation_to_user"] or existing.relation_to_user == change["relation_to_user"],
            not relations or (json_loads(existing.relations_json) or []) == relations,
            existing.importance == change["importance"],
            existing.presence == change["presence"],
            location_id is None or existing.location_scene_id == location_id,
            not change["outfit"] or existing.outfit == change["outfit"],
            not change["condition"] or existing.condition == change["condition"],
        ]
        return all(checks)
