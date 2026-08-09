"""LangGraph Agent Runtime 的路由与检查点回归测试。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
import sqlite3
from typing import Any

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.llm import ModelProviderError, ModelReply, ToolCall, local_embedding
from backend.main import create_app


class ToolThenFinalModel:
    mode = "test"
    model_name = "tool-then-final"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply:
        if tools and not any(message.get("role") == "tool" for message in messages):
            return ModelReply(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="state-change-1",
                        name="propose_state_change",
                        arguments={
                            "entity": "玩家",
                            "key": "金币",
                            "new_value": 8,
                            "reason": "购买药水花费 2 枚金币",
                        },
                    )
                ],
            )
        if tools:
            return ModelReply(content="你收起药水，钱袋里还剩 8 枚金币。")
        return ModelReply(
            content=(
                '{"summary":"玩家购买药水","time_change":"",'
                '"facts":[],"open_threads":[],"numbers":[]}'
            )
        )

    async def stream_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Callable[[str], Awaitable[None]],
    ) -> ModelReply:
        reply = await self.complete(messages, tools)
        if reply.content and not reply.tool_calls:
            await on_token(reply.content)
        return reply

    async def embed(self, text: str) -> list[float]:
        return local_embedding(text)


class EndlessToolModel(ToolThenFinalModel):
    model_name = "endless-tool"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply:
        if tools:
            index = sum(message.get("role") == "tool" for message in messages) + 1
            return ModelReply(
                content=None,
                tool_calls=[
                    ToolCall(
                        id=f"query-{index}",
                        name="query_state",
                        arguments={"entity": "玩家"},
                    )
                ],
            )
        return ModelReply(content="我停止查询，继续讲述故事。")


class FailingModel(ToolThenFinalModel):
    model_name = "failing-model"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply:
        if tools:
            raise ModelProviderError("测试连接中断")
        return await super().complete(messages, tools)


def test_langgraph_routes_model_to_tool_and_back(
    client: TestClient,
    chat_id: str,
) -> None:
    runtime = client.app.state.runtime
    runtime.model = ToolThenFinalModel()

    response = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "我用 2 枚金币购买一瓶药水。"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "8 枚金币" in body["assistant_message"]["content"]
    assert len(body["state_proposals"]) == 1
    events = [item["event_type"] for item in body["trace"]]
    assert events.count("model_response") == 2
    assert "tool_result" in events
    assert events[-1] == "turn_completed"

    snapshot = runtime.workflow.get_state(
        {"configurable": {"thread_id": f"turn:{body['turn_id']}"}}
    )
    assert snapshot.values["assistant_message_id"] == body["assistant_message"]["id"]
    assert snapshot.values["step"] == 2
    assert snapshot.next == ()


def test_langgraph_forces_final_reply_at_step_limit(
    client: TestClient,
    chat_id: str,
) -> None:
    runtime = client.app.state.runtime
    runtime.model = EndlessToolModel()

    response = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "检查状态后继续。"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["assistant_message"]["content"] == "我停止查询，继续讲述故事。"
    events = [item["event_type"] for item in body["trace"]]
    assert events.count("model_response") == runtime.settings.max_agent_steps
    assert "forced_model_response" in events


def test_langgraph_persists_error_reply_and_completes_pipeline(
    client: TestClient,
    chat_id: str,
) -> None:
    runtime = client.app.state.runtime
    runtime.model = FailingModel()

    response = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "继续故事。"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "测试连接中断" in body["assistant_message"]["content"]
    events = [item["event_type"] for item in body["trace"]]
    assert "model_error" in events
    assert "response_persisted" in events
    assert events[-1] == "turn_completed"


def test_langgraph_writes_durable_sqlite_checkpoints(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    checkpoint_path = tmp_path / "langgraph.db"
    settings = Settings(
        database_url=f"sqlite:///{database_path.as_posix()}",
        llm_base_url=None,
        llm_api_key=None,
        llm_model=None,
        embedding_model=None,
        max_agent_steps=3,
        recent_message_limit=12,
        rag_limit=4,
        langgraph_checkpoint_path=str(checkpoint_path),
    )

    with TestClient(create_app(settings)) as isolated_client:
        chat = isolated_client.post(
            "/api/chats",
            json={"title": "持久化测试", "system_prompt": ""},
        ).json()
        turn = isolated_client.post(
            f"/api/chats/{chat['id']}/messages",
            json={"content": "检查 LangGraph 持久化。"},
        )
        assert turn.status_code == 200

    assert checkpoint_path.exists()
    with sqlite3.connect(checkpoint_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        checkpoint_count = connection.execute(
            "SELECT COUNT(*) FROM checkpoints"
        ).fetchone()[0]
    assert {"checkpoints", "writes"}.issubset(tables)
    assert checkpoint_count > 0
