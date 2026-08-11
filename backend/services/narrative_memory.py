"""面向长篇角色扮演的楼层记忆、摘要森林与上下文选择。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.llm import ModelClient
from backend.models import (
    MemoryRecord,
    MessageRecord,
    NarrativeLeafRecord,
    NarrativeSummaryNodeRecord,
    TimelineAnchorRecord,
)
from backend.schemas import MemoryKind
from backend.services.memory import MemoryService
from backend.services.variants import (
    active_variant_clause,
    active_variant_ids,
    selected_variant_id,
)
from backend.utils import clean_story_text, json_dumps, json_loads


@dataclass(slots=True)
class NarrativeNodeView:
    id: str
    node_type: str
    level: int
    content: str
    child_ids: list[str]
    source_message_id: str | None
    time_start: str | None
    time_end: str | None
    valid: bool
    active: bool
    created_at: datetime


@dataclass(slots=True)
class CoverageView:
    total_ai_floors: int
    summarized_floors: int
    valid_floors: int
    missing_message_ids: list[str]
    invalid_message_ids: list[str]
    selected_node_ids: list[str]

    @property
    def coverage_ratio(self) -> float:
        if not self.total_ai_floors:
            return 1.0
        return round(self.valid_floors / self.total_ai_floors, 4)


class NarrativeMemoryService:
    """把逐轮摘要组织成可验证、可降级的摘要森林。"""

    def __init__(self, settings: Settings, memory_service: MemoryService) -> None:
        self.settings = settings
        self.memory_service = memory_service

    async def process_turn(
        self,
        db: Session,
        model: ModelClient,
        chat_id: str,
        user_message: MessageRecord,
        assistant_message: MessageRecord,
    ) -> MemoryRecord | None:
        if not self.settings.auto_summary_enabled:
            return None

        user_text = clean_story_text(user_message.content)
        assistant_text = clean_story_text(assistant_message.content)
        transcript = f"用户：{user_text}\n角色：{assistant_text}"
        summary = await self._summarize(
            model, transcript, "楼层", self.settings.summary_detail_mode
        )
        memory = await self.memory_service.create(
            db,
            model,
            chat_id,
            MemoryKind.EPISODIC,
            f"[楼层摘要] {summary}",
            importance=0.5,
            source_message_id=assistant_message.id,
        )
        times = _extract_story_times(transcript)
        now = datetime.now(UTC)
        leaf = NarrativeLeafRecord(
            id=str(uuid4()),
            chat_id=chat_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            variant_id=selected_variant_id(db, assistant_message.id),
            memory_id=memory.id,
            source_hash=_source_hash(user_message.content, assistant_message.content),
            content=summary,
            detail_mode=self.settings.summary_detail_mode,
            time_start=times[0] if times else None,
            time_end=times[-1] if times else None,
            created_at=assistant_message.created_at,
            updated_at=now,
        )
        db.add(leaf)
        db.commit()

        self._create_timeline_anchor(
            db, chat_id, times, summary, assistant_message.id
        )
        await self._compress_available_roots(db, model, chat_id)
        return memory

    async def backfill_missing(
        self, db: Session, model: ModelClient, chat_id: str
    ) -> int:
        """按消息顺序补齐旧存档的漏摘楼层；已有有效叶子不会重复处理。"""
        self._prune_invalid_branches(db, chat_id)
        messages = list(
            db.scalars(
                select(MessageRecord)
                .where(MessageRecord.chat_id == chat_id)
                .order_by(MessageRecord.created_at)
            ).all()
        )
        existing = set(
            db.scalars(
                select(NarrativeLeafRecord.assistant_message_id).where(
                    NarrativeLeafRecord.chat_id == chat_id,
                    active_variant_clause(NarrativeLeafRecord.variant_id),
                )
            ).all()
        )
        latest_user: MessageRecord | None = None
        count = 0
        for message in messages:
            if message.role == "user":
                latest_user = message
            elif (
                message.role == "assistant"
                and message.id not in existing
                and latest_user is not None
            ):
                await self.process_turn(db, model, chat_id, latest_user, message)
                existing.add(message.id)
                count += 1
        return count

    async def summarize_floor(
        self, db: Session, model: ModelClient, chat_id: str,
        assistant_message_id: str, detail_mode: str = "brief", replace: bool = False,
    ) -> NarrativeNodeView:
        assistant = db.get(MessageRecord, assistant_message_id)
        if not assistant or assistant.chat_id != chat_id or assistant.role != "assistant":
            raise ValueError("指定楼层不是当前故事中的 AI 回复。")
        existing = db.scalar(select(NarrativeLeafRecord).where(
            NarrativeLeafRecord.chat_id == chat_id,
            NarrativeLeafRecord.assistant_message_id == assistant_message_id,
            active_variant_clause(NarrativeLeafRecord.variant_id),
        ))
        if existing and not replace and self._leaf_valid(existing, self._load(db, chat_id)[2]):
            return next(item for item in self.inspect_nodes(db, chat_id) if item.id == existing.id)
        user = db.scalar(select(MessageRecord).where(
            MessageRecord.chat_id == chat_id,
            MessageRecord.role == "user",
            MessageRecord.created_at <= assistant.created_at,
        ).order_by(MessageRecord.created_at.desc()))
        if not user:
            raise ValueError("该楼层之前没有可配对的用户消息。")
        if existing:
            self.delete_node(db, chat_id, existing.id)
        transcript = f"用户：{clean_story_text(user.content)}\n角色：{clean_story_text(assistant.content)}"
        summary = await self._summarize(model, transcript, "楼层", detail_mode)
        memory = await self.memory_service.create(
            db, model, chat_id, MemoryKind.EPISODIC, f"[楼层摘要] {summary}",
            importance=0.5, source_message_id=assistant.id,
        )
        times = _extract_story_times(transcript)
        now = datetime.now(UTC)
        leaf = NarrativeLeafRecord(
            id=str(uuid4()), chat_id=chat_id, user_message_id=user.id,
            assistant_message_id=assistant.id,
            variant_id=selected_variant_id(db, assistant.id), memory_id=memory.id,
            source_hash=_source_hash(user.content, assistant.content), content=summary,
            detail_mode=detail_mode, time_start=times[0] if times else None,
            time_end=times[-1] if times else None, created_at=assistant.created_at,
            updated_at=now,
        )
        db.add(leaf)
        db.commit()
        self._create_timeline_anchor(db, chat_id, times, summary, assistant.id)
        await self._compress_available_roots(db, model, chat_id)
        return next(item for item in self.inspect_nodes(db, chat_id) if item.id == leaf.id)

    async def update_node(
        self, db: Session, model: ModelClient, chat_id: str, node_id: str, content: str
    ) -> NarrativeNodeView:
        record = db.get(NarrativeLeafRecord, node_id) or db.get(NarrativeSummaryNodeRecord, node_id)
        if not record or record.chat_id != chat_id:
            raise ValueError("摘要节点不存在。")
        record.content = content.strip()
        record.updated_at = datetime.now(UTC)
        memory = db.get(MemoryRecord, record.memory_id) if record.memory_id else None
        if memory:
            memory.content = content.strip()
            memory.embedding_json = json_dumps(await model.embed(content.strip()))
        db.commit()
        return next(item for item in self.inspect_nodes(db, chat_id) if item.id == node_id)

    def delete_node(self, db: Session, chat_id: str, node_id: str) -> None:
        leaves, nodes, _messages = self._load(db, chat_id)
        records = {item.id: item for item in [*leaves, *nodes]}
        if node_id not in records:
            raise ValueError("摘要节点不存在。")
        doomed = {node_id}
        changed = True
        while changed:
            changed = False
            for node in nodes:
                if node.id not in doomed and any(child in doomed for child in _child_ids(node)):
                    doomed.add(node.id)
                    changed = True
        memory_ids = [records[item].memory_id for item in doomed if records[item].memory_id]
        db.execute(delete(NarrativeSummaryNodeRecord).where(NarrativeSummaryNodeRecord.id.in_(doomed)))
        db.execute(delete(NarrativeLeafRecord).where(NarrativeLeafRecord.id.in_(doomed)))
        if memory_ids:
            db.execute(delete(MemoryRecord).where(MemoryRecord.id.in_(memory_ids)))
        db.commit()

    async def rebuild_node(
        self, db: Session, model: ModelClient, chat_id: str, node_id: str,
        detail_mode: str = "brief",
    ) -> NarrativeNodeView | None:
        leaf = db.get(NarrativeLeafRecord, node_id)
        if leaf and leaf.chat_id == chat_id:
            assistant_id = leaf.assistant_message_id
            return await self.summarize_floor(
                db, model, chat_id, assistant_id, detail_mode, replace=True
            )
        node = db.get(NarrativeSummaryNodeRecord, node_id)
        if not node or node.chat_id != chat_id:
            raise ValueError("摘要节点不存在。")
        self.delete_node(db, chat_id, node_id)
        await self._compress_available_roots(db, model, chat_id)
        candidates = [item for item in self.inspect_nodes(db, chat_id) if item.node_type == "summary"]
        return candidates[-1] if candidates else None

    def invalid_memory_ids(self, db: Session, chat_id: str) -> set[str]:
        """返回所有不可信叶子及其祖先摘要所对应的向量索引 ID。"""
        leaves, nodes, messages = self._load(db, chat_id)
        invalid_ids = {
            leaf.id for leaf in leaves if not self._leaf_valid(leaf, messages)
        }
        present_ids = {leaf.id for leaf in leaves} | {node.id for node in nodes}
        invalid_ids.update(
            node.id
            for node in nodes
            if any(child not in present_ids for child in _child_ids(node))
        )
        changed = True
        while changed:
            changed = False
            for node in nodes:
                if node.id not in invalid_ids and any(
                    child in invalid_ids for child in _child_ids(node)
                ):
                    invalid_ids.add(node.id)
                    changed = True
        return {
            item.memory_id
            for item in [*leaves, *nodes]
            if item.id in invalid_ids and item.memory_id
        }

    async def merge_memories(
        self,
        db: Session,
        model: ModelClient,
        chat_id: str,
        records: list[MemoryRecord],
        detail_mode: str,
        label: str = "手动合并",
    ) -> MemoryRecord:
        source = "\n".join(record.content for record in records)
        summary = await self._summarize(model, source, label, detail_mode)
        return await self.memory_service.create(
            db,
            model,
            chat_id,
            MemoryKind.SUMMARY,
            f"[{label}] {summary}",
            importance=0.82,
            source_message_id=records[-1].source_message_id,
        )

    def selected_history(
        self,
        db: Session,
        chat_id: str,
        recent_message_ids: set[str],
    ) -> list[NarrativeNodeView]:
        """为窗口外剧情选择最高且完整的摘要；损坏分支自动下钻。"""
        leaves, nodes, messages = self._load(db, chat_id)
        valid_leaves = {
            leaf.id: leaf
            for leaf in leaves
            if self._leaf_valid(leaf, messages)
        }
        all_ids = set(valid_leaves) | {node.id for node in nodes}
        node_by_id = {node.id: node for node in nodes}
        referenced = {
            child_id
            for node in nodes
            for child_id in _child_ids(node)
            if child_id in all_ids
        }
        roots = [
            item_id
            for item_id in all_ids
            if item_id not in referenced
        ]
        intact_cache: dict[str, bool] = {}

        def intact(item_id: str, visiting: set[str] | None = None) -> bool:
            if item_id in valid_leaves:
                return True
            if item_id in intact_cache:
                return intact_cache[item_id]
            node = node_by_id.get(item_id)
            if not node:
                return False
            path = set(visiting or ())
            if item_id in path:
                return False
            path.add(item_id)
            children = _child_ids(node)
            result = bool(children) and all(
                child_id in all_ids and intact(child_id, path)
                for child_id in children
            )
            intact_cache[item_id] = result
            return result

        def descendant_leaves(item_id: str, seen: set[str] | None = None) -> list[NarrativeLeafRecord]:
            if item_id in valid_leaves:
                return [valid_leaves[item_id]]
            path = set(seen or ())
            if item_id in path:
                return []
            path.add(item_id)
            node = node_by_id.get(item_id)
            if not node:
                return []
            result: list[NarrativeLeafRecord] = []
            for child_id in _child_ids(node):
                result.extend(descendant_leaves(child_id, path))
            return result

        def eligible(leaf: NarrativeLeafRecord) -> bool:
            return leaf.assistant_message_id not in recent_message_ids

        chosen_ids: list[str] = []
        visited: set[str] = set()

        def visit(item_id: str) -> None:
            if item_id in visited:
                return
            visited.add(item_id)
            if item_id in valid_leaves:
                if eligible(valid_leaves[item_id]):
                    chosen_ids.append(item_id)
                return
            node = node_by_id.get(item_id)
            if not node:
                return
            descendants = descendant_leaves(item_id)
            if intact(item_id) and descendants and all(eligible(item) for item in descendants):
                chosen_ids.append(item_id)
                return
            for child_id in _child_ids(node):
                visit(child_id)

        for root_id in roots:
            visit(root_id)

        views = [
            self._to_view(item_id, valid_leaves, node_by_id, intact(item_id), True)
            for item_id in chosen_ids
        ]
        return sorted(views, key=lambda item: item.created_at)

    def inspect_nodes(
        self,
        db: Session,
        chat_id: str,
        recent_message_ids: set[str] | None = None,
    ) -> list[NarrativeNodeView]:
        leaves, nodes, messages = self._load(db, chat_id)
        valid_map = {leaf.id: self._leaf_valid(leaf, messages) for leaf in leaves}
        selected = {
            item.id
            for item in self.selected_history(db, chat_id, recent_message_ids or set())
        }
        views = [
            NarrativeNodeView(
                id=leaf.id,
                node_type="leaf",
                level=0,
                content=leaf.content,
                child_ids=[],
                source_message_id=leaf.assistant_message_id,
                time_start=leaf.time_start,
                time_end=leaf.time_end,
                valid=valid_map[leaf.id],
                active=leaf.id in selected,
                created_at=leaf.created_at,
            )
            for leaf in leaves
        ]
        node_map = {node.id: node for node in nodes}
        valid_leaf_records = {leaf.id: leaf for leaf in leaves if valid_map[leaf.id]}
        for node in nodes:
            views.append(
                self._to_view(
                    node.id,
                    valid_leaf_records,
                    node_map,
                    self._node_intact(node.id, valid_leaf_records, node_map),
                    node.id in selected,
                )
            )
        return sorted(views, key=lambda item: (item.created_at, item.level))

    def coverage(self, db: Session, chat_id: str) -> CoverageView:
        leaves, _nodes, messages = self._load(db, chat_id)
        assistants = [
            message for message in messages.values() if message.role == "assistant"
        ]
        by_message = {leaf.assistant_message_id: leaf for leaf in leaves}
        missing = [item.id for item in assistants if item.id not in by_message]
        invalid = [
            item.id
            for item in assistants
            if item.id in by_message and not self._leaf_valid(by_message[item.id], messages)
        ]
        selected = self.selected_history(db, chat_id, set())
        return CoverageView(
            total_ai_floors=len(assistants),
            summarized_floors=len(assistants) - len(missing),
            valid_floors=len(assistants) - len(missing) - len(invalid),
            missing_message_ids=missing,
            invalid_message_ids=invalid,
            selected_node_ids=[item.id for item in selected],
        )

    def _prune_invalid_branches(self, db: Session, chat_id: str) -> None:
        """重建前删除失效叶子及其祖先；完好旁支会重新成为可压缩的森林根。"""
        leaves, nodes, messages = self._load(db, chat_id)
        invalid_ids = {
            leaf.id for leaf in leaves if not self._leaf_valid(leaf, messages)
        }
        present_ids = {leaf.id for leaf in leaves} | {node.id for node in nodes}
        invalid_ids.update(
            node.id
            for node in nodes
            if any(child not in present_ids for child in _child_ids(node))
        )
        changed = True
        while changed:
            changed = False
            for node in nodes:
                if node.id not in invalid_ids and any(
                    child in invalid_ids for child in _child_ids(node)
                ):
                    invalid_ids.add(node.id)
                    changed = True
        if not invalid_ids:
            return
        memory_ids = [
            item.memory_id
            for item in [*leaves, *nodes]
            if item.id in invalid_ids and item.memory_id
        ]
        db.execute(
            delete(NarrativeSummaryNodeRecord).where(
                NarrativeSummaryNodeRecord.id.in_(invalid_ids)
            )
        )
        db.execute(
            delete(NarrativeLeafRecord).where(NarrativeLeafRecord.id.in_(invalid_ids))
        )
        if memory_ids:
            db.execute(delete(MemoryRecord).where(MemoryRecord.id.in_(memory_ids)))
        db.commit()

    async def _compress_available_roots(
        self, db: Session, model: ModelClient, chat_id: str
    ) -> None:
        """逐层消费尚未被父节点收纳的同级根，形成森林而不是固定切片。"""
        source_level = 0
        while source_level < 8:
            leaves = list(
                db.scalars(
                    select(NarrativeLeafRecord)
                    .where(
                        NarrativeLeafRecord.chat_id == chat_id,
                        active_variant_clause(NarrativeLeafRecord.variant_id),
                    )
                    .order_by(NarrativeLeafRecord.created_at)
                ).all()
            )
            nodes = list(
                db.scalars(
                    select(NarrativeSummaryNodeRecord)
                    .where(NarrativeSummaryNodeRecord.chat_id == chat_id)
                    .order_by(NarrativeSummaryNodeRecord.created_at)
                ).all()
            )
            selected_variants = active_variant_ids(db, chat_id)
            nodes = [
                node for node in nodes
                if set(json_loads(node.variant_ids_json) or []).issubset(selected_variants)
            ]
            referenced = {child for node in nodes for child in _child_ids(node)}
            candidates: list[NarrativeLeafRecord | NarrativeSummaryNodeRecord]
            if source_level == 0:
                candidates = [leaf for leaf in leaves if leaf.id not in referenced]
                group_size = self.settings.chapter_summary_size
            else:
                candidates = [
                    node
                    for node in nodes
                    if node.level == source_level and node.id not in referenced
                ]
                group_size = self.settings.arc_summary_size
            if len(candidates) < group_size:
                source_level += 1
                continue

            group = candidates[:group_size]
            label = "章节" if source_level == 0 else f"篇章 L{source_level + 1}"
            content = await self._summarize(
                model,
                "\n".join(item.content for item in group),
                label,
                self.settings.summary_detail_mode if source_level == 0 else "brief",
            )
            prefix = "章节总结" if source_level == 0 else f"篇章概览 L{source_level + 1}"
            source_message_id = self._last_source_message_id(group, leaves, nodes)
            variant_ids = self._variant_ids(group, leaves, nodes)
            memory = await self.memory_service.create(
                db,
                model,
                chat_id,
                MemoryKind.SUMMARY,
                f"[{prefix}] {content}",
                importance=min(0.84 + source_level * 0.05, 0.98),
                source_message_id=source_message_id,
                variant_ids=variant_ids,
            )
            now = datetime.now(UTC)
            db.add(
                NarrativeSummaryNodeRecord(
                    id=str(uuid4()),
                    chat_id=chat_id,
                    level=source_level + 1,
                    content=content,
                    child_refs_json=json_dumps([item.id for item in group]),
                    variant_ids_json=json_dumps(sorted(variant_ids)),
                    memory_id=memory.id,
                    time_start=next((item.time_start for item in group if item.time_start), None),
                    time_end=next((item.time_end for item in reversed(group) if item.time_end), None),
                    created_at=now,
                    updated_at=now,
                )
            )
            db.commit()
            # 新节点可能立刻凑成更高层；重新从当前层检查剩余根。

    @staticmethod
    async def _summarize(
        model: ModelClient, content: str, level: str, detail_mode: str
    ) -> str:
        detail = (
            "保留关键动作、人物关系、时间、物品、地点、承诺、悬念与情绪转折。"
            if detail_mode == "detailed"
            else "只保留会影响后续剧情的事件、事实、关系、承诺和状态变化。"
        )
        reply = await model.complete(
            [
                {
                    "role": "system",
                    "content": (
                        f"生成剧情摘要。当前是{level}层级。{detail}"
                        "不得添加原文没有的信息，使用客观第三人称，避免文学扩写。"
                    ),
                },
                {"role": "user", "content": content[:20_000]},
            ]
        )
        return (reply.content or "未能生成摘要。 ").strip()

    @staticmethod
    def _create_timeline_anchor(
        db: Session,
        chat_id: str,
        times: list[str],
        summary: str,
        source_message_id: str,
    ) -> None:
        if not times:
            return
        label = times[0] if len(times) == 1 else f"{times[0]} → {times[-1]}"
        from backend.services.timeline import timeline_service
        timeline_service.create(db, chat_id, label, summary[:5_000], source_message_id)

    @staticmethod
    def _leaf_valid(
        leaf: NarrativeLeafRecord, messages: dict[str, MessageRecord]
    ) -> bool:
        user = messages.get(leaf.user_message_id)
        assistant = messages.get(leaf.assistant_message_id)
        return bool(
            user
            and assistant
            and leaf.source_hash == _source_hash(user.content, assistant.content)
        )

    @staticmethod
    def _load(
        db: Session, chat_id: str
    ) -> tuple[
        list[NarrativeLeafRecord],
        list[NarrativeSummaryNodeRecord],
        dict[str, MessageRecord],
    ]:
        leaves = list(
            db.scalars(
                select(NarrativeLeafRecord)
                .where(
                    NarrativeLeafRecord.chat_id == chat_id,
                    active_variant_clause(NarrativeLeafRecord.variant_id),
                )
                .order_by(NarrativeLeafRecord.created_at)
            ).all()
        )
        nodes = list(
            db.scalars(
                select(NarrativeSummaryNodeRecord)
                .where(NarrativeSummaryNodeRecord.chat_id == chat_id)
                .order_by(NarrativeSummaryNodeRecord.created_at)
            ).all()
        )
        selected_variants = active_variant_ids(db, chat_id)
        nodes = [
            node for node in nodes
            if set(json_loads(node.variant_ids_json) or []).issubset(selected_variants)
        ]
        messages = {
            item.id: item
            for item in db.scalars(
                select(MessageRecord).where(MessageRecord.chat_id == chat_id)
            ).all()
        }
        return leaves, nodes, messages

    @staticmethod
    def _variant_ids(
        group: list[NarrativeLeafRecord | NarrativeSummaryNodeRecord],
        leaves: list[NarrativeLeafRecord],
        nodes: list[NarrativeSummaryNodeRecord],
    ) -> set[str]:
        leaf_map = {item.id: item for item in leaves}
        node_map = {item.id: item for item in nodes}
        result: set[str] = set()

        def collect(item: NarrativeLeafRecord | NarrativeSummaryNodeRecord) -> None:
            if isinstance(item, NarrativeLeafRecord):
                result.add(item.variant_id)
                return
            stored = set(json_loads(item.variant_ids_json) or [])
            if stored:
                result.update(stored)
                return
            for child_id in _child_ids(item):
                child = leaf_map.get(child_id) or node_map.get(child_id)
                if child:
                    collect(child)

        for item in group:
            collect(item)
        return result

    @staticmethod
    def _node_intact(
        item_id: str,
        leaves: dict[str, NarrativeLeafRecord],
        nodes: dict[str, NarrativeSummaryNodeRecord],
        visiting: set[str] | None = None,
    ) -> bool:
        if item_id in leaves:
            return True
        node = nodes.get(item_id)
        if not node:
            return False
        path = set(visiting or ())
        if item_id in path:
            return False
        path.add(item_id)
        children = _child_ids(node)
        return bool(children) and all(
            NarrativeMemoryService._node_intact(child, leaves, nodes, path)
            for child in children
        )

    @staticmethod
    def _to_view(
        item_id: str,
        leaves: dict[str, NarrativeLeafRecord],
        nodes: dict[str, NarrativeSummaryNodeRecord],
        valid: bool,
        active: bool,
    ) -> NarrativeNodeView:
        leaf = leaves.get(item_id)
        if leaf:
            return NarrativeNodeView(
                id=leaf.id,
                node_type="leaf",
                level=0,
                content=leaf.content,
                child_ids=[],
                source_message_id=leaf.assistant_message_id,
                time_start=leaf.time_start,
                time_end=leaf.time_end,
                valid=valid,
                active=active,
                created_at=leaf.created_at,
            )
        node = nodes[item_id]
        return NarrativeNodeView(
            id=node.id,
            node_type="summary",
            level=node.level,
            content=node.content,
            child_ids=_child_ids(node),
            source_message_id=None,
            time_start=node.time_start,
            time_end=node.time_end,
            valid=valid,
            active=active,
            created_at=node.created_at,
        )

    @staticmethod
    def _last_source_message_id(
        group: list[NarrativeLeafRecord | NarrativeSummaryNodeRecord],
        leaves: list[NarrativeLeafRecord],
        nodes: list[NarrativeSummaryNodeRecord],
    ) -> str | None:
        leaf_map = {item.id: item for item in leaves}
        node_map = {item.id: item for item in nodes}

        def last(ref: NarrativeLeafRecord | NarrativeSummaryNodeRecord) -> str | None:
            if isinstance(ref, NarrativeLeafRecord):
                return ref.assistant_message_id
            children = _child_ids(ref)
            if not children:
                return None
            child_id = children[-1]
            child = leaf_map.get(child_id) or node_map.get(child_id)
            return last(child) if child else None

        return last(group[-1]) if group else None


def _child_ids(node: NarrativeSummaryNodeRecord) -> list[str]:
    value = json_loads(node.child_refs_json)
    return [str(item) for item in value] if isinstance(value, list) else []


def _source_hash(user_text: str, assistant_text: str) -> str:
    normalized = "\n---\n".join(
        re.sub(r"\s+", " ", text).strip() for text in (user_text, assistant_text)
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_TIME_PATTERN = re.compile(
    r"第[一二三四五六七八九十百零〇\d]+(?:天|日|周|月|年)|"
    r"(?:今天|昨日|昨天|明天|次日|翌日|当晚|数日前|数月前|数年前|"
    r"清晨|黎明|早晨|上午|中午|下午|傍晚|黄昏|夜晚|午夜)|"
    r"(?:\d{2,4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?(?:\s+\d{1,2}:\d{2})?)"
)


def _extract_story_times(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in _TIME_PATTERN.finditer(text)))
