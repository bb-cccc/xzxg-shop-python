from __future__ import annotations
# integrations/image_search.py：本模块的中文学习说明。

# 图片向量检索。
# 先把查询图片转成向量，再与商品图片向量计算余弦相似度。
# 相似度越大表示方向越接近，最终按降序返回。
# 空向量、损坏图片和远程失败必须被清晰处理。

# 图片检索适配器：通过向量相似度寻找相关商品。

import math
import time
from typing import Any

from app.domain.models import ProductImageVector
from app.integrations.image_embedding import ImageEmbeddingError, ImageEmbedder, LocalHistogramEmbedder
from app.integrations.objectstore import ObjectStoreError
def _product_payload(product, merchant, sku) -> dict[str, Any]:
    """执行 _product_payload：接收参数 product、merchant、sku，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
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
    """执行 cosine：接收参数 left、right，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


class ImageSearchService:
    """ImageSearchService：封装同一类数据和行为，供上层模块通过稳定接口调用。"""
    def __init__(self, repository, settings, object_store, embedder: ImageEmbedder, account_id: str = "", is_admin: bool = False) -> None:
        """执行 __init__：接收参数 repository、settings、object_store、embedder、account_id、is_admin，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        self.repository = repository
        self.settings = settings
        self.object_store = object_store
        self.embedder = embedder
        self.account_id = account_id
        self.is_admin = is_admin

    @staticmethod
    def file_id_from_url(value: str) -> str:
        """执行 file_id_from_url：接收参数 value，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        marker = "/api/v1/files/"
        if marker not in value:
            return ""
        rest = value.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
        return rest.split("/", 1)[0] if rest.startswith("file_") else ""
    async def _query_vector(self, *, file_id: str, object_key: str, image_url: str, data: bytes | None, content_type: str = "") -> tuple[list[float], int]:
        """执行 _query_vector：接收参数 file_id、object_key、image_url、data、content_type，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
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
    async def _stored_vectors(self, vector: list[float]) -> list[tuple[float, dict[str, Any]]]:
        """执行 _stored_vectors：接收参数 vector，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        vectors: list[tuple[float, dict[str, Any]]] = []
        rows: list[ProductImageVector] = await self.repository.list_product_image_vectors(self.embedder.provider, len(vector))
        for row in rows:
            score = cosine(vector, [float(value) for value in (row.embedding_json or [])])
            record = await self.repository.get_product_record(row.product_id)
            if record is None:
                continue
            product, merchant, sku = record
            vectors.append((score, _product_payload(product, merchant, sku)))
        return vectors
    async def search(self, *, file_id: str = "", object_key: str = "", image_url: str = "", data: bytes | None = None, content_type: str = "", top_k: int = 5) -> dict[str, Any]:
        """执行 search：接收参数 file_id、object_key、image_url、data、content_type、top_k，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
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
        scored = await self._stored_vectors(vector)
        if not scored and isinstance(self.embedder, LocalHistogramEmbedder):
            # Local fallback only considers local product images. It never fans out to
            # arbitrary remote URLs from a user request.
            for product, merchant, sku in await self.repository.list_image_products():
                sources = [product.image_url, *(product.image_urls_json or [])]
                for source in sources:
                    if not source or source.lower().startswith(("http://", "https://")):
                        continue
                    try:
                        candidate = await self.embedder.embed_source(source)
                    except ImageEmbeddingError:
                        continue
                    scored.append((cosine(vector, candidate), _product_payload(product, merchant, sku)))
                    break
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

