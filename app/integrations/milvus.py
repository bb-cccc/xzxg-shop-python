"""Milvus REST v2 adapter for text retrieval."""

from __future__ import annotations

# 外部服务适配器模块：统一对象存储、向量、重排和配置中心接口。

import asyncio
import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from app.rag.ranker import Candidate


# 模块中的核心类型，封装相关状态和行为。
class MilvusUnavailable(RuntimeError):
    pass


def flatten_search_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize Milvus REST v2 flat and nested entity result shapes."""
    entity = row.get("entity") if isinstance(row.get("entity"), dict) else row
    item = dict(entity)
    if row.get("id") is not None and not item.get("image_vector_id") and not item.get("chunk_id"):
        item["id"] = row.get("id")
    if row.get("distance") is not None and item.get("score") is None:
        item["score"] = row.get("distance")
    return item


def _normalise(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= 0:
        return vector
    return [value / magnitude for value in vector]


def _local_embedding(text: str, dimension: int) -> list[float]:
    """Return a repeatable local vector for development and smoke tests."""

    size = max(32, min(int(dimension or 128), 2048))
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    tokens = [value] if value else ["empty"]
    tokens.extend(part for part in re.split(r"[^\w\u4e00-\u9fff]+", value) if part)
    for width in (2, 3):
        tokens.extend(value[index : index + width] for index in range(max(0, len(value) - width + 1)))
    vector = [0.0] * size
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % size
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
        vector[int.from_bytes(digest[5:9], "big") % size] += 0.5 * sign
    return _normalise(vector)


# 外部能力适配器，对上层提供稳定的调用接口。
@dataclass(slots=True)
class MilvusVectorProvider:
    address: str
    collection: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str = "text-embedding-v4"
    token: str = ""
    timeout_seconds: float = 20.0
    embedding_provider: str = "dashscope"
    embedding_dimension: int = 128

    @property
    def uses_local_embedding(self) -> bool:
        provider = self.embedding_provider.strip().lower()
        return provider in {"local", "local_hash", "hash"} or not self.embedding_api_key.strip()

    async def _embedding_many(self, texts: list[str]) -> list[list[float]]:
        if self.uses_local_embedding:
            return [_local_embedding(text, self.embedding_dimension) for text in texts]
        if not self.embedding_base_url.strip():
            raise MilvusUnavailable("text embedding base URL is empty")
        url = self.embedding_base_url.rstrip("/") + "/embeddings"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    url,
                    json={"model": self.embedding_model, "input": texts},
                    headers={"Authorization": f"Bearer {self.embedding_api_key}"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise MilvusUnavailable("text embedding service unavailable") from error
        rows = payload.get("data") if isinstance(payload, dict) else None
        vectors = [row.get("embedding") for row in rows or [] if isinstance(row, dict)]
        if len(vectors) != len(texts) or any(not isinstance(vector, list) or not vector for vector in vectors):
            raise MilvusUnavailable("text embedding response is empty or incomplete")
        return [[float(value) for value in vector] for vector in vectors]

    async def _embedding(self, query: str) -> list[float]:
        return (await self._embedding_many([query]))[0]

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.address.rstrip("/") + path, json=payload, headers=headers)
                response.raise_for_status()
                result = response.json() if response.content else {}
        except (httpx.HTTPError, ValueError, TypeError) as error:
            detail = getattr(getattr(error, "response", None), "text", "")
            raise MilvusUnavailable(f"Milvus request failed: {path} {detail}") from error
        if isinstance(result, dict) and int(result.get("code", 0) or 0) not in {0, 200}:
            raise MilvusUnavailable(str(result.get("message") or f"Milvus returned code {result.get('code')}"))
        return result if isinstance(result, dict) else {}

    async def probe_image_collection(self, dimension: int, *, has_index: bool) -> dict[str, bool]:
        """Report service, collection, index and query readiness separately."""
        states = {"service_ready": False, "collection_ready": False, "index_ready": bool(has_index), "query_ready": False}
        base = self.address.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout_seconds, 5.0)) as client:
                response = await client.get(base + "/healthz")
                if response.status_code == 404:
                    response = await client.post(base + "/v2/vectordb/collections/list", json={"dbName": "default"})
                response.raise_for_status()
                body = response.json() if response.content else {}
                if isinstance(body, dict) and int(body.get("code", 0) or 0) not in {0, 200}:
                    raise MilvusUnavailable("Milvus service returned an error")
        except (httpx.HTTPError, MilvusUnavailable, ValueError, TypeError, OSError) as error:
            raise MilvusUnavailable("Milvus service is not ready") from error
        states["service_ready"] = True
        try:
            await self._post("/v2/vectordb/collections/describe", {"dbName": "default", "collectionName": self.collection})
        except MilvusUnavailable:
            return states
        states["collection_ready"] = True
        if not has_index:
            return states
        # A unit vector makes a real search request without exposing product data.
        query_vector = [0.0] * max(1, int(dimension))
        query_vector[0] = 1.0
        try:
            await self._post(
                "/v2/vectordb/entities/search",
                {
                    "dbName": "default",
                    "collectionName": self.collection,
                    "data": [query_vector],
                    "annsField": "embedding",
                    "limit": 1,
                    "outputFields": ["image_vector_id", "product_id"],
                    "searchParams": {"metricType": "COSINE"},
                },
            )
            states["query_ready"] = True
        except MilvusUnavailable:
            return states
        return states

    async def ensure_collection(self, dimension: int | None = None, primary_field: str = "chunk_id") -> None:
        dimension = max(1, int(dimension or self.embedding_dimension or 128))
        try:
            await self._post("/v2/vectordb/collections/describe", {"dbName": "default", "collectionName": self.collection})
        except MilvusUnavailable as error:
            message = str(error).lower()
            if "404" not in message and "not found" not in message and "does not exist" not in message and "collection" not in message:
                raise
            try:
                await self._post(
                    "/v2/vectordb/collections/create",
                    {
                        "dbName": "default",
                        "collectionName": self.collection,
                        "dimension": dimension,
                        "primaryFieldName": primary_field,
                        "idType": "VarChar",
                        "vectorFieldName": "embedding",
                        "metricType": "COSINE",
                        "autoID": False,
                        "enableDynamicField": True,
                        "params": {"max_length": 256},
                    },
                )
            except MilvusUnavailable as create_error:
                if "already" not in str(create_error).lower() and "exist" not in str(create_error).lower():
                    raise
        try:
            await self._post("/v2/vectordb/collections/load", {"dbName": "default", "collectionName": self.collection})
        except MilvusUnavailable:
            return

    async def upsert_knowledge(self, rows: Iterable[Any]) -> int:
        values = list(rows)
        if not values:
            return 0
        texts = [f"{getattr(row, 'title', '')} {getattr(row, 'snippet', '')} {getattr(row, 'content', '')}".strip() for row in values]
        vectors = await self._embedding_many(texts)
        await self.ensure_collection(len(vectors[0]))
        entities = [
            {
                "chunk_id": str(getattr(row, "chunk_id", "")),
                "title": str(getattr(row, "title", "")),
                "snippet": str(getattr(row, "snippet", "")),
                "source": str(getattr(row, "source", "")),
                "embedding": vector,
            }
            for row, vector in zip(values, vectors)
        ]
        await self._post("/v2/vectordb/entities/upsert", {"dbName": "default", "collectionName": self.collection, "data": entities})
        return len(entities)

    async def upsert_image_vectors(self, rows: Iterable[dict[str, Any]]) -> int:
        values = [row for row in rows if row.get("embedding")]
        if not values:
            return 0
        dimension = len(values[0]["embedding"])
        await self.ensure_collection(dimension, primary_field="image_vector_id")
        entities = [
            {
                "image_vector_id": str(row.get("image_vector_id") or ""),
                "product_id": str(row.get("product_id") or ""),
                "image_url": str(row.get("image_url") or ""),
                "image_type": str(row.get("image_type") or "product"),
                "embedding": [float(value) for value in row["embedding"]],
            }
            for row in values
        ]
        await self._post("/v2/vectordb/entities/upsert", {"dbName": "default", "collectionName": self.collection, "data": entities})
        return len(entities)

    async def _search_entities(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        # Milvus standalone is eventually consistent after an upsert. A short
        # bounded retry keeps an index build immediately searchable without
        # turning a provider failure into an unbounded request.
        for attempt in range(3):
            result = await self._post("/v2/vectordb/entities/search", payload)
            rows = result.get("data") or result.get("results") or []
            if rows or attempt == 2:
                return [row for row in rows if isinstance(row, dict)]
            await asyncio.sleep(0.2 * (attempt + 1))
        return []

    async def search_image(self, vector: list[float], limit: int) -> list[dict[str, Any]]:
        await self.ensure_collection(len(vector), primary_field="image_vector_id")
        rows = await self._search_entities({
            "dbName": "default",
            "collectionName": self.collection,
            "data": [vector],
            "annsField": "embedding",
            "limit": max(1, min(limit, 100)),
            "outputFields": ["image_vector_id", "product_id", "image_url", "image_type"],
            "searchParams": {"metricType": "COSINE"},
        })
        output: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = flatten_search_row(row)
            if row.get("id") is not None and not item.get("image_vector_id"):
                item["image_vector_id"] = row.get("id")
            if row.get("distance") is not None and item.get("score") is None:
                item["score"] = row.get("distance")
            if item.get("product_id"):
                output.append(item)
        return output

    async def search_knowledge(self, query: str, limit: int) -> list[Candidate]:
        vector = await self._embedding(query)
        await self.ensure_collection(len(vector))
        rows = await self._search_entities({
            "dbName": "default",
            "collectionName": self.collection,
            "data": [vector],
            "annsField": "embedding",
            "limit": max(1, min(limit, 100)),
            "outputFields": ["chunk_id", "title", "snippet", "source"],
            "searchParams": {"metricType": "COSINE"},
        })
        output: list[Candidate] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            entity = flatten_search_row(row)
            chunk_id = entity.get("chunk_id") or entity.get("id")
            if not chunk_id:
                continue
            output.append(
                Candidate(
                    chunk_id=str(chunk_id),
                    title=str(entity.get("title") or ""),
                    snippet=str(entity.get("snippet") or ""),
                    source=str(entity.get("source") or ""),
                    score=float(row.get("distance") or row.get("score") or 0.0),
                )
            )
        return output
