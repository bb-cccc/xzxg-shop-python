from __future__ import annotations


# RAG 服务编排：组合切片、召回和重排流程。

from dataclasses import dataclass, field
from typing import Protocol

from app.rag.ranker import Candidate, rank_candidates


class VectorProvider(Protocol):
    """向量检索适配器协议，可接入 Milvus、RDS 或测试实现。"""
    async def search_knowledge(self, query: str, limit: int) -> list[Candidate]: ...


@dataclass
class RetrievalResult:
    """检索候选及本次检索各阶段 ID 和状态信息。"""
    candidates: list[Candidate]
    trace: dict[str, object] = field(default_factory=dict)


class RAGService:
    """编排关键词召回、可选向量召回、去重和重排。"""

    def __init__(self, repository, vector_provider: VectorProvider | None = None) -> None:
        """保存关键词仓储和可选向量提供器；向量故障时允许降级。"""
        self.repository = repository
        self.vector_provider = vector_provider

    async def search_knowledge(self, query: str, limit: int = 5, filters: dict[str, object] | None = None) -> RetrievalResult:
        """执行知识检索，返回排序后的候选及可审计 trace。"""
        del filters  # structured filters are applied by the future Milvus/RDS adapter
        # 放大关键词召回数量，为后续重排保留候选空间。
        keyword_rows = await self.repository.search_knowledge(query, max(5, min(limit * 8, 50)))
        # 将 ORM 记录转换为 RAG 层统一的 Candidate，隔离数据库模型。
        keyword = [Candidate(chunk_id=row.chunk_id, title=row.title, snippet=row.snippet or getattr(row, "content", ""), source=row.source) for row in keyword_rows]
        vector: list[Candidate] = []
        vector_error = ""
        if self.vector_provider is not None:
            # 向量召回是增强能力，失败时继续使用关键词召回结果。
            try:
                vector = await self.vector_provider.search_knowledge(query, max(limit * 8, 10))
            except Exception as error:  # provider failure is a planned fallback
                # 只记录异常类型，避免把连接细节暴露给调用方。
                vector_error = type(error).__name__
        merged = {item.chunk_id: item for item in [*keyword, *vector]}
        # 使用 chunk_id 去重，避免两个召回源重复展示同一片段。
        ranked = rank_candidates(list(merged.values()), query, limit)
        # trace 记录各阶段命中 ID，便于定位召回或重排问题。
        return RetrievalResult(ranked, {"keyword_hit_ids": [item.chunk_id for item in keyword], "vector_hit_ids": [item.chunk_id for item in vector], "rerank_top_ids": [item.chunk_id for item in ranked], "vector_status": "unavailable" if vector_error else ("enabled" if self.vector_provider else "disabled"), "vector_error": vector_error})

