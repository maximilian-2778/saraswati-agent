"""模型提供器抽象、OpenAI 兼容实现和本地演示实现。"""

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from backend.config import Settings


@dataclass(slots=True)
class ToolCall:
    """模型请求执行的一次工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ModelReply:
    """将不同模型服务返回的数据统一成内部格式。"""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ModelProviderError(RuntimeError):
    """模型服务请求或响应格式异常。"""


class ModelClient(Protocol):
    mode: str
    model_name: str | None

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply: ...

    async def embed(self, text: str) -> list[float]: ...


class DemoModelClient:
    """无需联网的确定性模型，方便首次启动和自动化测试。"""

    mode = "demo"
    model_name = "demo-model"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply:
        user_text = next(
            (
                str(message.get("content", ""))
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )
        system_text = "\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        )

        if "生成剧情摘要" in system_text:
            compact = re.sub(r"\s+", " ", user_text).strip()[:800]
            return ModelReply(content=f"演示模式摘要：{compact}")

        compact = re.sub(r"\s+", " ", user_text).strip()[:300]
        return ModelReply(
            content=(
                "（演示模式）我已经收到并保存了这轮剧情："
                f"“{compact}”\n\n"
                "配置兼容的模型 API 后，这里会生成正式的角色扮演回复。"
            )
        )

    async def embed(self, text: str) -> list[float]:
        return local_embedding(text)


class OpenAICompatibleClient:
    """通过 OpenAI 兼容的 Chat Completions 接口调用模型。"""

    mode = "openai-compatible"

    def __init__(self, settings: Settings) -> None:
        if not (
            settings.llm_base_url
            and settings.llm_api_key
            and settings.llm_model
        ):
            raise ValueError("模型配置不完整，无法创建 OpenAI 兼容客户端")
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model_name = settings.llm_model
        self.embedding_model = settings.embedding_model
        self.temperature = settings.temperature
        self.top_p = settings.top_p
        self.max_output_tokens = settings.max_output_tokens
        self.presence_penalty = settings.presence_penalty
        self.frequency_penalty = settings.frequency_penalty
        self.request_timeout = settings.request_timeout

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_output_tokens,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = await self._post("chat/completions", payload)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError("模型响应中缺少 choices[0].message") from exc

        tool_calls: list[ToolCall] = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {"_raw": raw_arguments}
            tool_calls.append(
                ToolCall(
                    id=str(item.get("id") or "tool-call"),
                    name=str(function.get("name") or ""),
                    arguments=arguments,
                )
            )

        return ModelReply(content=message.get("content"), tool_calls=tool_calls)

    async def embed(self, text: str) -> list[float]:
        if not self.embedding_model:
            return local_embedding(text)
        data = await self._post(
            "embeddings",
            {"model": self.embedding_model, "input": text},
        )
        try:
            return [float(value) for value in data["data"][0]["embedding"]]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError("Embedding 响应格式不正确") from exc

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{path}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelProviderError(f"模型服务请求失败：{exc}") from exc


def build_model_client(settings: Settings) -> ModelClient:
    """根据配置选择真实模型或演示模型。"""
    if settings.provider_mode == "openai-compatible":
        return OpenAICompatibleClient(settings)
    return DemoModelClient()


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
