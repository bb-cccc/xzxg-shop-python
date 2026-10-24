from __future__ import annotations

# 外部服务适配器模块：统一对象存储、向量、重排和配置中心接口。

from dataclasses import dataclass
from typing import Any

import httpx


class RerankUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class RerankResult:
    index: int
    score: float


@dataclass(slots=True)
class ProductReranker:
    base_url: str
    api_key: str
    model: str = "qwen3-vl-rerank"
    timeout_seconds: float = 20.0

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankResult]:
        if not self.api_key.strip():
            raise RerankUnavailable("rerank API key is empty")
        if not documents:
            return []
        payload: dict[str, Any] = {
            "model": self.model,
            "input": {"query": query.strip(), "documents": documents},
            "parameters": {"top_n": max(1, min(top_n, len(documents))), "return_documents": False, "instruct": "根据用户电商导购需求，对候选商品按直接相关性、品牌/品类/属性约束匹配度排序；明显违背用户需求的商品排到后面。"},
        }
        url = self.base_url.rstrip("/") + "/api/v1/services/rerank/text-rerank/text-rerank"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, json=payload, headers={"Authorization": f"Bearer {self.api_key.strip()}", "Content-Type": "application/json"})
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise RerankUnavailable("rerank request failed") from error
        body = response.json()
        error = body.get("error") or {}
        if error.get("message"):
            raise RerankUnavailable(str(error["message"]))
        results = []
        for item in (body.get("output") or {}).get("results") or []:
            try:
                index = int(item.get("index"))
                if 0 <= index < len(documents):
                    results.append(RerankResult(index=index, score=float(item.get("relevance_score") or 0.0)))
            except (TypeError, ValueError):
                continue
        if not results:
            raise RerankUnavailable("rerank response is empty")
        return results
