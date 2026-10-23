from __future__ import annotations

# 数据访问模块：把业务查询封装为异步 Repository 操作。

from app.repositories.sql_support import *  # noqa: F401,F403


# 能力混入类，把这一领域的操作组合到主类中。
class RagRepositoryMixin:
    # 执行搜索 search_knowledge 
    async def search_knowledge(self, query: str, limit: int=5) -> list[KnowledgeChunk]:
        from app.rag.tokenize import query_terms
        query = query.strip()
        terms = query_terms(query)[:8]
        if not terms and query:
            terms = [query]
        conditions = []
        for term in terms:
            like = f'%{term}%'
            conditions.append(or_(KnowledgeChunk.title.ilike(like), KnowledgeChunk.snippet.ilike(like), KnowledgeChunk.content.ilike(like)))
        stmt = select(KnowledgeChunk)
        if conditions:
            stmt = stmt.where(or_(*conditions))
        stmt = stmt.order_by(KnowledgeChunk.sort_order, KnowledgeChunk.chunk_id).limit(max(1, min(limit, 20)))
        return list((await self.session.execute(stmt)).scalars().all())

    # 列出 list_knowledge_chunks 
    async def list_knowledge_chunks(self, document_id: str) -> list[KnowledgeChunk]:
        stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id).order_by(KnowledgeChunk.sort_order, KnowledgeChunk.chunk_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def ingest_knowledge_document(self, merchant_id: str, title: str, doc_type: str, content: str, source_url: str='', metadata: dict[str, object] | None=None, force_reindex: bool=False) -> KnowledgeDocument:
        from app.rag.splitter import split_document
        title = title.strip()
        content = content.strip()
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        if not force_reindex:
            existing = await self.session.scalar(select(KnowledgeDocument).where(KnowledgeDocument.merchant_id == merchant_id, KnowledgeDocument.content_hash == content_hash).order_by(KnowledgeDocument.created_at.desc()))
            if existing is not None:
                return existing
        drafts = split_document(title, content, doc_type)
        now = datetime.now(timezone.utc)
        document = KnowledgeDocument(document_id=self._new_id('doc'), merchant_id=merchant_id, title=title, doc_type=doc_type.strip(), content=content, status='indexed', chunk_count=len(drafts), source_url=source_url.strip(), content_hash=content_hash, metadata_json=metadata or {}, created_at=now, updated_at=now)
        self.session.add(document)
        for draft in drafts:
            self.session.add(KnowledgeChunk(chunk_id=self._new_id('ck'), document_id=document.document_id, title=str(draft['title']), content=str(draft['content']), snippet=str(draft['snippet']), source=document.document_id, doc_type=document.doc_type, merchant_id=merchant_id, metadata_json=metadata or {}, sort_order=int(draft['sort_order']), created_at=now, updated_at=now))
        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def get_knowledge_document_by_hash(self, merchant_id: str, content_hash: str) -> KnowledgeDocument | None:
        return await self.session.scalar(select(KnowledgeDocument).where(KnowledgeDocument.merchant_id == merchant_id, KnowledgeDocument.content_hash == content_hash).order_by(KnowledgeDocument.created_at.desc()))

    async def list_knowledge_documents(self, merchant_id: str, page: int, page_size: int) -> tuple[list[KnowledgeDocument], int]:
        filters = [KnowledgeDocument.merchant_id == merchant_id] if merchant_id else []
        total = int((await self.session.execute(select(func.count(KnowledgeDocument.document_id)).where(*filters))).scalar_one() or 0)
        stmt = select(KnowledgeDocument).where(*filters).order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.document_id).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)

    async def create_stored_file(self, file: StoredFile) -> StoredFile:
        self.session.add(file)
        await self.session.commit()
        await self.session.refresh(file)
        return file

    async def get_stored_file(self, account_id: str, file_id: str, *, is_admin: bool=False) -> StoredFile | None:
        stmt = select(StoredFile).where(StoredFile.file_id == file_id)
        if not is_admin:
            stmt = stmt.where(StoredFile.account_id == account_id)
        return await self.session.scalar(stmt)

    async def list_image_products(self) -> list[tuple[Product, Merchant, ProductSKU | None]]:
        visible_product, visible_merchant = self._visible_product_filter()
        rows = await self.session.execute(self._product_record_query().where(visible_product, visible_merchant).order_by(Product.sort_order, Product.product_id))
        return [(product, merchant, sku) for product, merchant, sku in rows.all()]

    async def list_product_image_vectors(self, provider: str, dimension: int) -> list[ProductImageVector]:
        stmt = select(ProductImageVector).where(ProductImageVector.provider == provider, ProductImageVector.dimension == dimension)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_product_image_vector(self, product_id: str, image_url: str, provider: str, dimension: int=0) -> ProductImageVector | None:
        filters = [ProductImageVector.product_id == product_id, ProductImageVector.image_url == image_url, ProductImageVector.provider == provider]
        if dimension > 0:
            filters.append(ProductImageVector.dimension == dimension)
        return await self.session.scalar(select(ProductImageVector).where(*filters))

    async def upsert_product_image_vector(self, vector: ProductImageVector) -> ProductImageVector:
        existing = await self.session.scalar(select(ProductImageVector).where(ProductImageVector.product_id == vector.product_id, ProductImageVector.image_url == vector.image_url))
        if existing is None:
            self.session.add(vector)
            existing = vector
        else:
            existing.provider = vector.provider
            existing.dimension = vector.dimension
            existing.embedding_json = vector.embedding_json
            existing.content_hash = vector.content_hash
            existing.metadata_json = vector.metadata_json
            existing.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(existing)
        return existing
