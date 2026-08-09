"""OpenAI Chat Completions 兼容接口适配器。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from backend.config import Settings
from backend.llm import ModelProviderError, ModelReply, ToolCall, local_embedding


class OpenAICompatibleClient:
    """复用 HTTP 连接，并统一处理普通、流式和结构化响应。"""

    mode = "openai-compatible"

    def __init__(self, settings: Settings) -> None:
        if not (settings.llm_base_url and settings.llm_api_key and settings.llm_model):
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
        self._structured_output_supported: bool | None = None
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout),
            headers={"Authorization": f"Bearer {self.api_key}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def check_connection(self) -> None:
        """通过模型列表接口检查地址和密钥，不触发文本生成。"""
        try:
            response = await self._client.get(self._url("models"))
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise self._provider_error("模型服务连接失败", exc) from exc

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply:
        payload = self._completion_payload(messages, tools)
        data = await self._post_json("chat/completions", payload)
        return self._parse_reply(data)

    async def complete_structured(
        self,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        if self._structured_output_supported is False:
            raise ModelProviderError("当前模型接口不支持 JSON Schema")
        payload = self._completion_payload(messages, None)
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }
        try:
            data = await self._post_json("chat/completions", payload)
        except ModelProviderError as exc:
            if any(code in str(exc) for code in ("HTTP 400", "HTTP 404", "HTTP 422")):
                self._structured_output_supported = False
            raise
        self._structured_output_supported = True
        reply = self._parse_reply(data)
        if not reply.content:
            raise ModelProviderError("结构化响应没有正文")
        try:
            value = json.loads(reply.content)
        except json.JSONDecodeError as exc:
            raise ModelProviderError("结构化响应不是有效 JSON") from exc
        if not isinstance(value, dict):
            raise ModelProviderError("结构化响应必须是 JSON 对象")
        return value

    async def embed(self, text: str) -> list[float]:
        if not self.embedding_model:
            return local_embedding(text)
        data = await self._post_json(
            "embeddings",
            {"model": self.embedding_model, "input": text},
        )
        try:
            return [float(value) for value in data["data"][0]["embedding"]]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelProviderError("Embedding 响应格式不正确") from exc

    async def stream_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Callable[[str], Awaitable[None]],
    ) -> ModelReply:
        payload = self._completion_payload(messages, tools)
        payload["stream"] = True
        content_parts: list[str] = []
        tool_parts: dict[int, dict[str, str]] = {}
        try:
            async with self._client.stream(
                "POST", self._url("chat/completions"), json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    data = json.loads(raw)
                    choice = self._stream_choice(data)
                    if choice is None:
                        continue
                    delta = choice.get("delta") or {}
                    token = delta.get("content")
                    if isinstance(token, str) and token:
                        content_parts.append(token)
                        await on_token(token)
                    self._collect_tool_parts(tool_parts, delta.get("tool_calls") or [])
        except ModelProviderError:
            raise
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise self._provider_error("模型流式请求失败", exc) from exc

        return ModelReply(
            content="".join(content_parts) or None,
            tool_calls=self._build_tool_calls(tool_parts),
        )

    @staticmethod
    def _stream_choice(data: Any) -> dict[str, Any] | None:
        """读取流式事件；空 choices 是常见的 usage/尾部统计帧。"""
        if not isinstance(data, dict):
            raise ModelProviderError("模型流式事件不是 JSON 对象")
        error = data.get("error")
        if error:
            if isinstance(error, dict):
                detail = error.get("message") or error.get("detail") or json.dumps(error, ensure_ascii=False)
            else:
                detail = str(error)
            raise ModelProviderError(f"模型流式服务返回错误：{detail}")
        choices = data.get("choices")
        if choices is None or choices == []:
            return None
        if not isinstance(choices, list) or not isinstance(choices[0], dict):
            raise ModelProviderError("模型流式事件中的 choices 格式不正确")
        return choices[0]

    def _completion_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
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
        return payload

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    response = await self._client.post(self._url(path), json=payload)
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict):
                        raise ModelProviderError("模型服务返回的不是 JSON 对象")
                    return data
        except ModelProviderError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise self._provider_error("模型服务请求失败", exc) from exc
        raise ModelProviderError("模型服务请求没有返回结果")

    def _parse_reply(self, data: dict[str, Any]) -> ModelReply:
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError("模型响应中缺少 choices[0].message") from exc
        tool_calls: list[ToolCall] = []
        for index, item in enumerate(message.get("tool_calls") or []):
            function = item.get("function") or {}
            tool_calls.append(
                ToolCall(
                    id=str(item.get("id") or f"tool-call-{index}"),
                    name=str(function.get("name") or ""),
                    arguments=self._parse_arguments(function.get("arguments") or "{}"),
                )
            )
        return ModelReply(content=message.get("content"), tool_calls=tool_calls)

    @staticmethod
    def _collect_tool_parts(
        target: dict[int, dict[str, str]], items: list[dict[str, Any]]
    ) -> None:
        for item in items:
            index = int(item.get("index", 0))
            current = target.setdefault(index, {"id": "", "name": "", "arguments": ""})
            current["id"] += str(item.get("id") or "")
            function = item.get("function") or {}
            current["name"] += str(function.get("name") or "")
            current["arguments"] += str(function.get("arguments") or "")

    def _build_tool_calls(self, parts: dict[int, dict[str, str]]) -> list[ToolCall]:
        return [
            ToolCall(
                id=parts[index]["id"] or f"tool-call-{index}",
                name=parts[index]["name"],
                arguments=self._parse_arguments(parts[index]["arguments"] or "{}"),
            )
            for index in sorted(parts)
        ]

    @staticmethod
    def _parse_arguments(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
        return value if isinstance(value, dict) else {"_raw": raw}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path}"

    @staticmethod
    def _provider_error(message: str, exc: Exception) -> ModelProviderError:
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            detail = exc.response.text[:500]
            return ModelProviderError(f"{message}：HTTP {status} {detail}")
        return ModelProviderError(f"{message}：{exc}")


def _is_retryable(exc: BaseException) -> bool:
    """只重试连接问题、限流和服务端故障，避免重复发送无效请求。"""
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and (
        exc.response.status_code == 429 or exc.response.status_code >= 500
    )
