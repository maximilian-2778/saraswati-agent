"""提取、保存并校验每轮剧情造成的结构化变化。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.llm import ModelClient, ModelProviderError
from backend.models import MessageRecord, NarrativeDeltaRecord, RoleplayGraphEventRecord
from backend.services.variants import active_variant_clause, selected_variant_id
from backend.utils import json_dumps, json_loads


class NarrativeNumber(BaseModel):
    """本轮正文中出现的一项明确数值。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: str
    unit: str
    entity: str = "剧情数值"
    key: str = ""


class NarrativeSceneChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: list[str] = Field(min_length=1, max_length=12)
    description: str = Field(default="", max_length=10_000)
    is_current: bool = False


class NarrativeNpcRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(max_length=120)
    relation: str = Field(max_length=1_000)


class NarrativeNpcChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=10_000)
    relation_to_user: str = Field(default="", max_length=5_000)
    relations: list[NarrativeNpcRelation] = Field(default_factory=list, max_length=100)
    importance: Literal["core", "supporting", "minor"] | None = None
    presence: Literal["present", "nearby", "away", "unknown"] | None = None
    location_path: list[str] = Field(default_factory=list, max_length=12)
    outfit: str = Field(default="", max_length=5_000)
    condition: str = Field(default="", max_length=5_000)


class NarrativeItemChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str = Field(max_length=120)
    owner: str = Field(default="", max_length=120)
    quantity: str = Field(default="", max_length=100)
    status: str = Field(default="", max_length=1_000)
    location: str = Field(default="", max_length=1_000)
    reason: str = Field(default="", max_length=2_000)


class NarrativeStateChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str = Field(max_length=100)
    key: str = Field(max_length=100)
    new_value: Any
    reason: str = Field(default="剧情正文中的明确变化", max_length=2_000)


