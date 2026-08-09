"""0.5.0 可靠性：Delta、事件回放、Token 预算与离线评测。"""

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.evaluation import retrieval_metrics
from backend.llm import ModelReply, local_embedding
from backend.services.narrative_delta import NarrativeDeltaService
from backend.services.token_budget import (
    TokenBudgetManager,
    estimate_tokens,
    token_counter_for_model,
)


class StructuredDeltaModel:
    mode = "test"
    model_name = "structured-test"

    def __init__(self) -> None:
        self.schema_used = False

    async def complete_structured(
        self,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        self.schema_used = schema_name == "narrative_delta" and schema["type"] == "object"
        return {
            "summary": "玩家购买了一张地图",
            "time_change": "",
            "facts": ["地图归玩家所有"],
            "open_threads": [],
            "numbers": [{"name": "价格", "value": "12", "unit": "金币"}],
        }

    async def complete(self, messages: list[dict[str, Any]], tools: Any = None) -> ModelReply:
        raise AssertionError("支持结构化输出时不应调用普通补救请求")

    async def embed(self, text: str) -> list[float]:
        return local_embedding(text)


def test_turn_creates_delta_and_rewrite_marks_it_invalid(
    client: TestClient, chat_id: str
) -> None:
    turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "我花费 12 金币买下地图。"},
    ).json()
    deltas = client.get(f"/api/chats/{chat_id}/narrative-deltas").json()
    assert len(deltas) == 1
    assert deltas[0]["valid"] is True
    assert deltas[0]["payload"]["numbers"]

    response = client.put(
        f"/api/chats/{chat_id}/messages/{turn['assistant_message']['id']}",
        json={"content": "改写后，本轮没有进行交易。"},
    )
    assert response.status_code == 200
    assert client.get(f"/api/chats/{chat_id}/narrative-deltas").json()[0]["valid"] is False


def test_graph_projection_replays_only_events_whose_source_is_unchanged(
    client: TestClient, chat_id: str
) -> None:
    turn = client.post(
        f"/api/chats/{chat_id}/messages", json={"content": "我进入月影酒馆。"}
    ).json()
    runtime = client.app.state.runtime
    with client.app.state.database.session_factory() as db:
        runtime.graph_service.upsert_scene_path(
            db,
            chat_id,
            ["王都", "月影酒馆"],
            "灯火通明",
            True,
            turn["user_message"]["id"],
        )
    assert len(client.get(f"/api/chats/{chat_id}/scenes").json()) == 2

    edited = client.put(
        f"/api/chats/{chat_id}/messages/{turn['user_message']['id']}",
        json={"content": "我没有进入酒馆，而是留在城门。"},
    )
    assert edited.status_code == 200
    assert client.get(f"/api/chats/{chat_id}/scenes").json() == []


def test_context_trace_contains_token_budget_diagnostics(
    client: TestClient, chat_id: str
) -> None:
    turn = client.post(
        f"/api/chats/{chat_id}/messages", json={"content": "继续调查钟楼。"}
    ).json()
    event = next(item for item in turn["trace"] if item["event_type"] == "context_built")
    budget = event["payload"]["token_budget"]
    assert budget["input_budget"] > 0
    assert budget["estimated_input_tokens"] <= budget["input_budget"]
    labels = {section["label"] for section in budget["sections"]}
    assert {"最近对话", "用户最新消息"} <= labels
    assert budget["final_prompt"]
    assert isinstance(budget["world_book_triggers"], list)
    assert isinstance(budget["rag_retrieval"], list)
    model_event = next(
        item for item in turn["trace"] if item["event_type"] == "model_response"
    )
    assert model_event["payload"]["duration_ms"] >= 0
    assert model_event["payload"]["input_tokens"] > 0
    assert model_event["payload"]["output_tokens"] > 0
    assert model_event["payload"]["pricing_configured"] is False
    completed = next(
        item for item in turn["trace"] if item["event_type"] == "turn_completed"
    )
    assert completed["payload"]["duration_ms"] >= model_event["payload"]["duration_ms"]


def test_token_budget_preserves_latest_message_and_stays_within_limit() -> None:
    manager = TokenBudgetManager()
    messages = [{"role": "system", "content": "规则" * 800}]
    messages.extend({"role": "user", "content": f"旧消息 {index} " * 80} for index in range(12))
    messages.append({"role": "user", "content": "必须保留的最新请求"})
    fitted, diagnostics = manager.fit(messages, 700, {"规则": messages[0]["content"]})
    assert fitted[-1]["content"] == "必须保留的最新请求"
    assert sum(estimate_tokens(str(item["content"])) for item in fitted) <= 700
    assert diagnostics["dropped_old_messages"] > 0


def test_token_counter_uses_model_tokenizer_and_unknown_model_fallback() -> None:
    assert token_counter_for_model("gpt-4o-mini").name.startswith("tiktoken:")
    assert token_counter_for_model("private-roleplay-model").name == "heuristic"


def test_narrative_delta_prefers_validated_structured_output() -> None:
    model = StructuredDeltaModel()
    payload = asyncio.run(
        NarrativeDeltaService()._extract(model, "我支付 12 金币", "你拿到了地图")
    )
    assert model.schema_used is True
    assert payload["numbers"] == [{
        "name": "价格",
        "value": "12",
        "unit": "金币",
        "entity": "剧情数值",
        "key": "",
    }]
    assert payload["scene_changes"] == []
    assert payload["npc_changes"] == []
    assert payload["item_changes"] == []
    assert payload["state_changes"] == []


def test_fixed_rag_dataset_meets_regression_threshold() -> None:
    path = Path(__file__).resolve().parent.parent / "evals" / "rag_cases.json"
    metrics = retrieval_metrics(json.loads(path.read_text(encoding="utf-8")), k=1)
    assert metrics["recall@1"] >= 0.8
    assert metrics["mrr"] >= 0.8


def test_openapi_keeps_routes_from_every_domain(client: TestClient) -> None:
    """路由拆分后，五个业务领域都必须继续出现在公开 API 中。"""
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/health",
        "/api/character-templates",
        "/api/chats",
        "/api/chats/{chat_id}/memories",
        "/api/chats/{chat_id}/state",
    }
    assert expected <= set(paths)
