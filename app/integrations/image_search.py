from __future__ import annotations

# 外部服务适配器模块：统一对象存储、向量、重排和配置中心接口。

import math
import time
from typing import Any

from app.integrations.image_embedding import ImageEmbeddingError, ImageEmbedder
from app.integrations.objectstore import ObjectStoreError


def _product_payload(product, merchant, sku) -> dict[str, Any]:
    from app.domain.schemas import amount_string

    return {
        "productId": product.product_id, "skuId": sku.sku_id if sku and sku.sku_id else None,
        "merchantId": merchant.merchant_id, "merchantName": merchant.name, "name": product.name,
        "brand": product.brand, "categoryId": product.category_id, "imageUrl": product.image_url,
        "price": amount_string(product.price), "marketPrice": amount_string(product.market_price),
        "stockStatus": product.stock_status, "tags": list(product.tags_json or []),
        "sellingPoints": list(product.selling_points_json or []), "recommendReason": product.recommend_reason,
        "riskNotes": list(product.risk_notes_json or []),
    }


def cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


# 领域服务，编排多个组件完成一项业务操作。
class ImageSearchService:
    def __init__(self, repository, settings, object_store, embedder: ImageEmbedder, account_id: str = "", is_admin: bool = False, vector_provider=None) -> None:
        self.repository = repository
        self.settings = settings
        self.object_store = object_store
        self.embedder = embedder
        self.account_id = account_id
        self.is_admin = is_admin
        self.vector_provider = vector_provider

    @staticmethod
    def file_id_from_url(value: str) -> str:
        marker = "/api/v1/files/"
        if marker not in value:
            return ""
        rest = value.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
        return rest.split("/", 1)[0] if rest.startswith("file_") else ""

    async def _query_vector(self, *, file_id: str, object_key: str, image_url: str, data: bytes | None, content_type: str = "") -> tuple[list[float], int]:
        if data is not None:
            return await self.embedder.embed_bytes(data, content_type), 0
        if file_id:
            started = time.perf_counter()
            stored = await self.repository.get_stored_file(self.account_id, file_id, is_admin=self.is_admin)
            if stored is None:
                raise FileNotFoundError(file_id)
            obj = await self.object_store.get(stored.object_key, stored.mime_type)
            return await self.embedder.embed_bytes(obj.data, stored.mime_type), int((time.perf_counter() - started) * 1000)
        if object_key:
            started = time.perf_counter()
            obj = await self.object_store.get(object_key)
            return await self.embedder.embed_bytes(obj.data, obj.content_type), int((time.perf_counter() - started) * 1000)
        return await self.embedder.embed_source(image_url), 0

    async def _milvus_vectors(self, vector: list[float]) -> list[tuple[float, dict[str, Any]]]:
        if self.vector_provider is None:
            return []
        try:
            hits = await self.vector_provider.search_image(vector, 50)
        except (OSError, RuntimeError, ValueError, TypeError):
            return []
        vectors: list[tuple[float, dict[str, Any]]] = []
        for hit in hits:
            product_id = str(hit.get("product_id") or "")
            if not product_id:
                continue
            record = await self.repository.get_product_record(product_id)
            if record is None:
                continue
            product, merchant, sku = record
            vectors.append((float(hit.get("distance") or hit.get("score") or 0.0), _product_payload(product, merchant, sku)))
        return vectors

    async def search(self, *, file_id: str = "", object_key: str = "", image_url: str = "", data: bytes | None = None, content_type: str = "", top_k: int = 5) -> dict[str, Any]:
        started = time.perf_counter()
        file_id = file_id.strip()
        object_key = object_key.strip()
        image_url = image_url.strip()
        if not file_id and image_url:
            file_id = self.file_id_from_url(image_url)
            if file_id:
                image_url = ""
        if not any((file_id, object_key, image_url, data is not None)):
            raise ValueError("empty_image")
        download_ms = 0
        embedding_started = time.perf_counter()
        try:
            vector, download_ms = await self._query_vector(file_id=file_id, object_key=object_key, image_url=image_url, data=data, content_type=content_type)
        except FileNotFoundError as error:
            raise error
        except (ImageEmbeddingError, ObjectStoreError) as error:
            raise error
        embedding_ms = int((time.perf_counter() - embedding_started) * 1000)
        search_started = time.perf_counter()
        scored = await self._milvus_vectors(vector)
        scored.sort(key=lambda item: (-item[0], item[1].get("productId", "")))
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for score, item in scored:
            product_id = str(item.get("productId", ""))
            if product_id in seen:
                continue
            seen.add(product_id)
            normalized = dict(item)
            normalized["imageRelevance"] = round(max(0.0, min(score, 1.0)), 6)
            items.append(normalized)
            if len(items) >= max(1, min(top_k, 20)):
                break
        vector_search_ms = int((time.perf_counter() - search_started) * 1000)
        status = "matched" if items else "no_match"
        match_status = "ok" if items else ("no_vector_hit" if scored else "image_vector_index_unavailable")
        return {
            "relevance_status": status,
            "match_status": match_status,
            "items": items,
            "durations": {
                "total_ms": int((time.perf_counter() - started) * 1000),
                "download_ms": download_ms,
                "embedding_ms": embedding_ms,
                "vector_search_ms": vector_search_ms,
                "rerank_ms": 0,
            },
            "provider": self.embedder.provider,
            "dimension": self.embedder.dimension,
        }

