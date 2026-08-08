"""分层记忆的创建、向量化与混合检索。"""

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.llm import ModelClient
from backend.models import MemoryRecord
from backend.schemas import MemoryKind
from backend.utils import json_dumps, json_loads


@dataclass(slots=True)
class RetrievedMemory:
    record: MemoryRecord
    score: float
    reason: str


class MemoryService:
    """管理记忆并计算可解释的混合召回分数。"""

    def __init__(self, settings: Settings) -> None:
        total = max(
            settings.vector_weight
            + settings.keyword_weight
            + settings.importance_weight
            + settings.recency_weight,
            0.0001,
        )
        self.vector_weight = settings.vector_weight / total
        self.keyword_weight = settings.keyword_weight / total
        self.importance_weight = settings.importance_weight / total
        self.recency_weight = settings.recency_weight / total

    async def create(
        self,
        db: Session,
        model: ModelClient,
        chat_id: str,
        kind: MemoryKind,
        content: str,
        importance: float = 0.5,
        source_message_id: str | None = None,
    ) -> MemoryRecord:
        embedding = await model.embed(content)
        record = MemoryRecord(
            id=str(uuid4()),
            chat_id=chat_id,
            kind=kind.value,
            content=content,
            importance=max(0.0, min(1.0, importance)),
            embedding_json=json_dumps(embedding),
            source_message_id=source_message_id,
            access_count=0,
            last_accessed_at=None,
            created_at=datetime.now(UTC),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    async def search(
        self,
        db: Session,
        model: ModelClient,
        chat_id: str,
        query: str,
        limit: int,
    ) -> list[RetrievedMemory]:
        records = db.scalars(
            select(MemoryRecord).where(MemoryRecord.chat_id == chat_id)
        ).all()
        if not records:
            return []

        query_vector = await model.embed(query)
        query_tokens = _tokens(query)
        now = datetime.now(UTC)
        scored: list[RetrievedMemory] = []

        for record in records:
            memory_vector = json_loads(record.embedding_json) or []
            vector_score = _cosine(query_vector, memory_vector)
            lexical_score = _jaccard(query_tokens, _tokens(record.content))
            recency_score = _recency(record.created_at, now)
            score = (
                self.vector_weight * max(vector_score, 0.0)
                + self.keyword_weight * lexical_score
                + self.importance_weight * record.importance
                + self.recency_weight * recency_score
            )
            reason = (
                f"向量 {vector_score:.2f}，关键词 {lexical_score:.2f}，"
                f"重要度 {record.importance:.2f}，时间 {recency_score:.2f}"
            )
            scored.append(RetrievedMemory(record, round(score, 4), reason))

        results = sorted(scored, key=lambda item: item.score, reverse=True)[:limit]
        for item in results:
            item.record.access_count += 1
            item.record.last_accessed_at = now
        db.commit()
        return results


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", text.lower()))


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_len = math.sqrt(sum(value * value for value in left))
    right_len = math.sqrt(sum(value * value for value in right))
    if left_len == 0 or right_len == 0:
        return 0.0
    return dot / (left_len * right_len)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _recency(created_at: datetime, now: datetime) -> float:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    age_days = max((now - created_at).total_seconds() / 86_400, 0.0)
    return 1.0 / (1.0 + age_days / 30.0)
