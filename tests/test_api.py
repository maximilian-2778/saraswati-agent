"""Saraswati Agent API 的核心端到端测试。"""

from fastapi.testclient import TestClient


def test_health_and_runtime_use_demo_mode(client: TestClient) -> None:
    health = client.get("/api/health")
    runtime = client.get("/api/runtime")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert runtime.json()["provider_mode"] == "demo"


def test_chat_turn_persists_messages_and_episode_memory(
    client: TestClient,
    chat_id: str,
) -> None:
    turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "我在雨夜走进了旧图书馆。"},
    )

    assert turn.status_code == 200
    body = turn.json()
    assert body["provider_mode"] == "demo"
    assert body["user_message"]["role"] == "user"
    assert body["assistant_message"]["role"] == "assistant"
    assert body["trace"]

    messages = client.get(f"/api/chats/{chat_id}/messages").json()
    memories = client.get(f"/api/chats/{chat_id}/memories").json()
    assert len(messages) == 2
    assert any(memory["kind"] == "episodic" for memory in memories)


def test_memory_search_returns_explainable_score(
    client: TestClient,
    chat_id: str,
) -> None:
    created = client.post(
        f"/api/chats/{chat_id}/memories",
        json={
            "kind": "semantic",
            "content": "守门人害怕银色铃铛。",
            "importance": 0.9,
        },
    )
    assert created.status_code == 201

    search = client.post(
        f"/api/chats/{chat_id}/memories/search",
        json={"query": "守门人害怕什么铃铛", "limit": 3},
    )
    assert search.status_code == 200
    result = search.json()[0]
    assert "银色铃铛" in result["memory"]["content"]
    assert result["score"] > 0
    assert "关键词" in result["retrieval_reason"]


def test_state_must_be_approved_and_numeric_conflict_is_audited(
    client: TestClient,
    chat_id: str,
) -> None:
    proposal = client.post(
        f"/api/chats/{chat_id}/state/proposals",
        json={
            "entity": "玩家",
            "key": "金币",
            "new_value": 87,
            "reason": "初始角色状态",
        },
    )
    assert proposal.status_code == 201
    proposal_id = proposal.json()["id"]
    assert client.get(f"/api/chats/{chat_id}/state").json() == []

    approved = client.post(
        f"/api/chats/{chat_id}/state/proposals/{proposal_id}/resolve",
        json={"action": "approve"},
    )
    assert approved.status_code == 200
    state = client.get(f"/api/chats/{chat_id}/state").json()
    assert state[0]["value"] == 87

    turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "旁白宣称我的金币是100。"},
    )
    assert turn.status_code == 200
    assert turn.json()["audit_issues"]
    assert turn.json()["audit_issues"][0]["expected_value"] == 87


def test_settings_update_masks_api_key_and_rebuilds_runtime(
    client: TestClient,
) -> None:
    initial = client.get("/api/settings")
    assert initial.status_code == 200
    assert initial.json()["api_key_configured"] is False

    payload = {
        "llm_base_url": "https://example.com/v1",
        "api_key": "test-secret-1234",
        "clear_api_key": False,
        "llm_model": "example-model",
        "embedding_model": None,
        "temperature": 0.65,
        "top_p": 0.9,
        "max_output_tokens": 1024,
        "presence_penalty": 0.1,
        "frequency_penalty": 0.2,
        "request_timeout": 45,
        "max_agent_steps": 6,
        "recent_message_limit": 20,
        "rag_limit": 7,
        "vector_weight": 0.5,
        "keyword_weight": 0.3,
        "importance_weight": 0.15,
        "recency_weight": 0.05,
    }
    updated = client.put("/api/settings", json=payload)
    assert updated.status_code == 200
    body = updated.json()
    assert body["provider_mode"] == "openai-compatible"
    assert body["api_key_configured"] is True
    assert body["api_key_hint"] == "••••1234"
    assert "test-secret" not in updated.text
    assert body["temperature"] == 0.65

    runtime = client.get("/api/runtime").json()
    assert runtime["model"] == "example-model"
    assert runtime["max_agent_steps"] == 6

    payload.update(
        {
            "llm_base_url": None,
            "api_key": None,
            "clear_api_key": True,
            "llm_model": None,
        }
    )
    cleared = client.put("/api/settings", json=payload)
    assert cleared.status_code == 200
    assert cleared.json()["provider_mode"] == "demo"


def test_character_and_world_book_are_persisted(
    client: TestClient,
    chat_id: str,
) -> None:
    empty_character = client.get(f"/api/chats/{chat_id}/character")
    assert empty_character.status_code == 200
    assert empty_character.json()["id"] is None

    character = client.put(
        f"/api/chats/{chat_id}/character",
        json={
            "name": "阿斯塔",
            "identity": "旧王都的守门人",
            "personality": "克制而警惕",
            "speaking_style": "简短、古雅",
            "scenario": "正在看守银铃之门",
        },
    )
    assert character.status_code == 200
    assert character.json()["name"] == "阿斯塔"

    created = client.post(
        f"/api/chats/{chat_id}/world-book",
        json={
            "title": "银铃之门",
            "keywords": ["银铃", "旧王都"],
            "content": "银铃之门只在月落时开启。",
            "priority": 80,
            "enabled": True,
        },
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]
    entries = client.get(f"/api/chats/{chat_id}/world-book").json()
    assert entries[0]["keywords"] == ["银铃", "旧王都"]

    turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "我来到银铃前。"},
    )
    context_trace = next(
        item for item in turn.json()["trace"] if item["event_type"] == "context_built"
    )
    assert context_trace["payload"]["character_configured"] is True
    assert context_trace["payload"]["world_entry_ids"] == [entry_id]

    updated = client.put(
        f"/api/chats/{chat_id}/world-book/{entry_id}",
        json={
            "title": "银铃之门",
            "keywords": [],
            "content": "这是一条常驻世界设定。",
            "priority": 90,
            "enabled": False,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    deleted = client.delete(f"/api/chats/{chat_id}/world-book/{entry_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/chats/{chat_id}/world-book").json() == []