class NarrativeDeltaPayload(BaseModel):
    """模型提取结果的严格边界，阻止异常字段进入剧情记录。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(max_length=500)
    time_change: str = Field(max_length=200)
    facts: list[str] = Field(default_factory=list, max_length=30)
    open_threads: list[str] = Field(default_factory=list, max_length=20)
    numbers: list[NarrativeNumber] = Field(default_factory=list, max_length=30)
    scene_changes: list[NarrativeSceneChange] = Field(default_factory=list, max_length=20)
    npc_changes: list[NarrativeNpcChange] = Field(default_factory=list, max_length=30)
    item_changes: list[NarrativeItemChange] = Field(default_factory=list, max_length=30)
    state_changes: list[NarrativeStateChange] = Field(default_factory=list, max_length=50)


class NarrativeDeltaService:
    """把自然语言回合压成可追溯 Delta，供回放、诊断和评测使用。"""

    async def process_turn(
        self,
        db: Session,
        model: ModelClient,
        chat_id: str,
        user_message: MessageRecord,
        assistant_message: MessageRecord,
    ) -> NarrativeDeltaRecord:
        events = list(
            db.scalars(
                select(RoleplayGraphEventRecord).where(
                    RoleplayGraphEventRecord.chat_id == chat_id,
                    RoleplayGraphEventRecord.source_message_id == user_message.id,
                    active_variant_clause(RoleplayGraphEventRecord.variant_id),
                )
            ).all()
        )
        extracted = await self._extract(model, user_message.content, assistant_message.content)
        extracted["graph_event_ids"] = [event.id for event in events]
        extracted["graph_changes"] = [json_loads(event.payload_json) for event in events]
        now = datetime.now(UTC)
        record = NarrativeDeltaRecord(
            id=str(uuid4()),
            chat_id=chat_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            variant_id=selected_variant_id(db, assistant_message.id),
            source_hash=source_hash(user_message.content, assistant_message.content),
            payload_json=json_dumps(extracted),
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def list_with_validity(self, db: Session, chat_id: str) -> list[tuple[NarrativeDeltaRecord, bool]]:
        records = list(
            db.scalars(
                select(NarrativeDeltaRecord)
                .where(
                    NarrativeDeltaRecord.chat_id == chat_id,
                    active_variant_clause(NarrativeDeltaRecord.variant_id),
                )
                .order_by(NarrativeDeltaRecord.created_at)
            ).all()
        )
        message_ids = {item.user_message_id for item in records} | {
            item.assistant_message_id for item in records
        }
        messages = db.scalars(select(MessageRecord).where(MessageRecord.id.in_(message_ids))).all()
        by_id = {message.id: message for message in messages}
        result: list[tuple[NarrativeDeltaRecord, bool]] = []
        for record in records:
            user = by_id.get(record.user_message_id)
            assistant = by_id.get(record.assistant_message_id)
            valid = bool(
                user
                and assistant
                and record.source_hash == source_hash(user.content, assistant.content)
            )
            result.append((record, valid))
        return result

    async def _extract(self, model: ModelClient, user_text: str, assistant_text: str) -> dict[str, Any]:
        prompt = (
            "提取本轮剧情中明确发生的变化，只返回符合 JSON Schema 的对象，不要推测。"
            "scene_changes 记录地点路径与当前场景；npc_changes 记录人物登场、位置、关系、穿着和状态；"
            "同一地点在对话中可能使用简称、店铺类型或正式名称；如果人物没有明确移动，"
            "不要因为称呼变化创建新地点，应沿用已有路径中最具体的名称。"
            "item_changes 记录物品归属、数量、位置或状态；state_changes 记录金钱、属性、任务等精确状态。"
            "numbers 中尽量填写 entity 和 key。没有变化的数组返回空数组。"
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"玩家：{user_text}\n角色：{assistant_text}"},
        ]
        parsed = await _structured_delta(model, messages)
        if parsed is not None:
            return parsed.model_dump(mode="json")
        return {
            "summary": _compact(f"{user_text} / {assistant_text}", 300),
            "time_change": "",
            "facts": [],
            "open_threads": [],
            "numbers": _extract_numbers(f"{user_text}\n{assistant_text}"),
            "scene_changes": [],
            "npc_changes": [],
            "item_changes": [],
            "state_changes": [],
        }


def source_hash(user_text: str, assistant_text: str) -> str:
    normalized = f"{user_text.strip()}\n---\n{assistant_text.strip()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def message_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


async def _structured_delta(
    model: ModelClient,
    messages: list[dict[str, Any]],
) -> NarrativeDeltaPayload | None:
    """优先使用供应商 JSON Schema；不支持时校验普通 JSON 回复。"""
    structured = getattr(model, "complete_structured", None)
    if structured is not None:
        try:
            value = await structured(
                messages,
                "narrative_delta",
                NarrativeDeltaPayload.model_json_schema(),
            )
            return NarrativeDeltaPayload.model_validate(value)
        except (ModelProviderError, ValidationError, TypeError, ValueError):
            pass

    try:
        reply = await model.complete(messages, None)
        value = _parse_json_object(reply.content or "")
        if value is None:
            return None
        return NarrativeDeltaPayload.model_validate(_normalize(value))
    except (ModelProviderError, ValidationError):
        return None


def _normalize(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": _compact(str(value.get("summary", "")), 500),
        "time_change": _compact(str(value.get("time_change", "")), 200),
        "facts": _string_list(value.get("facts"), 30),
        "open_threads": _string_list(value.get("open_threads"), 20),
        "numbers": _number_list(value.get("numbers"), 30),
        "scene_changes": _object_list(value.get("scene_changes"), 20),
        "npc_changes": _object_list(value.get("npc_changes"), 30),
        "item_changes": _object_list(value.get("item_changes"), 30),
        "state_changes": _object_list(value.get("state_changes"), 50),
    }


def _number_list(value: Any, limit: int) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "name": _compact(str(item.get("name", "")), 200),
                "value": _compact(str(item.get("value", "")), 100),
                "unit": _compact(str(item.get("unit", "")), 100),
                "entity": _compact(str(item.get("entity", "剧情数值")), 100) or "剧情数值",
                "key": _compact(str(item.get("key", "")), 100),
            }
        )
    return result


def _object_list(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value[:limit] if isinstance(item, dict)]


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_compact(str(item), 500) for item in value[:limit] if str(item).strip()]


def _compact(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _extract_numbers(text: str) -> list[dict[str, str]]:
    return [
        {"name": "正文数值", "value": match.group(0), "unit": "", "entity": "剧情数值", "key": ""}
        for match in re.finditer(r"(?<!\w)-?\d+(?:\.\d+)?", text)
    ][:30]
