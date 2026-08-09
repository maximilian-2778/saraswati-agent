"""模型客户端公共协议、未配置状态和供应商工厂。"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.config import Settings


@dataclass(slots=True)
class ToolCall:
    """模型请求执行的一次工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ModelReply:
    """不同模型服务统一使用的内部回复格式。"""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ModelProviderError(RuntimeError):
    """模型服务请求失败或响应格式异常。"""


class ModelClient(Protocol):
    mode: str
    model_name: str | None

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply: ...

    async def stream_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Callable[[str], Awaitable[None]],
    ) -> ModelReply: ...

    async def embed(self, text: str) -> list[float]: ...

    async def check_connection(self) -> None: ...


class StructuredOutputClient(Protocol):
    """可选能力：让支持 JSON Schema 的供应商直接返回结构化结果。"""

    async def complete_structured(
        self,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]: ...


class UnconfiguredModelClient:
    """尚未配置对话模型时使用；仅保留无需联网的本地向量能力。"""

    mode = "unconfigured"
    model_name = None

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply:
        raise ModelProviderError("尚未连接模型 API，请先在设置中完成配置。")

    async def embed(self, text: str) -> list[float]:
        return local_embedding(text)

    async def stream_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Callable[[str], Awaitable[None]],
    ) -> ModelReply:
        raise ModelProviderError("尚未连接模型 API，请先在设置中完成配置。")

    async def check_connection(self) -> None:
        raise ModelProviderError("尚未连接模型 API，请先在设置中完成配置。")

    async def close(self) -> None:
        return None


def build_model_client(settings: Settings) -> ModelClient:
    """按配置选择供应商适配器；配置不完整时进入未连接状态。"""
    if settings.provider_mode == "openai-compatible":
        from backend.providers.openai_compatible import OpenAICompatibleClient

        return OpenAICompatibleClient(settings)
    return UnconfiguredModelClient()


def local_embedding(text: str, dimensions: int = 96) -> list[float]:
    """生成无需外部模型的哈希词袋向量，作为 RAG 的本地回退方案。"""
    vector = [0.0] * dimensions
    tokens = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", text.lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    length = math.sqrt(sum(value * value for value in vector))
    if length == 0:
        return vector
    return [value / length for value in vector]
