"""LangGraph Agent Runtime 的路由与检查点回归测试。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
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


class PartialStreamFailureModel(ToolThenFinalModel):
    model_name = "partial-stream-failure"

    async def stream_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Callable[[str], Awaitable[None]],
    ) -> ModelReply:
        await on_token("这段已经成功生成，不应被尾部错误覆盖。")
        raise ModelProviderError("测试流尾异常")


class TextBeforeToolModel(ToolThenFinalModel):
    """模拟先输出草稿、随后请求工具、最后再输出正式回答的兼容接口。"""

    model_name = "text-before-tool"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply:
        if tools and not any(message.get("role") == "tool" for message in messages):
            return ModelReply(
                content="这是工具执行前的临时草稿。",
                tool_calls=[
                    ToolCall(
                        id="query-before-final",
                        name="query_state",
                        arguments={"entity": "玩家"},
                    )
                ],
            )
        if tools:
            return ModelReply(content="这是工具执行后的最终回答。")
        return await super().complete(messages, tools)

    async def stream_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Callable[[str], Awaitable[None]],
    ) -> ModelReply:
        reply = await self.complete(messages, tools)
        if reply.content:
            await on_token(reply.content)
        return reply


class DeltaOnlyModel:
    mode = "test"
    model_name = "delta-only"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelReply:
        return ModelReply(content="傍晚，你带着两瓶药水走进王都酒馆，莉娜正在柜台后等你。")

    async def complete_structured(
        self,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "summary": "玩家傍晚抵达王都酒馆并遇见莉娜",
            "time_change": "傍晚",
            "facts": ["莉娜在酒馆内"],
            "open_threads": [],
            "numbers": [],
            "scene_changes": [{
                "path": ["王都", "酒馆"],
                "description": "王都中心的酒馆",
                "is_current": True,
            }],
            "npc_changes": [{
                "name": "莉娜",
                "description": "酒馆老板",
                "relation_to_user": "熟人",
                "relations": [],
                "importance": "supporting",
                "presence": "present",
                "location_path": ["王都", "酒馆"],
                "outfit": "围裙",
                "condition": "平静",
            }],
            "item_changes": [{
                "item": "药水",
                "owner": "玩家",
                "quantity": "2",
                "status": "完好",
                "location": "背包",
                "reason": "正文明确写明玩家带着两瓶药水",
            }],
            "state_changes": [{
                "entity": "玩家",
                "key": "金币",
                "new_value": 8,
                "reason": "本轮结算后的余额",
            }],
        }

    async def embed(self, text: str) -> list[float]:
        return local_embedding(text)


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
    assert body["state_proposals"][0]["status"] == "approved"
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


def test_generation_after_delta_updates_graph_timeline_and_state(
    client: TestClient,
    chat_id: str,
) -> None:
    runtime = client.app.state.runtime
    runtime.model = DeltaOnlyModel()

    response = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "我带着药水去酒馆找莉娜。"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "narrative_delta_applied" in [item["event_type"] for item in body["trace"]]
    assert {item["name"] for item in client.get(f"/api/chats/{chat_id}/scenes").json()} == {"王都", "酒馆"}
    assert client.get(f"/api/chats/{chat_id}/npcs").json()[0]["name"] == "莉娜"
    assert client.get(f"/api/chats/{chat_id}/timeline").json()[0]["story_time"] == "傍晚"
    state = client.get(f"/api/chats/{chat_id}/state").json()
    assert {(item["entity"], item["key"]) for item in state} == {("物品:药水", "状态"), ("玩家", "金币")}
    assert all(item["status"] == "approved" for item in body["state_proposals"])


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


def test_streaming_keeps_generated_content_when_stream_tail_fails(
    client: TestClient,
    chat_id: str,
) -> None:
    runtime = client.app.state.runtime
    runtime.model = PartialStreamFailureModel()

    with client.stream(
        "POST",
        f"/api/chats/{chat_id}/turns/stream",
        json={"content": "继续故事。"},
    ) as response:
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert "".join(
        event.get("content", "") for event in events if event["type"] == "chunk"
    ) == "这段已经成功生成，不应被尾部错误覆盖。"
    assert any(
        event["type"] == "phase" and event["phase"] == "postprocessing"
        for event in events
    )
    done = next(event for event in events if event["type"] == "done")
    assert done["turn"]["assistant_message"]["content"] == "这段已经成功生成，不应被尾部错误覆盖。"
    error_trace = next(
        item for item in done["turn"]["trace"] if item["event_type"] == "model_error"
    )
    assert error_trace["payload"]["streamed_content_preserved"] is True


def test_streaming_hides_provisional_text_before_tool_final_reply(
    client: TestClient,
    chat_id: str,
) -> None:
    runtime = client.app.state.runtime
    runtime.model = TextBeforeToolModel()

    with client.stream(
        "POST",
        f"/api/chats/{chat_id}/turns/stream",
        json={"content": "先查询状态，再回答。"},
    ) as response:
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert response.status_code == 200
    chunks = [
        event.get("content", "")
        for event in events
        if event.get("type") == "chunk"
    ]
    assert chunks == ["这是工具执行后的最终回答。"]
    assert not any(
        event.get("phase") == "generation_reset"
        for event in events
        if event.get("type") == "phase"
    )

    done = next(event for event in events if event["type"] == "done")
    assert done["turn"]["assistant_message"]["content"] == "这是工具执行后的最终回答。"


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

    with TestClient(create_app(settings, ToolThenFinalModel())) as isolated_client:
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
