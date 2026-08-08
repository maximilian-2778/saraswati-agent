"""场景树与 NPC 关系图服务。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.models import MessageRecord, NpcRecord, RoleplayGraphEventRecord, SceneNodeRecord
from backend.services.narrative_delta import message_hash
from backend.utils import json_dumps, json_loads


class RoleplayGraphService:
    """维护叙事结构，并选择本轮真正需要注入的节点。"""

    def list_scenes(self, db: Session, chat_id: str) -> list[SceneNodeRecord]:
        return list(
            db.scalars(
                select(SceneNodeRecord)
                .where(SceneNodeRecord.chat_id == chat_id)
                .order_by(SceneNodeRecord.created_at)
            ).all()
        )

    def list_npcs(self, db: Session, chat_id: str) -> list[NpcRecord]:
        return list(
            db.scalars(
                select(NpcRecord)
                .where(NpcRecord.chat_id == chat_id)
                .order_by(NpcRecord.updated_at.desc())
            ).all()
        )

    def upsert_scene(
        self,
        db: Session,
        chat_id: str,
        name: str,
        parent_id: str | None = None,
        description: str = "",
        is_current: bool = False,
        source_message_id: str | None = None,
        scene_id: str | None = None,
        record_event: bool = True,
    ) -> SceneNodeRecord:
        parent = self._scene_parent(db, chat_id, parent_id)
        record = db.get(SceneNodeRecord, scene_id) if scene_id else None
        if scene_id and not record:
            raise ValueError("场景不存在")
        if record and record.chat_id != chat_id:
            raise ValueError("场景不属于当前故事")
        if not record:
            record = db.scalar(
                select(SceneNodeRecord).where(
                    SceneNodeRecord.chat_id == chat_id,
                    SceneNodeRecord.parent_id == parent_id,
                    SceneNodeRecord.name == name.strip(),
                )
            )
        now = datetime.now(UTC)
        if not record:
            record = SceneNodeRecord(
                id=str(uuid4()),
                chat_id=chat_id,
                parent_id=parent.id if parent else None,
                name=name.strip(),
                description=description.strip(),
                is_current=False,
                source_message_id=source_message_id,
                created_at=now,
                updated_at=now,
            )
            db.add(record)
        else:
            if parent and self._would_cycle(db, record.id, parent.id):
                raise ValueError("场景父级不能指向自身或后代")
            record.parent_id = parent.id if parent else None
            record.name = name.strip()
            if description.strip():
                record.description = description.strip()
            record.source_message_id = source_message_id or record.source_message_id
            record.updated_at = now
        if is_current:
            for item in self.list_scenes(db, chat_id):
                item.is_current = item.id == record.id
            record.is_current = True
        db.commit()
        db.refresh(record)
        if record_event:
            records = self.list_scenes(db, chat_id)
            self._record_event(
                db,
                chat_id,
                "scene_upsert",
                {
                    "path": self.scene_path(record, {item.id: item for item in records}),
                    "description": record.description,
                    "is_current": record.is_current,
                },
                source_message_id,
            )
        return record

    def upsert_scene_path(
        self,
        db: Session,
        chat_id: str,
        path: list[str],
        description: str = "",
        is_current: bool = False,
        source_message_id: str | None = None,
        record_event: bool = True,
    ) -> SceneNodeRecord:
        parent_id: str | None = None
        current: SceneNodeRecord | None = None
        cleaned = [item.strip() for item in path if item.strip()]
        if not cleaned:
            raise ValueError("场景路径不能为空")
        for index, name in enumerate(cleaned):
            current = self.upsert_scene(
                db,
                chat_id,
                name,
                parent_id,
                description if index == len(cleaned) - 1 else "",
                is_current and index == len(cleaned) - 1,
                source_message_id,
                record_event=record_event,
            )
            parent_id = current.id
        assert current is not None
        return current

    def upsert_npc(
        self,
        db: Session,
        chat_id: str,
        name: str,
        description: str = "",
        relation_to_user: str = "",
        relations: list[dict[str, str]] | None = None,
        importance: str = "supporting",
        presence: str = "away",
        location_scene_id: str | None = None,
        outfit: str = "",
        condition: str = "",
        source_message_id: str | None = None,
        npc_id: str | None = None,
        record_event: bool = True,
    ) -> NpcRecord:
        if location_scene_id:
            self._scene_parent(db, chat_id, location_scene_id)
        record = db.get(NpcRecord, npc_id) if npc_id else None
        if npc_id and not record:
            raise ValueError("NPC 不存在")
        if record and record.chat_id != chat_id:
            raise ValueError("NPC 不属于当前故事")
        if not record:
            record = db.scalar(
                select(NpcRecord).where(
                    NpcRecord.chat_id == chat_id, NpcRecord.name == name.strip()
                )
            )
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "name": name.strip(),
            "description": description.strip(),
            "relation_to_user": relation_to_user.strip(),
            "relations_json": json_dumps(relations or []),
            "importance": importance if importance in {"core", "supporting", "minor"} else "supporting",
            "presence": presence if presence in {"present", "nearby", "away", "unknown"} else "unknown",
            "location_scene_id": location_scene_id,
            "outfit": outfit.strip(),
            "condition": condition.strip(),
            "source_message_id": source_message_id,
            "updated_at": now,
        }
        if not record:
            record = NpcRecord(id=str(uuid4()), chat_id=chat_id, created_at=now, **values)
            db.add(record)
        else:
            for key, value in values.items():
                if key in {"description", "relation_to_user", "outfit", "condition"} and not value:
                    continue
                if key == "relations_json" and not relations:
                    continue
                if key == "source_message_id" and not value:
                    continue
                setattr(record, key, value)
        db.commit()
        db.refresh(record)
        if record_event:
            scenes = self.list_scenes(db, chat_id)
            scene_by_id = {item.id: item for item in scenes}
            location = scene_by_id.get(record.location_scene_id or "")
            self._record_event(
                db,
                chat_id,
                "npc_upsert",
                {
                    "name": record.name,
                    "description": record.description,
                    "relation_to_user": record.relation_to_user,
                    "relations": json_loads(record.relations_json) or [],
                    "importance": record.importance,
                    "presence": record.presence,
                    "location_path": self.scene_path(location, scene_by_id) if location else [],
                    "outfit": record.outfit,
                    "condition": record.condition,
                },
                source_message_id,
            )
        return record

    def rebuild_projections(self, db: Session, chat_id: str) -> dict[str, int]:
        """丢弃当前投影，仅按来源仍有效的历史事件重放。"""
        events = list(
            db.scalars(
                select(RoleplayGraphEventRecord)
                .where(RoleplayGraphEventRecord.chat_id == chat_id)
                .order_by(RoleplayGraphEventRecord.created_at, RoleplayGraphEventRecord.id)
            ).all()
        )
        source_ids = {event.source_message_id for event in events if event.source_message_id}
        messages = db.scalars(select(MessageRecord).where(MessageRecord.id.in_(source_ids))).all()
        source_by_id = {message.id: message for message in messages}
        valid_events = [
            event for event in events
            if event.source_message_id is None
            or (
                event.source_message_id in source_by_id
                and event.source_hash == message_hash(source_by_id[event.source_message_id].content)
            )
        ]
        db.execute(delete(NpcRecord).where(NpcRecord.chat_id == chat_id))
        db.execute(delete(SceneNodeRecord).where(SceneNodeRecord.chat_id == chat_id))
        db.commit()
        for event in valid_events:
            payload = json_loads(event.payload_json) or {}
            if event.event_type == "scene_upsert":
                self.upsert_scene_path(
                    db,
                    chat_id,
                    list(payload.get("path") or []),
                    str(payload.get("description") or ""),
                    bool(payload.get("is_current")),
                    event.source_message_id,
                    record_event=False,
                )
            elif event.event_type == "npc_upsert":
                location_id = None
                location_path = list(payload.get("location_path") or [])
                if location_path:
                    location_id = self.upsert_scene_path(
                        db, chat_id, location_path, record_event=False
                    ).id
                self.upsert_npc(
                    db,
                    chat_id,
                    str(payload.get("name") or ""),
                    str(payload.get("description") or ""),
                    str(payload.get("relation_to_user") or ""),
                    list(payload.get("relations") or []),
                    str(payload.get("importance") or "supporting"),
                    str(payload.get("presence") or "unknown"),
                    location_id,
                    str(payload.get("outfit") or ""),
                    str(payload.get("condition") or ""),
                    event.source_message_id,
                    record_event=False,
                )
            elif event.event_type == "scene_delete":
                scene = self._find_scene_by_path(db, chat_id, list(payload.get("path") or []))
                if scene:
                    db.delete(scene)
                    db.commit()
            elif event.event_type == "npc_delete":
                npc = db.scalar(
                    select(NpcRecord).where(
                        NpcRecord.chat_id == chat_id,
                        NpcRecord.name == str(payload.get("name") or ""),
                    )
                )
                if npc:
                    db.delete(npc)
                    db.commit()
        return {"total_events": len(events), "replayed_events": len(valid_events)}

    def delete_scene(self, db: Session, chat_id: str, scene_id: str) -> None:
        scene = db.get(SceneNodeRecord, scene_id)
        if not scene or scene.chat_id != chat_id:
            raise ValueError("场景不存在")
        records = self.list_scenes(db, chat_id)
        path = self.scene_path(scene, {item.id: item for item in records})
        self._record_event(db, chat_id, "scene_delete", {"path": path}, None)
        db.delete(scene)
        db.commit()

    def delete_npc(self, db: Session, chat_id: str, npc_id: str) -> None:
        npc = db.get(NpcRecord, npc_id)
        if not npc or npc.chat_id != chat_id:
            raise ValueError("NPC 不存在")
        self._record_event(db, chat_id, "npc_delete", {"name": npc.name}, None)
        db.delete(npc)
        db.commit()

    @staticmethod
    def _record_event(
        db: Session,
        chat_id: str,
        event_type: str,
        payload: dict[str, Any],
        source_message_id: str | None,
    ) -> None:
        source = db.get(MessageRecord, source_message_id) if source_message_id else None
        db.add(
            RoleplayGraphEventRecord(
                id=str(uuid4()),
                chat_id=chat_id,
                event_type=event_type,
                payload_json=json_dumps(payload),
                source_message_id=source_message_id,
                source_hash=message_hash(source.content) if source else None,
                created_at=datetime.now(UTC),
            )
        )
        db.commit()

    def _find_scene_by_path(
        self, db: Session, chat_id: str, path: list[str]
    ) -> SceneNodeRecord | None:
        records = self.list_scenes(db, chat_id)
        by_id = {item.id: item for item in records}
        return next(
            (item for item in records if self.scene_path(item, by_id) == path),
            None,
        )

    def context_text(self, db: Session, chat_id: str, query: str) -> str:
        scenes = self.list_scenes(db, chat_id)
        scene_by_id = {item.id: item for item in scenes}
        current = next((item for item in scenes if item.is_current), None)
        chunks: list[str] = []
        if current:
            path = self.scene_path(current, scene_by_id)
            chunks.append(f"[当前场景] {' > '.join(path)}：{current.description or '暂无补充描述'}")

        normalized = query.casefold()
        selected = []
        for npc in self.list_npcs(db, chat_id):
            relevant = (
                npc.importance == "core"
                or npc.presence in {"present", "nearby"}
                or npc.name.casefold() in normalized
            )
            if relevant and len(selected) < 12:
                selected.append(npc)
        if selected:
            chunks.append("[本轮相关 NPC]")
            for npc in selected:
                location = scene_by_id.get(npc.location_scene_id or "")
                relations = json_loads(npc.relations_json) or []
                relation_text = "；".join(
                    f"与{item.get('target')}：{item.get('relation')}"
                    for item in relations
                    if isinstance(item, dict) and item.get("target") and item.get("relation")
                )
                details = [
                    npc.description,
                    f"与玩家：{npc.relation_to_user}" if npc.relation_to_user else "",
                    relation_text,
                    f"状态：{npc.condition}" if npc.condition else "",
                    f"穿着：{npc.outfit}" if npc.outfit else "",
                    f"位置：{location.name}" if location else "",
                    f"在场级别：{npc.presence}",
                ]
                chunks.append(f"- {npc.name}｜" + "；".join(item for item in details if item))
        return "\n".join(chunks)

    @staticmethod
    def scene_path(
        scene: SceneNodeRecord, by_id: dict[str, SceneNodeRecord]
    ) -> list[str]:
        path = [scene.name]
        parent_id = scene.parent_id
        visited = {scene.id}
        while parent_id and parent_id not in visited and parent_id in by_id:
            visited.add(parent_id)
            parent = by_id[parent_id]
            path.append(parent.name)
            parent_id = parent.parent_id
        return list(reversed(path))

    @staticmethod
    def _scene_parent(
        db: Session, chat_id: str, parent_id: str | None
    ) -> SceneNodeRecord | None:
        if not parent_id:
            return None
        parent = db.get(SceneNodeRecord, parent_id)
        if not parent or parent.chat_id != chat_id:
            raise ValueError("场景父级不存在")
        return parent

    @staticmethod
    def _would_cycle(db: Session, scene_id: str, parent_id: str) -> bool:
        cursor = db.get(SceneNodeRecord, parent_id)
        visited: set[str] = set()
        while cursor and cursor.id not in visited:
            if cursor.id == scene_id:
                return True
            visited.add(cursor.id)
            cursor = db.get(SceneNodeRecord, cursor.parent_id) if cursor.parent_id else None
        return False
