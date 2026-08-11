"""按模型 tokenizer 计算上下文预算，并为未知模型提供保守估算。"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Protocol

try:
    import tiktoken
except ImportError:  # pragma: no cover - 只在依赖尚未安装时使用回退算法
    tiktoken = None


class TokenCounter(Protocol):
    """Token 计数器的最小接口，便于接入其他模型供应商。"""

    name: str

    def count(self, text: str) -> int: ...


class HeuristicTokenCounter:
    """未知模型使用的保守估算器；它不用于计费。"""

    name = "heuristic"

    def count(self, text: str) -> int:
        cjk = len(re.findall(r"[\u3400-\u9fff]", text))
        non_cjk = re.sub(r"[\u3400-\u9fff]", "", text)
        latin = len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", non_cjk))
        return max(1, cjk + latin)


class TiktokenCounter:
    """使用 tiktoken 对已知模型或 OpenAI 兼容模型进行精确分词。"""

    def __init__(self, model_name: str | None) -> None:
        if tiktoken is None:
            raise RuntimeError("tiktoken 尚未安装")
        self.model_name = model_name or "unknown"
        self.encoding = tiktoken.encoding_for_model(self.model_name)
        self.name = f"tiktoken:{self.encoding.name}"

    def count(self, text: str) -> int:
        return max(1, len(self.encoding.encode(text, disallowed_special=())))


@lru_cache(maxsize=32)
def token_counter_for_model(model_name: str | None) -> TokenCounter:
    """优先选择模型 tokenizer；依赖不可用时自动回退。"""
    if tiktoken is not None:
        try:
            return TiktokenCounter(model_name)
        except KeyError:
            pass
    return HeuristicTokenCounter()


def estimate_tokens(text: str, model_name: str | None = None) -> int:
    """兼容旧调用方式的 Token 计数入口。"""
    return token_counter_for_model(model_name).count(text)


class TokenBudgetManager:
    """裁剪过长上下文，同时保留系统规则和最新用户请求。"""

    def fit(
        self,
        messages: list[dict[str, Any]],
        input_budget: int,
        section_texts: dict[str, str],
        model_name: str | None = None,
        include_debug_content: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        counter = token_counter_for_model(model_name)
        fitted = [dict(message) for message in messages]
        original_tokens = sum(
            counter.count(str(item.get("content", ""))) for item in fitted
        )
        dropped = 0
        dropped_messages: list[dict[str, Any]] = []
        while len(fitted) > 2 and self._tokens(fitted, counter) > input_budget:
            removed = fitted.pop(1)
            removed_content = str(removed.get("content", ""))
            if include_debug_content:
                dropped_messages.append(
                    {
                        "role": str(removed.get("role", "unknown")),
                        "estimated_tokens": counter.count(removed_content),
                        "characters": len(removed_content),
                        "preview": removed_content[:160],
                    }
                )
            dropped += 1

        truncated_system = False
        system_tokens_before = counter.count(str(fitted[0].get("content", ""))) if fitted else 0
        if fitted and self._tokens(fitted, counter) > input_budget:
            other_tokens = sum(
                counter.count(str(item.get("content", ""))) for item in fitted[1:]
            )
            allowance = max(256, input_budget - other_tokens)
            system = str(fitted[0].get("content", ""))
            if counter.count(system) > allowance:
                fitted[0]["content"] = _head_tail(system, allowance, counter)
                truncated_system = True

        included_tokens = self._tokens(fitted, counter)
        return fitted, {
            "input_budget": input_budget,
            "estimated_input_tokens": included_tokens,
            "original_estimated_tokens": original_tokens,
            "remaining_tokens": max(0, input_budget - included_tokens),
            "dropped_old_messages": dropped,
            "dropped_messages": dropped_messages,
            "system_prompt_truncated": truncated_system,
            "system_tokens_before_truncation": system_tokens_before,
            "tokenizer": counter.name,
            "model": model_name,
            "sections": {
                name: {
                    "estimated_tokens": counter.count(text) if text else 0,
                    "characters": len(text),
                }
                for name, text in section_texts.items()
            },
        }

    @staticmethod
    def _tokens(messages: list[dict[str, Any]], counter: TokenCounter) -> int:
        return sum(counter.count(str(item.get("content", ""))) for item in messages)


def _head_tail(text: str, token_limit: int, counter: TokenCounter) -> str:
    """保留提示词开头规则和末尾动态事实。"""
    if counter.count(text) <= token_limit:
        return text
    marker = "\n\n[中间低优先级上下文因 Token 预算被省略]\n\n"
    low, high = 0, len(text)
    best = marker
    while low <= high:
        kept = (low + high) // 2
        head = int(kept * 0.55)
        tail = kept - head
        candidate = text[:head] + marker + (text[-tail:] if tail else "")
        if counter.count(candidate) <= token_limit:
            best = candidate
            low = kept + 1
        else:
            high = kept - 1
    return best
