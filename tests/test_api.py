"""Saraswati Agent API 的核心端到端测试。"""

import json

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


def test_agent_does_not_recall_memory_from_recent_full_text_window(
    client: TestClient,
    chat_id: str,
) -> None:
    first_turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "我把银色铃铛交给了守门人。"},
    )
    assert first_turn.status_code == 200

    second_turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "守门人现在拿着什么？"},
    )
    assert second_turn.status_code == 200
    assert second_turn.json()["retrieved_memories"] == []


def test_message_rewrite_invalidates_and_can_rebuild_memory_branch(
    client: TestClient,
    chat_id: str,
) -> None:
    turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "第一天，我在港口遇见了船长。"},
    ).json()
    assistant_id = turn["assistant_message"]["id"]
    proposal = client.post(
        f"/api/chats/{chat_id}/state/proposals",
        json={
            "entity": "NPC:船长",
            "key": "是否在港口",
            "new_value": True,
            "reason": "本轮剧情确认",
            "source_message_id": turn["user_message"]["id"],
        },
    ).json()
    client.post(
        f"/api/chats/{chat_id}/state/proposals/{proposal['id']}/resolve",
        json={"action": "approve"},
    )
    assert client.get(f"/api/chats/{chat_id}/state").json()

    edited = client.put(
        f"/api/chats/{chat_id}/messages/{assistant_id}",
        json={"content": "改写后：船长并没有在港口出现。"},
    )
    assert edited.status_code == 200
    broken = client.get(f"/api/chats/{chat_id}/memory-coverage").json()
    assert broken["invalid_message_ids"] == [assistant_id]
    assert broken["coverage_ratio"] == 0.0
    assert client.get(f"/api/chats/{chat_id}/state").json() == []
    proposals = client.get(f"/api/chats/{chat_id}/state/proposals").json()
    reverted = next(item for item in proposals if item["id"] == proposal["id"])
    assert reverted["status"] == "pending"
    assert reverted["reason"].startswith("源剧情已改写")

    repaired = client.post(
        f"/api/chats/{chat_id}/memory-coverage/backfill"
    )
    assert repaired.status_code == 200
    assert repaired.json()["coverage_ratio"] == 1.0
    assert repaired.json()["invalid_message_ids"] == []


def test_memory_hub_builds_summaries_timeline_and_manual_merge(
    client: TestClient,
    chat_id: str,
) -> None:
    first_turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "<think>不要写入记忆的推理</think>第一天清晨，我在钟楼遇见了守门人。"},
    )
    assert first_turn.status_code == 200
    memories = client.get(f"/api/chats/{chat_id}/memories").json()
    assert memories[0]["kind"] == "episodic"
    assert memories[0]["content"].startswith("[楼层摘要]")
    assert "不要写入记忆的推理" not in memories[0]["content"]

    timeline = client.get(f"/api/chats/{chat_id}/timeline")
    assert timeline.status_code == 200
    assert timeline.json()[0]["story_time"] == "第一天 → 清晨"

    second_memory = client.post(
        f"/api/chats/{chat_id}/memories",
        json={"kind": "semantic", "content": "守门人名叫阿斯塔。", "importance": 0.8},
    ).json()
    merged = client.post(
        f"/api/chats/{chat_id}/memories/merge",
        json={
            "memory_ids": [memories[0]["id"], second_memory["id"]],
            "detail_mode": "brief",
        },
    )
    assert merged.status_code == 200
    assert merged.json()["content"].startswith("[手动合并]")

    updated = client.put(
        f"/api/chats/{chat_id}/memories/{merged.json()['id']}",
        json={"content": "[手动合并] 修订后的剧情总结。", "importance": 0.9},
    )
    assert updated.status_code == 200
    assert updated.json()["importance"] == 0.9


