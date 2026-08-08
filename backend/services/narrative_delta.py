"""提取、保存并校验每轮剧情造成的结构化变化。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.llm import ModelClient, ModelProviderError
from backend.models import MessageRecord, NarrativeDeltaRecord, RoleplayGraphEventRecord
from backend.utils import json_dumps, json_loads


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
                .where(NarrativeDeltaRecord.chat_id == chat_id)
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
            "只返回 JSON，不要 Markdown。提取本轮剧情 Delta，格式为："
            '{"summary":"一句话","time_change":"","facts":[],"open_threads":[],'
            '"numbers":[{"name":"","value":"","unit":""}]}。'
            "只记录正文明确发生的变化，不推测。"
        )
        try:
            reply = await model.complete(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"玩家：{user_text}\n角色：{assistant_text}"},
                ],
                None,
            )
            parsed = _parse_json_object(reply.content or "")
        except ModelProviderError:
            parsed = None
        if parsed is not None:
            return _normalize(parsed)
        return {
            "summary": _compact(f"{user_text} / {assistant_text}", 300),
            "time_change": "",
            "facts": [],
            "open_threads": [],
            "numbers": _extract_numbers(f"{user_text}\n{assistant_text}"),
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


def _normalize(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": _compact(str(value.get("summary", "")), 500),
        "time_change": _compact(str(value.get("time_change", "")), 200),
        "facts": _string_list(value.get("facts"), 30),
        "open_threads": _string_list(value.get("open_threads"), 20),
        "numbers": value.get("numbers", []) if isinstance(value.get("numbers"), list) else [],
    }


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_compact(str(item), 500) for item in value[:limit] if str(item).strip()]


def _compact(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _extract_numbers(text: str) -> list[dict[str, str]]:
    return [
        {"name": "正文数值", "value": match.group(0), "unit": ""}
        for match in re.finditer(r"(?<!\w)-?\d+(?:\.\d+)?", text)
    ][:30]
