"""分层记忆的创建、向量化与混合检索。"""

import asyncio
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
from backend.reranker import RerankerClient
from backend.schemas import MemoryKind
from backend.services.variants import (
    active_variant_clause,
    active_variant_ids,
    selected_variant_for_source,
)
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
        self.reranker = RerankerClient(settings)
        self.rerank_candidates = settings.rerank_candidates

    async def create(
        self,
        db: Session,
        model: ModelClient,
        chat_id: str,
        kind: MemoryKind,
        content: str,
        importance: float = 0.5,
        source_message_id: str | None = None,
        variant_ids: set[str] | None = None,
    ) -> MemoryRecord:
        embedding = await model.embed(content)
        inferred_variant = selected_variant_for_source(db, source_message_id)
        scope = set(variant_ids or ())
        if inferred_variant:
            scope.add(inferred_variant)
        record = MemoryRecord(
            id=str(uuid4()),
            chat_id=chat_id,
            kind=kind.value,
            content=content,
            importance=max(0.0, min(1.0, importance)),
            embedding_json=json_dumps(embedding),
            source_message_id=source_message_id,
            variant_id=inferred_variant,
            variant_ids_json=json_dumps(sorted(scope)),
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
        exclude_source_message_ids: set[str] | None = None,
        exclude_memory_ids: set[str] | None = None,
    ) -> list[RetrievedMemory]:
        records = db.scalars(
            select(MemoryRecord).where(
                MemoryRecord.chat_id == chat_id,
                active_variant_clause(MemoryRecord.variant_id),
            )
        ).all()
        if not records:
            return []
        selected_variants = active_variant_ids(db, chat_id)

        queries = _expand_queries(query)
        query_vectors = await asyncio.gather(*(model.embed(item) for item in queries))
        query_token_sets = [_tokens(item) for item in queries]
        now = datetime.now(UTC)
        scored: list[RetrievedMemory] = []

        excluded_sources = exclude_source_message_ids or set()
        excluded_memories = exclude_memory_ids or set()
        for record in records:
            if not set(json_loads(record.variant_ids_json) or []).issubset(selected_variants):
                continue
            # 最近窗口已经会携带消息原文，不再召回同一楼层的派生记忆。
            # 这样可以避免模型同时看到“原文 + 楼层摘要”而重复强调同一事件。
            if record.source_message_id in excluded_sources or record.id in excluded_memories:
                continue
            memory_vector = json_loads(record.embedding_json) or []
            vector_scores = [_cosine(vector, memory_vector) for vector in query_vectors]
            lexical_scores = [
                _jaccard(tokens, _tokens(record.content)) for tokens in query_token_sets
            ]
            vector_score = max(vector_scores, default=0.0)
            lexical_score = max(lexical_scores, default=0.0)
            best_query = max(
                range(len(queries)),
                key=lambda index: vector_scores[index] + lexical_scores[index],
            )
            recency_score = _recency(record.created_at, now)
            score = (
                self.vector_weight * max(vector_score, 0.0)
                + self.keyword_weight * lexical_score
                + self.importance_weight * record.importance
                + self.recency_weight * recency_score
            )
            reason = (
                f"视角“{queries[best_query][:28]}”，向量 {vector_score:.2f}，关键词 {lexical_score:.2f}，"
                f"重要度 {record.importance:.2f}，时间 {recency_score:.2f}"
            )
            scored.append(RetrievedMemory(record, round(score, 4), reason))

        candidates = sorted(scored, key=lambda item: item.score, reverse=True)[
            : max(limit, self.rerank_candidates)
        ]
        results = candidates[:limit]
        if self.reranker.configured and candidates:
            try:
                reranked = await self.reranker.rerank(
                    query, [item.record.content for item in candidates]
                )
                reordered: list[RetrievedMemory] = []
                for rank in reranked:
                    if 0 <= rank.index < len(candidates):
                        item = candidates[rank.index]
                        item.score = round(0.3 * item.score + 0.7 * max(0.0, rank.score), 4)
                        item.reason += f"，独立精排 {rank.score:.2f}"
                        reordered.append(item)
                if reordered:
                    results = reordered[:limit]
            except RuntimeError as exc:
                # 精排属于增强链路；失败时保留确定性的本地混合排序。
                results = candidates[:limit]
                for item in results:
                    item.reason += f"，精排降级（{exc}）"
        for item in results:
            item.record.access_count += 1
            item.record.last_accessed_at = now
        db.commit()
        return results


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", text.lower()))


def _expand_queries(query: str) -> list[str]:
    """以多个角色扮演视角检索同一输入；保留原查询以避免模板词稀释。"""
    clean = re.sub(r"\s+", " ", query).strip()
    variants = [
        clean,
        f"相关历史事件与因果：{clean}",
        f"相关人物、关系、承诺与情绪变化：{clean}",
        f"相关物品、数值、地点、计划与悬念：{clean}",
    ]
    return list(dict.fromkeys(item for item in variants if item))


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