def test_memory_hub_automatically_creates_chapter_summary(
    client: TestClient,
    chat_id: str,
) -> None:
    for index in range(8):
        response = client.post(
            f"/api/chats/{chat_id}/messages",
            json={"content": f"第{index + 1}轮剧情继续推进。"},
        )
        assert response.status_code == 200

    memories = client.get(f"/api/chats/{chat_id}/memories").json()
    assert sum(item["kind"] == "episodic" for item in memories) == 8
    assert any(item["content"].startswith("[章节总结]") for item in memories)

    graph = client.get(f"/api/chats/{chat_id}/memory-graph")
    assert graph.status_code == 200
    nodes = graph.json()
    assert sum(item["node_type"] == "leaf" for item in nodes) == 8
    chapter = next(item for item in nodes if item["level"] == 1)
    assert len(chapter["child_ids"]) == 8
    assert chapter["valid"] is True

    coverage = client.get(f"/api/chats/{chat_id}/memory-coverage")
    assert coverage.status_code == 200
    assert coverage.json()["coverage_ratio"] == 1.0
    assert coverage.json()["missing_message_ids"] == []


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

    second_proposal = client.post(
        f"/api/chats/{chat_id}/state/proposals",
        json={
            "entity": "玩家",
            "key": "金币",
            "new_value": 80,
            "reason": "购买地图",
        },
    ).json()
    client.post(
        f"/api/chats/{chat_id}/state/proposals/{second_proposal['id']}/resolve",
        json={"action": "approve"},
    )
    rebuilt_state = client.get(f"/api/chats/{chat_id}/state").json()[0]
    assert rebuilt_state["value"] == 80
    assert rebuilt_state["version"] == 2

    turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "旁白宣称我的金币是100。"},
    )
    assert turn.status_code == 200
    assert turn.json()["audit_issues"]
    assert turn.json()["audit_issues"][0]["expected_value"] == 80


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
        "rerank_base_url": "https://rerank.example.com/v1",
        "rerank_api_key": "dummy-rerank-key-5678",
        "clear_rerank_api_key": False,
        "rerank_model": "example-reranker",
        "rerank_candidates": 16,
    }
    updated = client.put("/api/settings", json=payload)
    assert updated.status_code == 200
    body = updated.json()
    assert body["provider_mode"] == "openai-compatible"
    assert body["api_key_configured"] is True
    assert body["api_key_hint"] == "••••1234"
    assert "test-secret" not in updated.text
    assert "dummy-rerank-key" not in updated.text
    assert body["rerank_api_key_configured"] is True
    assert body["rerank_api_key_hint"] == "••••5678"
    assert body["rerank_model"] == "example-reranker"
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


def test_scene_npc_graph_is_available_to_story_runtime(
    client: TestClient,
    chat_id: str,
) -> None:
    root = client.post(
        f"/api/chats/{chat_id}/scenes",
        json={"name": "旧王都", "description": "被城墙包围", "is_current": False},
    )
    assert root.status_code == 201
    tavern = client.post(
        f"/api/chats/{chat_id}/scenes",
        json={
            "name": "银铃酒馆",
            "parent_id": root.json()["id"],
            "description": "旅人交换传闻的地方",
            "is_current": True,
        },
    )
    assert tavern.status_code == 201
    assert tavern.json()["path"] == ["旧王都", "银铃酒馆"]

    npc = client.post(
        f"/api/chats/{chat_id}/npcs",
        json={
            "name": "阿斯塔",
            "description": "沉默的守门人",
            "relation_to_user": "暂时的盟友",
            "relations": [{"target": "酒馆老板", "relation": "欠对方一个人情"}],
            "importance": "core",
            "presence": "present",
            "location_scene_id": tavern.json()["id"],
            "outfit": "黑色斗篷",
            "condition": "警惕",
        },
    )
    assert npc.status_code == 201
    assert npc.json()["relations"][0]["target"] == "酒馆老板"

    turn = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "第一天，我在银铃酒馆和阿斯塔谈话。"},
    )
    assert turn.status_code == 200
    assert client.get(f"/api/chats/{chat_id}/scenes").json()[1]["is_current"] is True
    assert client.get(f"/api/chats/{chat_id}/npcs").json()[0]["presence"] == "present"


def test_character_avatar_is_copied_and_story_can_be_deleted(
    client: TestClient,
) -> None:
    avatar = "data:image/png;base64,c2FyYXN3YXRp"
    template = client.post(
        "/api/character-templates",
        json={"name": "阿斯塔", "avatar": avatar},
    )
    assert template.status_code == 201
    assert template.json()["avatar"] == avatar

    story = client.post(
        "/api/chats",
        json={
            "title": "可删除故事",
            "character_template_ids": [template.json()["id"]],
        },
    )
    story_id = story.json()["id"]
    character = client.get(f"/api/chats/{story_id}/characters").json()[0]
    assert character["avatar"] == avatar

    assert client.post(
        f"/api/chats/{story_id}/messages", json={"content": "测试"}
    ).status_code == 200
    assert client.delete(f"/api/chats/{story_id}").status_code == 204
    assert client.get(f"/api/chats/{story_id}").status_code == 404
    assert all(item["id"] != story_id for item in client.get("/api/chats").json())


