"""0.5.0 可靠性：Delta、事件回放、Token 预算与离线评测。"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.evaluation import retrieval_metrics
from backend.services.token_budget import TokenBudgetManager, estimate_tokens


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
    assert "近期原文" in budget["sections"]


def test_token_budget_preserves_latest_message_and_stays_within_limit() -> None:
    manager = TokenBudgetManager()
    messages = [{"role": "system", "content": "规则" * 800}]
    messages.extend({"role": "user", "content": f"旧消息 {index} " * 80} for index in range(12))
    messages.append({"role": "user", "content": "必须保留的最新请求"})
    fitted, diagnostics = manager.fit(messages, 700, {"规则": messages[0]["content"]})
    assert fitted[-1]["content"] == "必须保留的最新请求"
    assert sum(estimate_tokens(str(item["content"])) for item in fitted) <= 700
    assert diagnostics["dropped_old_messages"] > 0


def test_fixed_rag_dataset_meets_regression_threshold() -> None:
    path = Path(__file__).resolve().parent.parent / "evals" / "rag_cases.json"
    metrics = retrieval_metrics(json.loads(path.read_text(encoding="utf-8")), k=1)
    assert metrics["recall@1"] >= 0.8
    assert metrics["mrr"] >= 0.8
