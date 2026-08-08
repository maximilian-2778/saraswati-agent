"""可离线复现的 RAG 排序指标，供回归测试与简历演示使用。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.llm import local_embedding


@dataclass(frozen=True, slots=True)
class RankedDocument:
    id: str
    score: float


def rank_documents(query: str, documents: list[dict[str, str]]) -> list[RankedDocument]:
    """用项目的本地向量回退和关键词交集对固定语料排序。"""
    query_vector = local_embedding(query)
    query_tokens = _tokens(query)
    ranked = []
    for document in documents:
        text = document["text"]
        vector_score = _cosine(query_vector, local_embedding(text))
        lexical_score = _jaccard(query_tokens, _tokens(text))
        ranked.append(
            RankedDocument(document["id"], round(0.65 * max(vector_score, 0) + 0.35 * lexical_score, 6))
        )
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def retrieval_metrics(cases: list[dict[str, object]], k: int = 3) -> dict[str, float]:
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    for case in cases:
        relevant = set(str(item) for item in case["relevant_ids"])  # type: ignore[index]
        ranked = rank_documents(str(case["query"]), list(case["documents"]))  # type: ignore[arg-type]
        top_k = {item.id for item in ranked[:k]}
        recalls.append(len(top_k & relevant) / max(len(relevant), 1))
        rank = next((index for index, item in enumerate(ranked, 1) if item.id in relevant), None)
        reciprocal_ranks.append(1 / rank if rank else 0.0)
    return {
        f"recall@{k}": round(sum(recalls) / max(len(recalls), 1), 4),
        "mrr": round(sum(reciprocal_ranks) / max(len(reciprocal_ranks), 1), 4),
        "cases": float(len(cases)),
    }


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", text.lower()))


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_len = sum(value * value for value in left) ** 0.5
    right_len = sum(value * value for value in right) ** 0.5
    return dot / (left_len * right_len) if left_len and right_len else 0.0