def test_chat_candidates_bookmarks_branches_and_checkpoints(
    client: TestClient,
) -> None:
    story = client.post("/api/chats", json={"title": "多结局测试"})
    assert story.status_code == 201
    story_id = story.json()["id"]

    turn = client.post(
        f"/api/chats/{story_id}/messages",
        json={"content": "我推开了酒馆的门。"},
    )
    assert turn.status_code == 200
    user_message = turn.json()["user_message"]
    assistant_message = turn.json()["assistant_message"]

    bookmark = client.post(
        f"/api/chats/{story_id}/messages/{assistant_message['id']}/bookmark"
    )
    assert bookmark.status_code == 200
    assert bookmark.json()["bookmarked"] is True
    assert client.get(f"/api/chats/{story_id}/bookmarks").json()[0]["message_id"] == assistant_message["id"]

    proposal = client.post(
        f"/api/chats/{story_id}/state/proposals",
        json={
            "entity": "玩家",
            "key": "金币",
            "new_value": 20,
            "reason": "原候选获得金币",
            "source_message_id": user_message["id"],
        },
    )
    assert proposal.status_code == 201
    approved = client.post(
        f"/api/chats/{story_id}/state/proposals/{proposal.json()['id']}/resolve",
        json={"action": "approve"},
    )
    assert approved.status_code == 200
    assert client.get(f"/api/chats/{story_id}/state").json()[0]["value"] == 20

    candidate = client.post(
        f"/api/chats/{story_id}/messages/{assistant_message['id']}/regenerate"
    )
    assert candidate.status_code == 200
    assert candidate.json()["position"] == 1
    variants = client.get(f"/api/chats/{story_id}/message-variants").json()
    assert len(variants) == 2
    assert variants[1]["selected"] is True
    assert client.get(f"/api/chats/{story_id}/state").json() == []

    selected = client.post(
        f"/api/chats/{story_id}/messages/{assistant_message['id']}/variants/{variants[0]['id']}/select"
    )
    assert selected.status_code == 200
    assert selected.json()["content"] == variants[0]["content"]
    assert client.get(f"/api/chats/{story_id}/state").json()[0]["value"] == 20

    checkpoint = client.post(
        f"/api/chats/{story_id}/checkpoints",
        json={"message_id": assistant_message["id"], "name": "进入酒馆"},
    )
    assert checkpoint.status_code == 201
    restored = client.post(
        f"/api/chats/{story_id}/checkpoints/{checkpoint.json()['id']}/restore"
    )
    assert restored.status_code == 201
    restored_messages = client.get(
        f"/api/chats/{restored.json()['id']}/messages"
    ).json()
    assert [item["content"] for item in restored_messages] == [
        user_message["content"],
        variants[0]["content"],
    ]

    branch = client.post(
        f"/api/chats/{story_id}/branches",
        json={"message_id": user_message["id"], "title": "门外支线"},
    )
    assert branch.status_code == 201
    assert len(client.get(f"/api/chats/{branch.json()['id']}/messages").json()) == 1

    deleted = client.delete(
        f"/api/chats/{story_id}/messages/{user_message['id']}"
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/chats/{story_id}/messages").json() == []


def test_persona_character_card_and_advanced_world_book_snapshots(
    client: TestClient,
) -> None:
    world = client.post("/api/world-book-templates", json={
        "title": "银铃规则", "keywords": ["银铃"], "secondary_keywords": ["门"],
        "content": "银铃只会在午夜响起。", "priority": 88, "constant": False,
        "case_sensitive": True, "scan_depth": 8, "insertion_position": "system",
        "group_name": "门铃", "recursive": True, "token_budget": 256,
        "scope": "persona",
    })
    assert world.status_code == 201
    world_id = world.json()["id"]
    persona = client.post("/api/persona-templates", json={
        "name": "林澈", "identity": "旅行者", "appearance": "银发",
        "personality": "谨慎", "speaking_style": "简短", "world_book_ids": [world_id],
    })
    assert persona.status_code == 201
    character = client.post("/api/character-templates", json={
        "name": "守门人", "first_message": "夜深了，你为何而来？",
        "alternate_greetings": ["门已经关了。"], "tags": ["奇幻", "NPC"],
        "favorite": True, "world_book_ids": [world_id],
    })
    assert character.status_code == 201
    duplicate = client.post(f"/api/character-templates/{character.json()['id']}/duplicate")
    assert duplicate.status_code == 201
    assert duplicate.json()["name"].endswith("副本")

    story = client.post("/api/chats", json={
        "title": "午夜门扉", "persona_template_id": persona.json()["id"],
        "character_template_ids": [character.json()["id"]],
    })
    assert story.status_code == 201
    story_id = story.json()["id"]
    snapshot = client.get(f"/api/chats/{story_id}/persona")
    assert snapshot.status_code == 200
    assert snapshot.json()["name"] == "林澈"
    story_world = client.get(f"/api/chats/{story_id}/world-books").json()
    assert len(story_world) == 1
    assert story_world[0]["scan_depth"] == 8
    messages = client.get(f"/api/chats/{story_id}/messages").json()
    assert messages[0]["content"] == "夜深了，你为何而来？"
    variants = client.get(f"/api/chats/{story_id}/message-variants").json()
    assert len(variants) == 2


def test_chat_turn_can_stream_ndjson_events(
    client: TestClient,
    chat_id: str,
) -> None:
    with client.stream(
        "POST",
        f"/api/chats/{chat_id}/turns/stream",
        json={"content": "沿着钟楼继续前进。"},
    ) as response:
        assert response.status_code == 200
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert events[0]["type"] == "user"
    assert any(item["type"] == "chunk" for item in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["turn"]["assistant_message"]["content"]
