"""原生世界推演状态链与 API 测试。"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.models import MessageRecord
from backend.services.world_engine import WorldEngineService


class WorldModel:
    mode = "test"
    model_name = "world-test"

    async def complete_structured(self, messages: list[dict], schema_name: str, schema: dict) -> dict:
        assert schema_name == "world_evolution"
        return {
            "round": 99,
            "digest": "北境商路中断，各方开始争夺旧关隘。",
            "factions": [{
                "id": "north-guild", "name": "北境商会", "description": "控制商路",
                "status": "strained", "relation": "neutral", "influence": 3,
                "latest_action": "派人调查关隘",
            }],
            "events": [{
                "id": "closed-pass", "name": "旧关隘封锁", "type": "conflict",
                "stage": "developing", "level": 2, "summary": "商路受阻。",
                "participants": ["北境商会"], "location": "旧关隘",
                "next_pressure": "物价可能上涨", "active": True,
            }],
            "rumors": [{
                "id": "pass-rumor", "topic": "关隘异动", "type": "report", "level": 2,
                "content": "来往商队称关隘已经封闭。", "scope": "北境商路",
                "source": "商队", "active": True,
            }],
            "trends": [{
                "id": "trade-pressure", "name": "商路承压",
                "description": "货物流通正在放缓。", "direction": "falling",
            }],
        }


def test_world_engine_api_defaults_to_manual(client: TestClient, chat_id: str) -> None:
    response = client.get(f"/api/chats/{chat_id}/world-engine")
    assert response.status_code == 200
    assert response.json()["state"]["round"] == 0
    assert response.json()["auto_evolve"] is False

    enabled = client.put(
        f"/api/chats/{chat_id}/world-engine/config",
        json={"auto_evolve": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["auto_evolve"] is True


def test_world_evolution_chain_stops_after_source_message_changes(
    client: TestClient,
    chat_id: str,
) -> None:
    turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "我听说北境关隘突然关闭。"},
    )
    assert turn.status_code == 200
    user_id = turn.json()["user_message"]["id"]
    assistant_id = turn.json()["assistant_message"]["id"]

    database = client.app.state.database
    service = WorldEngineService()
    with database.session_factory() as db:
        user = db.get(MessageRecord, user_id)
        assistant = db.get(MessageRecord, assistant_id)
        snapshot = asyncio.run(service.evolve(db, WorldModel(), chat_id, user, assistant, "manual"))
        assert snapshot.state.round == 1
        assert snapshot.state.factions[0].name == "北境商会"
        assert "旧关隘封锁" in service.context_text(db, chat_id)

        assistant.content = "改写后的回复不再提及关隘。"
        db.commit()
        rolled_back = service.snapshot(db, chat_id)
        assert rolled_back.state.round == 0
        assert rolled_back.stale_count == 1


def test_manual_world_state_update_keeps_current_round(client: TestClient, chat_id: str) -> None:
    payload = {
        "round": 7,
        "digest": "群岛议会正在重组。",
        "factions": [], "events": [], "rumors": [], "trends": [],
    }
    response = client.put(f"/api/chats/{chat_id}/world-engine/state", json=payload)
    assert response.status_code == 200
    # 编辑现状不是推进世界，因此不会伪造轮次。
    assert response.json()["state"]["round"] == 0
    assert response.json()["state"]["digest"] == "群岛议会正在重组。"
