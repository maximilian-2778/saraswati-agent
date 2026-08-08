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


def test_templates_are_copied_into_isolated_story_snapshots(
    client: TestClient,
) -> None:
    first_character = client.post(
        "/api/character-templates",
        json={
            "name": "阿斯塔",
            "identity": "旧王都的守门人",
            "personality": "克制而警惕",
            "speaking_style": "简短、古雅",
            "scenario": "正在看守银铃之门",
        },
    )
    second_character = client.post(
        "/api/character-templates",
        json={"name": "旅人", "identity": "远方来客"},
    )
    world_template = client.post(
        "/api/world-book-templates",
        json={
            "title": "银铃之门",
            "keywords": ["银铃", "旧王都"],
            "content": "银铃之门只在月落时开启。",
            "priority": 80,
            "enabled": True,
        },
    )
    assert first_character.status_code == 201
    assert second_character.status_code == 201
    assert world_template.status_code == 201

    story = client.post(
        "/api/chats",
        json={
            "title": "银铃纪事",
            "character_template_ids": [
                first_character.json()["id"],
                second_character.json()["id"],
            ],
            "world_book_template_ids": [world_template.json()["id"]],
        },
    )
    assert story.status_code == 201
    story_id = story.json()["id"]

    characters = client.get(f"/api/chats/{story_id}/characters").json()
    world_books = client.get(f"/api/chats/{story_id}/world-books").json()
    assert [item["name"] for item in characters] == ["阿斯塔", "旅人"]
    assert characters[0]["source_template_id"] == first_character.json()["id"]
    assert world_books[0]["keywords"] == ["银铃", "旧王都"]

    changed_snapshot = {**characters[0], "personality": "因剧情发展变得信任旅人"}
    updated = client.put(
        f"/api/chats/{story_id}/characters/{characters[0]['id']}",
        json=changed_snapshot,
    )
    assert updated.status_code == 200
    templates = client.get("/api/character-templates").json()
    original = next(item for item in templates if item["id"] == first_character.json()["id"])
    assert original["personality"] == "克制而警惕"

    turn = client.post(
        f"/api/chats/{story_id}/messages",
        json={"content": "我来到银铃前。"},
    )
    context_trace = next(
        item for item in turn.json()["trace"] if item["event_type"] == "context_built"
    )
    assert context_trace["payload"]["character_configured"] is True
    assert context_trace["payload"]["world_entry_ids"] == [world_books[0]["id"]]

    deleted_template = client.delete(
        f"/api/character-templates/{first_character.json()['id']}"
    )
    assert deleted_template.status_code == 204
    remaining_snapshot = client.get(f"/api/chats/{story_id}/characters").json()[0]
    assert remaining_snapshot["name"] == "阿斯塔"
    assert remaining_snapshot["source_template_id"] is None
