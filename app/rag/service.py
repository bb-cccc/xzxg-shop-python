from __future__ import annotations

# 检索增强模块：负责文本切片、关键词重排和图片索引。

from dataclasses import dataclass, field
from typing import Protocol

from app.rag.ranker import Candidate, rank_candidates


# 外部能力适配器，对上层提供稳定的调用接口。
class VectorProvider(Protocol):
    async def search_knowledge(self, query: str, limit: int) -> list[Candidate]: ...


# 模块中的核心类型，封装相关状态和行为。
@dataclass
class RetrievalResult:
    candidates: list[Candidate]
    trace: dict[str, object] = field(default_factory=dict)


# 领域服务，编排多个组件完成一项业务操作。
class RAGService:

    def __init__(self, repository, vector_provider: VectorProvider | None = None) -> None:
        self.repository = repository
        self.vector_provider = vector_provider

    async def search_knowledge(self, query: str, limit: int = 5, filters: dict[str, object] | None = None) -> RetrievalResult:
        del filters  # structured filters are applied by the future Milvus/RDS adapter
        keyword_rows = await self.repository.search_knowledge(query, max(5, min(limit * 8, 50)))
        keyword = [Candidate(chunk_id=row.chunk_id, title=row.title, snippet=row.snippet or getattr(row, "content", ""), source=row.source) for row in keyword_rows]
        vector: list[Candidate] = []
        vector_error = ""
        if self.vector_provider is not None:
            try:
                vector = await self.vector_provider.search_knowledge(query, max(limit * 8, 10))
            except (OSError, RuntimeError, ValueError, TypeError) as error:  # provider failure is a planned fallback
                vector_error = type(error).__name__
        merged = {item.chunk_id: item for item in [*keyword, *vector]}
        ranked = rank_candidates(list(merged.values()), query, limit)
        return RetrievalResult(ranked, {"keyword_hit_ids": [item.chunk_id for item in keyword], "vector_hit_ids": [item.chunk_id for item in vector], "rerank_top_ids": [item.chunk_id for item in ranked], "vector_status": "unavailable" if vector_error else ("enabled" if self.vector_provider else "disabled"), "vector_error": vector_error})


def build_vector_provider(settings) -> VectorProvider | None:
    if not getattr(settings, "rag_vector_enabled", False) or str(getattr(settings, "rag_vector_provider", "none")).lower() != "milvus":
        return None
    from app.integrations.milvus import MilvusVectorProvider

    return MilvusVectorProvider(
        address=getattr(settings, "milvus_address", "http://127.0.0.1:19530"),
        collection=getattr(settings, "milvus_knowledge_collection", "knowledge_text_chunks"),
        embedding_base_url=getattr(settings, "embedding_base_url", getattr(settings, "ai_base_url", "")),
        embedding_api_key=getattr(settings, "embedding_api_key", "") or getattr(settings, "ai_api_key", ""),
        embedding_model=getattr(settings, "embedding_model", "text-embedding-v4"),
        token=getattr(settings, "milvus_token", ""),
        timeout_seconds=float(getattr(settings, "image_embedding_timeout_seconds", 20.0)),
        embedding_provider=getattr(settings, "embedding_provider", "dashscope"),
        embedding_dimension=int(getattr(settings, "embedding_dimension", 128)),
    )


def build_image_vector_provider(settings):
    if not getattr(settings, "rag_vector_enabled", False) or str(getattr(settings, "rag_vector_provider", "none")).lower() != "milvus":
        return None
    from app.integrations.milvus import MilvusVectorProvider

    provider = str(getattr(settings, "image_embedding_provider", "dashscope")).lower()
    dimension = 64 if provider in {"local", "local_histogram", "histogram"} else int(getattr(settings, "image_embedding_dimension", 1536))
    collection = getattr(settings, "milvus_image_collection", "product_image_vectors_v1536")
    if provider in {"local", "local_histogram", "histogram"} and collection == "product_image_vectors_v1536":
        collection = "product_image_vectors_v64"
    return MilvusVectorProvider(
        address=getattr(settings, "milvus_address", "http://127.0.0.1:19530"),
        collection=collection,
        embedding_base_url="",
        embedding_api_key="",
        token=getattr(settings, "milvus_token", ""),
        timeout_seconds=float(getattr(settings, "image_embedding_timeout_seconds", 20.0)),
        embedding_provider="local_hash",
        embedding_dimension=dimension,
    )

