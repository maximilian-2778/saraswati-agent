"""故事级世界推演：状态链、消息指纹校验和模型驱动演化。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.llm import ModelClient, ModelProviderError
from backend.models import (
    MessageRecord,
    NpcRecord,
    SceneNodeRecord,
    StoryWorldBookRecord,
    WorldEngineConfigRecord,
    WorldEvolutionRecord,
)
from backend.services.narrative_delta import source_hash
from backend.utils import json_dumps, json_loads


class WorldFaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", max_length=64)
    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=2_000)
    status: Literal["rising", "stable", "strained", "declining", "dissolved"] = "stable"
    relation: Literal["allied", "friendly", "neutral", "cold", "hostile"] = "neutral"
    influence: int = Field(default=1, ge=1, le=5)
    latest_action: str = Field(default="", max_length=1_000)


class WorldEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", max_length=64)
    name: str = Field(max_length=160)
    type: Literal["conflict", "progress"] = "conflict"
    stage: Literal["seed", "developing", "approaching", "resolved", "failed", "dissipated"] = "seed"
    level: int = Field(default=1, ge=1, le=4)
    summary: str = Field(default="", max_length=2_000)
    participants: list[str] = Field(default_factory=list, max_length=20)
    location: str = Field(default="", max_length=200)
    next_pressure: str = Field(default="", max_length=1_000)
    active: bool = True


class WorldRumor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", max_length=64)
    topic: str = Field(max_length=160)
    type: Literal["announcement", "report", "rumor", "sentiment"] = "rumor"
    level: int = Field(default=1, ge=1, le=4)
    content: str = Field(default="", max_length=2_000)
    scope: str = Field(default="", max_length=300)
    source: str = Field(default="", max_length=300)
    active: bool = True


class WorldTrend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", max_length=64)
    name: str = Field(max_length=160)
    description: str = Field(default="", max_length=2_000)
    direction: Literal["rising", "stable", "falling"] = "stable"


class WorldState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round: int = Field(default=0, ge=0)
    digest: str = Field(default="世界尚未开始推演。", max_length=4_000)
    factions: list[WorldFaction] = Field(default_factory=list, max_length=20)
    events: list[WorldEvent] = Field(default_factory=list, max_length=30)
    rumors: list[WorldRumor] = Field(default_factory=list, max_length=30)
    trends: list[WorldTrend] = Field(default_factory=list, max_length=12)


class WorldEngineSnapshot(BaseModel):
    state: WorldState
    auto_evolve: bool = False
    records_count: int = 0
    stale_count: int = 0
    updated_at: datetime | None = None


class WorldEngineService:
    """以不可变快照构成世界状态链；断裂分支自动停止生效。"""

    def snapshot(self, db: Session, chat_id: str) -> WorldEngineSnapshot:
        records = list(db.scalars(
            select(WorldEvolutionRecord)
            .where(WorldEvolutionRecord.chat_id == chat_id)
            .order_by(WorldEvolutionRecord.sequence)
        ).all())
        message_ids = {
            value for record in records
            for value in (record.user_message_id, record.assistant_message_id)
            if value
        }
        messages = db.scalars(select(MessageRecord).where(MessageRecord.id.in_(message_ids))).all() if message_ids else []
        by_id = {item.id: item for item in messages}
        state = WorldState()
        stale_count = 0
        updated_at: datetime | None = None
        for record in records:
            valid_source = self._valid_source(record, by_id)
            valid_parent = record.before_hash == state_hash(state)
            if not valid_source or not valid_parent:
                stale_count += 1
                continue
            try:
                state = WorldState.model_validate(json_loads(record.after_state_json))
            except (ValidationError, TypeError, ValueError):
                stale_count += 1
                continue
            updated_at = record.created_at
        config = db.get(WorldEngineConfigRecord, chat_id)
        return WorldEngineSnapshot(
            state=state,
            auto_evolve=bool(config and config.auto_evolve),
            records_count=len(records),
            stale_count=stale_count,
            updated_at=updated_at,
        )

    def set_auto_evolve(self, db: Session, chat_id: str, enabled: bool) -> WorldEngineSnapshot:
        record = db.get(WorldEngineConfigRecord, chat_id)
        now = datetime.now(UTC)
        if record is None:
            record = WorldEngineConfigRecord(chat_id=chat_id, auto_evolve=enabled, updated_at=now)
            db.add(record)
        else:
            record.auto_evolve = enabled
            record.updated_at = now
        db.commit()
        return self.snapshot(db, chat_id)

    def save_manual(self, db: Session, chat_id: str, state: WorldState) -> WorldEngineSnapshot:
        current = self.snapshot(db, chat_id).state
        normalized = normalize_state(state, current.round)
        self._append(db, chat_id, current, normalized, "edit")
        return self.snapshot(db, chat_id)

    async def evolve(
        self,
        db: Session,
        model: ModelClient,
        chat_id: str,
        user_message: MessageRecord | None = None,
        assistant_message: MessageRecord | None = None,
        mode: str = "manual",
    ) -> WorldEngineSnapshot:
        if assistant_message is not None and mode == "auto":
            existing = db.scalar(select(WorldEvolutionRecord.id).where(
                WorldEvolutionRecord.chat_id == chat_id,
                WorldEvolutionRecord.assistant_message_id == assistant_message.id,
            ))
            if existing:
                return self.snapshot(db, chat_id)
        before = self.snapshot(db, chat_id).state
        supporting = self._supporting_context(db, chat_id)
        next_state = await self._generate(
            model,
            before,
            user_message.content if user_message else "",
            assistant_message.content if assistant_message else "",
            supporting,
        )
        next_state = normalize_state(next_state, before.round + 1)
        self._append(
            db,
            chat_id,
            before,
            next_state,
            mode,
            user_message,
            assistant_message,
        )
        return self.snapshot(db, chat_id)

    def context_text(self, db: Session, chat_id: str) -> str:
        state = self.snapshot(db, chat_id).state
        if state.round == 0:
            return ""
        lines = [f"世界轮次：{state.round}", f"世界概况：{state.digest}"]
        active_events = [item for item in state.events if item.active]
        if active_events:
            lines.append("持续事件：" + "；".join(
                f"{item.name}（{item.stage}，Lv{item.level}）：{item.summary}"
                for item in active_events[:8]
            ))
        if state.factions:
            lines.append("主要势力：" + "；".join(
                f"{item.name}（{item.status}/{item.relation}）：{item.latest_action or item.description}"
                for item in state.factions[:8]
            ))
        visible_rumors = [item for item in state.rumors if item.active and item.level >= 2]
        if visible_rumors:
            lines.append("正在传播的信息：" + "；".join(
                f"{item.topic}：{item.content}" for item in visible_rumors[:8]
            ))
        return "\n".join(lines)

    async def _generate(
        self,
        model: ModelClient,
        before: WorldState,
        user_text: str,
        assistant_text: str,
        supporting: str,
    ) -> WorldState:
        system = (
            "你负责在长篇角色扮演中维护玩家视野之外仍会发展的世界。"
            "根据本轮已发生的剧情和既有世界状态，返回下一轮完整世界状态。"
            "保持已有 id，不要把人物和地点档案复制成势力；没有充分依据时维持原状。"
            "事件必须能够跨轮持续，传闻必须有明确传播来源；不得替玩家行动，不得泄露角色未知的秘密。"
            "digest 应简洁概括当前宏观局势。只返回符合 JSON Schema 的对象。"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": (
                f"【当前世界状态】\n{before.model_dump_json(indent=2)}\n\n"
                f"【已有设定与结构化资料】\n{supporting or '暂无'}\n\n"
                f"【本轮玩家行动】\n{user_text or '手动推进，没有新增玩家行动'}\n\n"
                f"【本轮剧情结果】\n{assistant_text or '请让既有事件与势力自然向前发展一轮'}"
            )},
        ]
        structured = getattr(model, "complete_structured", None)
        if structured is not None:
            try:
                value = await structured(messages, "world_evolution", WorldState.model_json_schema())
                return WorldState.model_validate(value)
            except (ModelProviderError, ValidationError, TypeError, ValueError):
                pass
        reply = await model.complete(messages, None)
        match = re.search(r"\{.*\}", reply.content or "", re.DOTALL)
        if not match:
            raise ModelProviderError("世界推演没有返回可解析的状态")
        try:
            return WorldState.model_validate(json.loads(match.group(0)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ModelProviderError(f"世界推演返回格式无效：{exc}") from exc

    def _append(
        self,
        db: Session,
        chat_id: str,
        before: WorldState,
        after: WorldState,
        mode: str,
        user: MessageRecord | None = None,
        assistant: MessageRecord | None = None,
    ) -> None:
        sequence = int(db.scalar(select(func.max(WorldEvolutionRecord.sequence)).where(
            WorldEvolutionRecord.chat_id == chat_id
        )) or 0) + 1
        record = WorldEvolutionRecord(
            id=str(uuid4()),
            chat_id=chat_id,
            sequence=sequence,
            mode=mode[:20],
            user_message_id=user.id if user else None,
            assistant_message_id=assistant.id if assistant else None,
            source_hash=source_hash(user.content, assistant.content) if user and assistant else None,
            before_hash=state_hash(before),
            after_state_json=json_dumps(after.model_dump(mode="json")),
            created_at=datetime.now(UTC),
        )
        db.add(record)
        db.commit()

    @staticmethod
    def _valid_source(record: WorldEvolutionRecord, messages: dict[str, MessageRecord]) -> bool:
        if record.source_hash is None:
            return record.user_message_id is None and record.assistant_message_id is None
        user = messages.get(record.user_message_id or "")
        assistant = messages.get(record.assistant_message_id or "")
        return bool(user and assistant and record.source_hash == source_hash(user.content, assistant.content))

    @staticmethod
    def _supporting_context(db: Session, chat_id: str) -> str:
        scenes = db.scalars(select(SceneNodeRecord).where(SceneNodeRecord.chat_id == chat_id)).all()
        npcs = db.scalars(select(NpcRecord).where(NpcRecord.chat_id == chat_id)).all()
        books = db.scalars(select(StoryWorldBookRecord).where(
            StoryWorldBookRecord.chat_id == chat_id,
            StoryWorldBookRecord.enabled.is_(True),
        ).order_by(StoryWorldBookRecord.priority.desc()).limit(12)).all()
        parts = []
        if scenes:
            parts.append("地点：" + "；".join(f"{item.name}：{item.description}" for item in scenes[:20]))
        if npcs:
            parts.append("人物：" + "；".join(
                f"{item.name}：{item.description or item.relation_to_user}" for item in npcs[:30]
            ))
        if books:
            parts.append("世界书：\n" + "\n".join(f"- {item.title}：{item.content[:2000]}" for item in books))
        return "\n".join(parts)


def state_hash(state: WorldState) -> str:
    canonical = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_state(state: WorldState, round_number: int) -> WorldState:
    value = state.model_copy(deep=True)
    value.round = max(0, round_number)
    _ensure_ids(value.factions, "faction")
    _ensure_ids(value.events, "event")
    _ensure_ids(value.rumors, "rumor")
    _ensure_ids(value.trends, "trend")
    return value


def _ensure_ids(items: list[Any], prefix: str) -> None:
    used: set[str] = set()
    for item in items:
        candidate = str(getattr(item, "id", "") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", candidate) or candidate in used:
            candidate = f"{prefix}-{uuid4().hex[:10]}"
            item.id = candidate
        used.add(candidate)
