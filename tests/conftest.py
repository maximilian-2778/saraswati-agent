"""后端测试共用的临时应用和数据库。"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app


@pytest.fixture
def client(tmp_path: object) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "test.db"  # type: ignore[operator]
    settings = Settings(
        database_url=f"sqlite:///{database_path.as_posix()}",
        llm_base_url=None,
        llm_api_key=None,
        llm_model=None,
        embedding_model=None,
        max_agent_steps=3,
        recent_message_limit=12,
        rag_limit=4,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def chat_id(client: TestClient) -> str:
    response = client.post(
        "/api/chats",
        json={"title": "测试存档", "system_prompt": "保持叙事连贯。"},
    )
    assert response.status_code == 201
    return response.json()["id"]
