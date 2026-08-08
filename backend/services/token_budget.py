"""与具体模型 tokenizer 解耦的保守 Token 预算器。"""

from __future__ import annotations

import re
from typing import Any


def estimate_tokens(text: str) -> int:
    """估算中英文混合文本 Token；用于预算而非计费。"""
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    non_cjk = re.sub(r"[\u3400-\u9fff]", "", text)
    latin = len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", non_cjk))
    return max(1, cjk + latin)


class TokenBudgetManager:
    """优先删除最旧对话，再压缩系统提示，始终保留最新用户消息。"""

    def fit(
        self,
        messages: list[dict[str, Any]],
        input_budget: int,
        section_texts: dict[str, str],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        fitted = [dict(message) for message in messages]
        original_tokens = sum(estimate_tokens(str(item.get("content", ""))) for item in fitted)
        dropped = 0
        while len(fitted) > 2 and self._tokens(fitted) > input_budget:
            fitted.pop(1)
            dropped += 1

        truncated_system = False
        if fitted and self._tokens(fitted) > input_budget:
            other_tokens = sum(
                estimate_tokens(str(item.get("content", ""))) for item in fitted[1:]
            )
            allowance = max(256, input_budget - other_tokens)
            system = str(fitted[0].get("content", ""))
            if estimate_tokens(system) > allowance:
                fitted[0]["content"] = _head_tail(system, allowance)
                truncated_system = True

        included_tokens = self._tokens(fitted)
        return fitted, {
            "input_budget": input_budget,
            "estimated_input_tokens": included_tokens,
            "original_estimated_tokens": original_tokens,
            "remaining_tokens": max(0, input_budget - included_tokens),
            "dropped_old_messages": dropped,
            "system_prompt_truncated": truncated_system,
            "sections": {
                name: {"estimated_tokens": estimate_tokens(text), "characters": len(text)}
                for name, text in section_texts.items()
            },
        }

    @staticmethod
    def _tokens(messages: list[dict[str, Any]]) -> int:
        return sum(estimate_tokens(str(item.get("content", ""))) for item in messages)


def _head_tail(text: str, token_limit: int) -> str:
    """保留提示词开头规则和末尾动态事实，避免只截掉一类信息。"""
    if estimate_tokens(text) <= token_limit:
        return text
    marker = "\n\n[中间低优先级上下文因 Token 预算被省略]\n\n"
    low, high = 0, len(text)
    best = marker
    while low <= high:
        kept = (low + high) // 2
        head = int(kept * 0.55)
        tail = kept - head
        candidate = text[:head] + marker + (text[-tail:] if tail else "")
        if estimate_tokens(candidate) <= token_limit:
            best = candidate
            low = kept + 1
        else:
            high = kept - 1
    return best
