"""独立 reranker 客户端的协议与解析测试。"""

import asyncio

from backend.config import Settings
from backend.reranker import RerankerClient


def test_reranker_uses_independent_endpoint_and_parses_scores(monkeypatch: object) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"results": [{"index": 1, "relevance_score": 0.92}, {"index": 0, "relevance_score": 0.31}]}

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, object], headers: dict[str, str]) -> FakeResponse:
            captured.update(url=url, json=json, headers=headers)
            return FakeResponse()

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "backend.reranker.httpx.AsyncClient", lambda **_kwargs: FakeClient()
    )
    settings = Settings(
        database_url="sqlite://",
        llm_base_url=None,
        llm_api_key=None,
        llm_model=None,
        embedding_model=None,
        max_agent_steps=4,
        recent_message_limit=16,
        rag_limit=5,
        rerank_base_url="https://rank.example/v1",
        rerank_api_key="secret",
        rerank_model="rank-model",
    )
    scores = asyncio.run(RerankerClient(settings).rerank("银铃", ["文档甲", "文档乙"]))

    assert captured["url"] == "https://rank.example/v1/rerank"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["json"] == {
        "model": "rank-model",
        "query": "银铃",
        "documents": ["文档甲", "文档乙"],
        "top_n": 2,
        "return_documents": False,
    }
    assert [(item.index, item.score) for item in scores] == [(1, 0.92), (0, 0.31)]
