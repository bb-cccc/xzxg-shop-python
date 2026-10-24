from __future__ import annotations

# 检索增强模块：负责文本切片、关键词重排和图片索引。

import hashlib
import time
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from app.domain.models import ProductImageVector
from app.integrations.image_embedding import ImageEmbeddingError


@dataclass(slots=True)
class ImageIndexReport:
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    vector_indexed: int = 0
    vector_failed: bool = False
    errors: list[dict[str, str]] | None = None
    duration_ms: int = 0

    def payload(self) -> dict[str, object]:
        return {"indexed": self.indexed, "skipped": self.skipped, "failed": self.failed, "vector_indexed": self.vector_indexed, "vector_failed": self.vector_failed, "errors": self.errors or [], "duration_ms": self.duration_ms}


async def index_product_images(repository, embedder, *, limit: int = 0, force: bool = False, vector_provider=None) -> ImageIndexReport:
    started = time.perf_counter()
    report = ImageIndexReport(errors=[])
    milvus_rows: list[dict[str, object]] = []
    rows = await repository.list_image_products()
    if limit > 0:
        rows = rows[:limit]
    for product, _merchant, _sku in rows:
        sources = [product.image_url, *(product.image_urls_json or [])]
        for source in sources:
            source = str(source or "").strip()
            if not source:
                continue
            content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
            if not force:
                dimension = int(getattr(embedder, "dimension", 0) or 0)
                existing = await repository.get_product_image_vector(product.product_id, source, embedder.provider, dimension)
                if existing is not None:
                    report.skipped += 1
                    continue
            try:
                vector = await embedder.embed_source(source)
                item = ProductImageVector(
                    vector_id=repository._new_id("imgvec"), product_id=product.product_id, image_url=source,
                    provider=embedder.provider, dimension=len(vector), embedding_json=vector, content_hash=content_hash,
                    metadata_json={"indexed_by": "python_image_indexer"},
                )
                await repository.upsert_product_image_vector(item)
                milvus_rows.append({"image_vector_id": item.vector_id, "product_id": item.product_id, "image_url": item.image_url, "image_type": "product", "embedding": vector})
                report.indexed += 1
            except (ImageEmbeddingError, SQLAlchemyError, OSError, ValueError, TypeError) as error:
                report.failed += 1
                report.errors.append({"product_id": product.product_id, "image_url": source, "error": type(error).__name__})
    if vector_provider is not None and milvus_rows:
        try:
            report.vector_indexed = await vector_provider.upsert_image_vectors(milvus_rows)
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            report.vector_failed = True
            report.errors.append({"product_id": "", "image_url": "", "error": f"milvus_{type(error).__name__}"})
    report.duration_ms = int((time.perf_counter() - started) * 1000)
    return report
