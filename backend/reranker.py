"""独立 rerank 服务客户端，兼容 Cohere/Jina 风格的 /rerank 接口。"""

from dataclasses import dataclass

import httpx

from backend.config import Settings


@dataclass(slots=True)
class RerankScore:
    index: int
    score: float


class RerankerClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = (settings.rerank_base_url or "").rstrip("/")
        self.api_key = settings.rerank_api_key or ""
        self.model = settings.rerank_model or ""
        self.timeout = settings.request_timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    async def rerank(self, query: str, documents: list[str]) -> list[RerankScore]:
        if not self.configured or not documents:
            return []
        url = self.base_url if self.base_url.endswith("/rerank") else f"{self.base_url}/rerank"
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "return_documents": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"reranker 请求失败：{exc}") from exc
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise RuntimeError("reranker 响应缺少 results")
        parsed: list[RerankScore] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(
                    RerankScore(
                        index=int(item["index"]),
                        score=float(item.get("relevance_score", item.get("score", 0))),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return parsed
