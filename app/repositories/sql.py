"""SQLAlchemy 异步仓储实现，集中处理查询、分页、事务和权限过滤。"""

from __future__ import annotations

# SQLAlchemy Repository 实现：把抽象数据操作转换为异步 SQL 查询。

import hashlib
import json
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import String, and_, case, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.domain.models import (
    Account,
    AgentRun,
    AgentTraceEvent,
    AgentPrompt,
    AgentPromptPublishRecord,
    AppConfig,
    AuthToken,
    CartItem,
    Category,
    ChatSession,
    KnowledgeChunk,
    KnowledgeDocument,
    Coupon,
    Merchant,
    Order,
    OrderItem,
    Payment,
    Product,
    ProductImageVector,
    ProductSKU,
    ProductReview,
    PromotionRule,
    UserCoupon,
    UserMessage,
    StoredFile,
)
from app.security.auth import token_digest


class SQLRepository:
    """使用一个异步会话访问账号、商品、会话、订单和运营数据。"""
    def __init__(self, session: AsyncSession) -> None:
        """保存请求范围内的会话；具体方法负责提交或回滚事务。"""
        self.session = session

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    async def get_account_by_username(self, username: str) -> tuple[Account, str] | None:
        stmt = select(Account).where(Account.username == username, Account.status == "active")
        account = (await self.session.execute(stmt)).scalar_one_or_none()
        if account is None:
            return None
        return account, account.password_hash

    async def get_account_by_token(self, token: str, now: datetime) -> Account | None:
        stmt = (
            select(Account)
            .join(AuthToken, AuthToken.account_id == Account.account_id)
            .where(
                AuthToken.token.in_([token_digest(token), token.strip()]),
                AuthToken.expires_at > now,
                Account.status.in_(["active", "risk"]),
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_auth_token(self, account_id: str, token_digest: str, created_at: datetime, expires_at: datetime) -> None:
        self.session.add(AuthToken(token=token_digest, account_id=account_id, created_at=created_at, expires_at=expires_at))
        await self.session.commit()

    async def create_account(self, account: Account) -> Account:
        self.session.add(account)
        await self.session.commit()
        await self.session.refresh(account)
        return account

    async def update_password_hash(self, account_id: str, password_hash: str) -> None:
        await self.session.execute(
            update(Account).where(Account.account_id == account_id).values(password_hash=password_hash, updated_at=datetime.utcnow())
        )
        await self.session.commit()

    def _visible_product_filter(self):
        return Product.status == "active", Merchant.status == "active"

    def _keyword_filter(self, keyword: str):
        raw = keyword.strip()
        terms: list[str] = []
        seen: set[str] = set()
        for item in [raw, *raw.split()]:
            item = item.strip()
            normalized = item.lower()
            if item and normalized not in seen:
                terms.append(item)
                seen.add(normalized)
            if len(terms) >= 10:
                break
        if not terms:
            return None
        clauses = []
        for term in terms:
            pattern = f"%{term}%"
            clauses.append(
                or_(
                    Product.name.ilike(pattern),
                    Product.brand.ilike(pattern),
                    Category.name.ilike(pattern),
                    cast(Product.tags_json, String).ilike(pattern),
                    cast(Product.selling_points_json, String).ilike(pattern),
                )
            )
        return or_(*clauses)

    def _product_record_query(self):
        return (
            select(Product, Merchant, ProductSKU)
            .join(Merchant, Merchant.merchant_id == Product.merchant_id)
            .join(Category, Category.category_id == Product.category_id, isouter=True)
            .join(
                ProductSKU,
                and_(ProductSKU.product_id == Product.product_id, ProductSKU.is_default.is_(True)),
                isouter=True,
            )
        )

    async def list_product_records(self, keyword: str, category_id: str, page: int, page_size: int) -> tuple[list[tuple[Product, Merchant, ProductSKU | None]], int]:
        visible_product, visible_merchant = self._visible_product_filter()
        filters = [visible_product, visible_merchant]
        if category_id:
            filters.append(or_(Product.category_id == category_id, Category.parent_id == category_id))
        keyword_filter = self._keyword_filter(keyword)
        if keyword_filter is not None:
            filters.append(keyword_filter)

        count_stmt = (
            select(func.count(Product.product_id))
            .select_from(Product)
            .join(Merchant, Merchant.merchant_id == Product.merchant_id)
            .join(Category, Category.category_id == Product.category_id, isouter=True)
            .where(*filters)
        )
        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)
        stmt = self._product_record_query().where(*filters).order_by(Product.sort_order, Product.product_id).offset((page - 1) * page_size).limit(page_size)
        rows = (await self.session.execute(stmt)).all()
        return [(product, merchant, sku) for product, merchant, sku in rows], total

    async def get_product_record(self, product_id: str) -> tuple[Product, Merchant, ProductSKU | None] | None:
        # Go's public detail handler reads by product ID without applying the list visibility predicate.
        # Keep that behavior for compatibility; search/list still hide inactive products and merchants.
        stmt = self._product_record_query().where(Product.product_id == product_id)
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None
        product, merchant, sku = row
        return product, merchant, sku

    async def list_product_skus(self, product_id: str) -> Sequence[ProductSKU]:
        stmt = select(ProductSKU).where(ProductSKU.product_id == product_id).order_by(ProductSKU.sku_id)
        return (await self.session.execute(stmt)).scalars().all()

    async def list_categories(self) -> Sequence[Category]:
        stmt = select(Category).order_by(Category.sort_order, Category.category_id)
        return (await self.session.execute(stmt)).scalars().all()

    async def list_merchants(self, page: int, page_size: int) -> tuple[list[Merchant], int]:
        filters = [Merchant.status == "active"]
        count_stmt = select(func.count(Merchant.merchant_id)).where(*filters)
        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)
        stmt = select(Merchant).where(*filters).order_by(Merchant.merchant_id).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(10)}"

    async def create_session(self, account_id: str, title: str) -> ChatSession:
        now = datetime.now(timezone.utc)
        item = ChatSession(
            session_id=self._new_id("sess"),
            account_id=account_id,
            title=title.strip() or "AI 导购",
            summary="",
            message_count=0,
            last_message_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_session(self, account_id: str, session_id: str) -> ChatSession | None:
        stmt = select(ChatSession).where(
            ChatSession.account_id == account_id,
            ChatSession.session_id == session_id,
            ChatSession.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_sessions(self, account_id: str, page: int, page_size: int) -> tuple[list[ChatSession], int]:
        filters = [ChatSession.account_id == account_id, ChatSession.message_count > 0, ChatSession.deleted_at.is_(None)]
        total = int((await self.session.execute(select(func.count(ChatSession.session_id)).where(*filters))).scalar_one() or 0)
        stmt = (
            select(ChatSession)
            .where(*filters)
            .order_by(ChatSession.pinned_at.is_(None), ChatSession.pinned_at.desc(), ChatSession.last_message_at.desc(), ChatSession.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def search_sessions(self, account_id: str, keyword: str, page: int, page_size: int) -> tuple[list[ChatSession], int]:
        keyword = keyword.strip()
        if not keyword:
            return await self.list_sessions(account_id, page, page_size)
        like = f"%{keyword}%"
        filters = [ChatSession.account_id == account_id, ChatSession.message_count > 0, ChatSession.deleted_at.is_(None)]
        stmt_base = (
            select(ChatSession)
            .outerjoin(UserMessage, and_(UserMessage.session_id == ChatSession.session_id, UserMessage.account_id == ChatSession.account_id))
            .where(*filters, or_(ChatSession.title.ilike(like), ChatSession.summary.ilike(like), UserMessage.content.ilike(like)))
            .distinct()
        )
        total = len((await self.session.execute(stmt_base)).scalars().all())
        stmt = stmt_base.order_by(ChatSession.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def update_session(self, account_id: str, session_id: str, title: str, summary: str) -> ChatSession | None:
        item = await self.get_session(account_id, session_id)
        if item is None:
            return None
        if title.strip():
            item.title = title.strip()[:128]
        if summary.strip():
            item.summary = summary.strip()[:500]
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def pin_session(self, account_id: str, session_id: str, pinned: bool) -> ChatSession | None:
        item = await self.get_session(account_id, session_id)
        if item is None:
            return None
        item.pinned_at = datetime.now(timezone.utc) if pinned else None
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete_session(self, account_id: str, session_id: str) -> bool:
        item = await self.get_session(account_id, session_id)
        if item is None:
            return False
        item.deleted_at = datetime.now(timezone.utc)
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True

    async def create_user_message(self, account_id: str, session_id: str, client_message_id: str, content: str, attachments: list[dict[str, object]]) -> tuple[UserMessage, bool]:
        client_message_id = client_message_id.strip() or f"server_{self._new_id('msg')}"
        existing = await self.session.scalar(
            select(UserMessage).where(
                UserMessage.account_id == account_id,
                UserMessage.session_id == session_id,
                UserMessage.client_message_id == client_message_id,
            )
        )
        if existing is not None:
            return existing, False
        now = datetime.now(timezone.utc)
        item = UserMessage(
            message_id=self._new_id("msg"),
            session_id=session_id,
            account_id=account_id,
            client_message_id=client_message_id,
            content=content,
            attachments_json=attachments,
            created_at=now,
        )
        self.session.add(item)
        session = await self.get_session(account_id, session_id)
        if session is None:
            raise ValueError("session not found")
        if session.title in ("", "AI 导购"):
            session.title = content.strip()[:128] or "AI 导购"
        if not session.summary:
            session.summary = content.strip()[:500]
        session.message_count += 1
        session.last_message_at = now
        session.updated_at = now
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(UserMessage).where(
                    UserMessage.account_id == account_id,
                    UserMessage.session_id == session_id,
                    UserMessage.client_message_id == client_message_id,
                )
            )
            if existing is None:
                raise
            return existing, False
        await self.session.refresh(item)
        return item, True

    async def create_run(self, account_id: str, session_id: str, message_id: str) -> tuple[AgentRun, bool]:
        existing = await self.session.scalar(select(AgentRun).where(AgentRun.account_id == account_id, AgentRun.message_id == message_id))
        if existing is not None:
            return existing, False
        now = datetime.now(timezone.utc)
        item = AgentRun(
            run_id=self._new_id("run"),
            session_id=session_id,
            message_id=message_id,
            account_id=account_id,
            status="running",
            trace_id=self._new_id("trace"),
            content="",
            blocks_json=[],
            followups_json=[],
            segments_json=[],
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(select(AgentRun).where(AgentRun.account_id == account_id, AgentRun.message_id == message_id))
            if existing is None:
                raise
            return existing, False
        await self.session.refresh(item)
        return item, True

    async def get_run(self, account_id: str, run_id: str) -> AgentRun | None:
        return await self.session.scalar(select(AgentRun).where(AgentRun.account_id == account_id, AgentRun.run_id == run_id))

    async def update_run_status(self, account_id: str, run_id: str, status: str) -> AgentRun | None:
        item = await self.get_run(account_id, run_id)
        if item is None or (item.status != "running" and status in {"completed", "failed", "canceled"}):
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def update_run_result(self, account_id: str, run_id: str, content: str, blocks: list[dict[str, object]], followups: list[str], segments: list[dict[str, object]]) -> bool:
        item = await self.get_run(account_id, run_id)
        if item is None:
            return False
        item.content = content
        item.blocks_json = blocks
        item.followups_json = followups
        item.segments_json = segments
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True

    async def is_run_canceled(self, run_id: str) -> bool:
        item = await self.session.scalar(select(AgentRun.status).where(AgentRun.run_id == run_id))
        return item == "canceled"

    async def record_trace(self, run_id: str, trace_id: str, account_id: str, stage: str, event_type: str, status: str = "ok", model: str = "", duration_ms: int = 0, error: str = "", metadata: dict[str, object] | None = None) -> None:
        self.session.add(AgentTraceEvent(
            trace_event_id=self._new_id("trc"), run_id=run_id, trace_id=trace_id, account_id=account_id,
            stage=stage, event_type=event_type, model=model, status=status, duration_ms=duration_ms,
            error=error, metadata_json=metadata or {}, created_at=datetime.now(timezone.utc),
        ))
        await self.session.commit()

    async def list_trace(self, account_id: str, run_id: str) -> list[AgentTraceEvent]:
        stmt = select(AgentTraceEvent).where(AgentTraceEvent.account_id == account_id, AgentTraceEvent.run_id == run_id).order_by(AgentTraceEvent.created_at, AgentTraceEvent.trace_event_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_session_detail(self, account_id: str, session_id: str) -> tuple[ChatSession, list[tuple[UserMessage, list[AgentRun]]]] | None:
        session = await self.get_session(account_id, session_id)
        if session is None:
            return None
        messages = list((await self.session.execute(select(UserMessage).where(UserMessage.account_id == account_id, UserMessage.session_id == session_id).order_by(UserMessage.created_at, UserMessage.message_id))).scalars().all())
        result: list[tuple[UserMessage, list[AgentRun]]] = []
        for message in messages:
            runs = list((await self.session.execute(select(AgentRun).where(AgentRun.account_id == account_id, AgentRun.message_id == message.message_id).order_by(AgentRun.created_at, AgentRun.run_id))).scalars().all())
            result.append((message, runs))
        return session, result

    async def last_product_ids(self, account_id: str, session_id: str) -> list[str]:
        stmt = select(AgentRun.blocks_json).where(
            AgentRun.account_id == account_id,
            AgentRun.session_id == session_id,
            AgentRun.status == "completed",
        ).order_by(AgentRun.created_at.desc()).limit(5)
        seen: set[str] = set()
        result: list[str] = []
        for blocks in (await self.session.execute(stmt)).scalars().all():
            for block in blocks or []:
                for product_id in block.get("product_ids", []) if isinstance(block, dict) else []:
                    if product_id not in seen:
                        seen.add(product_id)
                        result.append(product_id)
                product = block.get("product") if isinstance(block, dict) else None
                if isinstance(product, dict) and product.get("productId") and product["productId"] not in seen:
                    seen.add(product["productId"])
                    result.append(product["productId"])
        return result

    async def search_knowledge(self, query: str, limit: int = 5) -> list[KnowledgeChunk]:
        from app.rag.tokenize import query_terms

        query = query.strip()
        terms = query_terms(query)[:8]
        if not terms and query:
            terms = [query]
        conditions = []
        for term in terms:
            like = f"%{term}%"
            conditions.append(or_(KnowledgeChunk.title.ilike(like), KnowledgeChunk.snippet.ilike(like), KnowledgeChunk.content.ilike(like)))
        stmt = select(KnowledgeChunk)
        if conditions:
            stmt = stmt.where(or_(*conditions))
        stmt = stmt.order_by(KnowledgeChunk.sort_order, KnowledgeChunk.chunk_id).limit(max(1, min(limit, 20)))
        return list((await self.session.execute(stmt)).scalars().all())

    async def ingest_knowledge_document(
        self,
        merchant_id: str,
        title: str,
        doc_type: str,
        content: str,
        source_url: str = "",
        metadata: dict[str, object] | None = None,
        force_reindex: bool = False,
    ) -> KnowledgeDocument:
        from app.rag.splitter import split_document

        title = title.strip()
        content = content.strip()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if not force_reindex:
            existing = await self.session.scalar(select(KnowledgeDocument).where(KnowledgeDocument.merchant_id == merchant_id, KnowledgeDocument.content_hash == content_hash).order_by(KnowledgeDocument.created_at.desc()))
            if existing is not None:
                return existing
        drafts = split_document(title, content, doc_type)
        now = datetime.now(timezone.utc)
        document = KnowledgeDocument(
            document_id=self._new_id("doc"), merchant_id=merchant_id, title=title, doc_type=doc_type.strip(), content=content,
            status="indexed", chunk_count=len(drafts), source_url=source_url.strip(), content_hash=content_hash,
            metadata_json=metadata or {}, created_at=now, updated_at=now,
        )
        self.session.add(document)
        for draft in drafts:
            self.session.add(KnowledgeChunk(
                chunk_id=self._new_id("ck"), document_id=document.document_id, title=str(draft["title"]),
                content=str(draft["content"]), snippet=str(draft["snippet"]), source=document.document_id,
                doc_type=document.doc_type, merchant_id=merchant_id, metadata_json=metadata or {},
                sort_order=int(draft["sort_order"]), created_at=now, updated_at=now,
            ))
        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def list_knowledge_documents(self, merchant_id: str, page: int, page_size: int) -> tuple[list[KnowledgeDocument], int]:
        filters = [KnowledgeDocument.merchant_id == merchant_id] if merchant_id else []
        total = int((await self.session.execute(select(func.count(KnowledgeDocument.document_id)).where(*filters))).scalar_one() or 0)
        stmt = select(KnowledgeDocument).where(*filters).order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.document_id).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def create_stored_file(self, file: StoredFile) -> StoredFile:
        self.session.add(file)
        await self.session.commit()
        await self.session.refresh(file)
        return file

    async def get_stored_file(self, account_id: str, file_id: str, *, is_admin: bool = False) -> StoredFile | None:
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

    async def _cart_rows(self, account_id: str):
        stmt = (
            select(CartItem, Product, Merchant, ProductSKU)
            .join(Product, Product.product_id == CartItem.product_id)
            .join(Merchant, Merchant.merchant_id == Product.merchant_id)
            .join(ProductSKU, ProductSKU.sku_id == CartItem.sku_id, isouter=True)
            .where(CartItem.account_id == account_id)
            .order_by(CartItem.created_at, CartItem.cart_item_id)
        )
        return list((await self.session.execute(stmt)).all())

    async def get_cart_rows(self, account_id: str):
        return await self._cart_rows(account_id)

    async def add_cart_item(self, account_id: str, product_id: str, sku_id: str, quantity: int) -> bool:
        product = await self.session.get(Product, product_id)
        if product is None:
            return False
        if not sku_id:
            sku_id = str((await self.session.scalar(select(ProductSKU.sku_id).where(ProductSKU.product_id == product_id).order_by(ProductSKU.sku_id).limit(1))) or "")
        existing = await self.session.scalar(select(CartItem).where(CartItem.account_id == account_id, CartItem.product_id == product_id, CartItem.sku_id == sku_id))
        quantity = max(1, quantity)
        if existing is None:
            self.session.add(CartItem(cart_item_id=self._new_id("cart"), account_id=account_id, product_id=product_id, sku_id=sku_id, quantity=quantity, selected=True))
        else:
            existing.quantity += quantity
            existing.selected = True
            existing.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True

    async def checkout(self, account_id: str) -> list[tuple[Order, list[OrderItem], str]]:
        await self.session.rollback()
        try:
            async with self.session.begin():
                rows = await self._cart_rows(account_id)
                selected = [row for row in rows if row[0].selected]
                if not selected:
                    return []
                grouped: dict[str, list[tuple[CartItem, Product, Merchant, ProductSKU | None]]] = {}
                for cart_item, product, merchant, sku in selected:
                    if product.stock_quantity < cart_item.quantity:
                        raise ValueError("库存不足")
                    if sku is not None and sku.stock_quantity < cart_item.quantity:
                        raise ValueError("库存不足")
                    grouped.setdefault(product.merchant_id, []).append((cart_item, product, merchant, sku))
                created: list[tuple[Order, list[OrderItem], str]] = []
                for merchant_id, merchant_rows in grouped.items():
                    total = sum((Decimal(str(sku.price if sku is not None else product.price)) * quantity.quantity for quantity, product, _merchant, sku in merchant_rows), Decimal("0.00"))
                    now = datetime.now(timezone.utc)
                    order = Order(
                        order_id=self._new_id("ord"), order_no=f"NO{now.strftime('%Y%m%d%H%M%S')}{secrets.token_hex(3)}",
                        account_id=account_id, merchant_id=merchant_id, status="pending_payment",
                        total_amount=total, discount_amount=Decimal("0.00"), pay_amount=total,
                        payment_deadline_at=now + timedelta(minutes=30), created_at=now, updated_at=now,
                    )
                    self.session.add(order)
                    items: list[OrderItem] = []
                    for cart_item, product, merchant, sku in merchant_rows:
                        updated_product = await self.session.execute(
                            update(Product)
                            .where(Product.product_id == product.product_id, Product.stock_quantity >= cart_item.quantity)
                            .values(
                                stock_quantity=Product.stock_quantity - cart_item.quantity,
                                stock_status=case((Product.stock_quantity - cart_item.quantity <= 0, "out_of_stock"), else_=Product.stock_status),
                                updated_at=datetime.now(timezone.utc),
                            )
                        )
                        if updated_product.rowcount != 1:
                            raise ValueError("库存不足")
                        if sku is not None:
                            updated_sku = await self.session.execute(
                                update(ProductSKU)
                                .where(ProductSKU.sku_id == sku.sku_id, ProductSKU.stock_quantity >= cart_item.quantity)
                                .values(
                                    stock_quantity=ProductSKU.stock_quantity - cart_item.quantity,
                                    stock_status=case((ProductSKU.stock_quantity - cart_item.quantity <= 0, "out_of_stock"), else_=ProductSKU.stock_status),
                                    updated_at=datetime.now(timezone.utc),
                                )
                            )
                            if updated_sku.rowcount != 1:
                                raise ValueError("库存不足")
                        item = OrderItem(
                            order_item_id=self._new_id("oi"), order_id=order.order_id, product_id=product.product_id,
                            sku_id=cart_item.sku_id, name=product.name, image_url=product.image_url,
                            price=sku.price if sku is not None else product.price, quantity=cart_item.quantity, merchant_id=merchant.merchant_id, merchant_name=merchant.name,
                        )
                        items.append(item)
                        self.session.add(item)
                        self.session.add(cart_item)
                        await self.session.delete(cart_item)
                    self.session.add(Payment(
                        payment_id=self._new_id("pay"), order_id=order.order_id, account_id=account_id,
                        amount=total, status="pending", method="mock_balance", expires_at=order.payment_deadline_at,
                        created_at=now, updated_at=now,
                    ))
                    created.append((order, items, merchant_rows[0][2].name))
                return created
        except ValueError:
            await self.session.rollback()
            raise

    async def update_cart_item(self, account_id: str, cart_item_id: str, quantity: int | None = None, selected: bool | None = None) -> bool:
        item = await self.session.scalar(select(CartItem).where(CartItem.account_id == account_id, CartItem.cart_item_id == cart_item_id))
        if item is None:
            return False
        if quantity is not None and quantity > 0:
            item.quantity = quantity
        if selected is not None:
            item.selected = selected
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True

    async def delete_cart_item(self, account_id: str, cart_item_id: str) -> bool:
        item = await self.session.scalar(select(CartItem).where(CartItem.account_id == account_id, CartItem.cart_item_id == cart_item_id))
        if item is None:
            return False
        await self.session.delete(item)
        await self.session.commit()
        return True

    @staticmethod
    def _discount_amount(base: Decimal, kind: str, threshold: Decimal, amount: Decimal, rate: Decimal = Decimal("0")) -> Decimal:
        if base < threshold:
            return Decimal("0.00")
        if kind in {"percentage", "percent", "rate"}:
            if rate <= 0 or rate >= 1:
                return Decimal("0.00")
            return min(base, (base * rate).quantize(Decimal("0.01")))
        return min(base, max(Decimal("0.00"), amount))

    async def preview_cart_discount(self, account_id: str) -> dict[str, object]:
        rows = await self._cart_rows(account_id)
        total = Decimal("0.00")
        merchant_totals: dict[str, Decimal] = {}
        for cart_item, product, merchant, sku in rows:
            if not cart_item.selected:
                continue
            price = Decimal(str(sku.price if sku and sku.price is not None else product.price))
            line = price * cart_item.quantity
            total += line
            merchant_totals[merchant.merchant_id] = merchant_totals.get(merchant.merchant_id, Decimal("0.00")) + line
        now = datetime.now(timezone.utc)
        lines: list[dict[str, str]] = []
        discount = Decimal("0.00")
        promotions = list((await self.session.execute(select(PromotionRule).where(PromotionRule.status == "active", PromotionRule.start_at <= now, PromotionRule.end_at >= now).order_by(PromotionRule.created_at.desc()))).scalars().all())
        for promotion in promotions:
            base = merchant_totals.get(promotion.merchant_id, Decimal("0.00")) if promotion.scope == "merchant" else total
            value = self._discount_amount(base, promotion.type, Decimal(str(promotion.threshold_amount)), Decimal(str(promotion.discount_amount)), Decimal(str(promotion.discount_rate)))
            if value > 0:
                discount += value
                lines.append({"type": "promotion", "id": promotion.promotion_id, "name": promotion.name, "amount": f"{value:.2f}"})
        user_coupons = list((await self.session.execute(select(UserCoupon, Coupon).join(Coupon, Coupon.coupon_id == UserCoupon.coupon_id).where(UserCoupon.account_id == account_id, UserCoupon.status == "unused"))).all())
        for user_coupon, coupon in user_coupons:
            if coupon.status != "active" or (self._aware(coupon.start_at) and self._aware(coupon.start_at) > now) or (self._aware(coupon.end_at) and self._aware(coupon.end_at) < now):
                continue
            base = merchant_totals.get(coupon.merchant_id, Decimal("0.00")) if coupon.scope == "merchant" else total
            value = self._discount_amount(base, coupon.type, Decimal(str(coupon.threshold_amount)), Decimal(str(coupon.discount_amount)))
            if value > 0:
                discount += value
                lines.append({"type": "coupon", "id": user_coupon.user_coupon_id, "name": coupon.name, "amount": f"{value:.2f}"})
        discount = min(total, discount)
        return {"total_amount": f"{total:.2f}", "discount_amount": f"{discount:.2f}", "pay_amount": f"{(total - discount):.2f}", "lines": lines}

    async def list_orders(self, *, account_id: str = "", merchant_id: str = "", page: int = 1, page_size: int = 10) -> tuple[list[tuple[Order, Merchant, list[OrderItem]]], int]:
        filters = []
        if account_id:
            filters.append(Order.account_id == account_id)
        if merchant_id:
            filters.append(Order.merchant_id == merchant_id)
        total = int((await self.session.execute(select(func.count(Order.order_id)).where(*filters))).scalar_one() or 0)
        rows = list((await self.session.execute(select(Order, Merchant).join(Merchant, Merchant.merchant_id == Order.merchant_id).where(*filters).order_by(Order.created_at.desc(), Order.order_id.desc()).offset((page - 1) * page_size).limit(page_size))).all())
        result: list[tuple[Order, Merchant, list[OrderItem]]] = []
        for order, merchant in rows:
            items = list((await self.session.execute(select(OrderItem).where(OrderItem.order_id == order.order_id).order_by(OrderItem.order_item_id))).scalars().all())
            result.append((order, merchant, items))
        return result, total

    async def get_order_detail(self, account_id: str, order_id: str, *, is_admin: bool = False) -> tuple[Order, Merchant, list[OrderItem], Payment | None] | None:
        filters = [Order.order_id == order_id]
        if not is_admin:
            filters.append(Order.account_id == account_id)
        row = (await self.session.execute(select(Order, Merchant).join(Merchant, Merchant.merchant_id == Order.merchant_id).where(*filters))).first()
        if row is None:
            return None
        order, merchant = row
        items = list((await self.session.execute(select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.order_item_id))).scalars().all())
        payment = await self.session.scalar(select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at.desc()))
        return order, merchant, items, payment

    async def pay_order(self, account_id: str, order_id: str, method: str = "mock_balance") -> tuple[Order, Payment] | None:
        detail = await self.get_order_detail(account_id, order_id)
        if detail is None:
            return None
        order, _merchant, _items, payment = detail
        now = datetime.now(timezone.utc)
        deadline = self._aware(order.payment_deadline_at)
        if order.status != "pending_payment" or (deadline and now > deadline) or payment is None or payment.status != "pending":
            return None
        order.status = "pending_ship"
        order.paid_at = now
        order.updated_at = now
        payment.status = "success"
        payment.method = method.strip() or "mock_balance"
        payment.transaction_no = self._new_id("txn")
        payment.paid_at = now
        payment.updated_at = now
        await self.session.commit()
        return order, payment

    async def cancel_order(self, account_id: str, order_id: str, reason: str = "") -> Order | None:
        detail = await self.get_order_detail(account_id, order_id)
        if detail is None:
            return None
        order, _merchant, _items, payment = detail
        if order.status != "pending_payment":
            return None
        now = datetime.now(timezone.utc)
        order.status = "canceled"
        order.closed_at = now
        order.cancel_reason = reason.strip()[:256] or "用户取消"
        order.updated_at = now
        if payment and payment.status == "pending":
            payment.status = "failed"
            payment.updated_at = now
        await self.session.commit()
        return order

    async def confirm_receipt(self, account_id: str, order_id: str) -> Order | None:
        detail = await self.get_order_detail(account_id, order_id)
        if detail is None:
            return None
        order, _merchant, _items, _payment = detail
        if order.status != "shipped":
            return None
        now = datetime.now(timezone.utc)
        order.status = "completed"
        order.completed_at = now
        order.updated_at = now
        await self.session.commit()
        return order

    async def update_order_status(self, order_id: str, status: str, merchant_id: str = "") -> tuple[Order, Merchant, list[OrderItem]] | None:
        detail = await self.get_order_detail("", order_id, is_admin=True)
        if detail is None:
            return None
        order, merchant, items, _payment = detail
        if merchant_id and order.merchant_id != merchant_id:
            return None
        if order.status not in {"pending_ship", "shipped"} and status not in {"canceled", "closed_timeout"}:
            return None
        if status not in {"pending_ship", "shipped", "completed", "canceled", "closed_timeout"}:
            return None
        order.status = status
        now = datetime.now(timezone.utc)
        order.updated_at = now
        if status == "completed":
            order.completed_at = now
        if status in {"canceled", "closed_timeout"}:
            order.closed_at = now
        await self.session.commit()
        return order, merchant, items

    async def expire_pending_orders(self) -> int:
        now = datetime.now(timezone.utc)
        rows = list((await self.session.execute(select(Order).where(Order.status == "pending_payment", Order.payment_deadline_at.is_not(None), Order.payment_deadline_at < now))).scalars().all())
        for order in rows:
            order.status = "closed_timeout"
            order.closed_at = now
            order.cancel_reason = "支付超时自动关闭"
            order.updated_at = now
            payments = list((await self.session.execute(select(Payment).where(Payment.order_id == order.order_id, Payment.status == "pending"))).scalars().all())
            for payment in payments:
                payment.status = "expired"
                payment.updated_at = now
        if rows:
            await self.session.commit()
        return len(rows)

    async def list_promotions(self, merchant_id: str = "", page: int = 1, page_size: int = 10) -> tuple[list[PromotionRule], int]:
        filters = [PromotionRule.merchant_id == merchant_id] if merchant_id else []
        total = int((await self.session.execute(select(func.count(PromotionRule.promotion_id)).where(*filters))).scalar_one() or 0)
        stmt = select(PromotionRule).where(*filters).order_by(PromotionRule.created_at.desc(), PromotionRule.promotion_id.desc()).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def create_promotion(self, item: PromotionRule) -> PromotionRule:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def update_promotion_status(self, promotion_id: str, status: str, merchant_id: str = "") -> PromotionRule | None:
        stmt = select(PromotionRule).where(PromotionRule.promotion_id == promotion_id)
        if merchant_id:
            stmt = stmt.where(PromotionRule.merchant_id == merchant_id)
        item = await self.session.scalar(stmt)
        if item is None:
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_available_coupons(self, page: int = 1, page_size: int = 10) -> tuple[list[Coupon], int]:
        now = datetime.now(timezone.utc)
        filters = [Coupon.status == "active", Coupon.start_at <= now, Coupon.end_at >= now, or_(Coupon.total_count == 0, Coupon.claimed_count < Coupon.total_count)]
        total = int((await self.session.execute(select(func.count(Coupon.coupon_id)).where(*filters))).scalar_one() or 0)
        stmt = select(Coupon).where(*filters).order_by(Coupon.created_at.desc(), Coupon.coupon_id.desc()).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def list_user_coupons(self, account_id: str, page: int = 1, page_size: int = 10) -> tuple[list[tuple[UserCoupon, Coupon]], int]:
        filters = [UserCoupon.account_id == account_id]
        total = int((await self.session.execute(select(func.count(UserCoupon.user_coupon_id)).where(*filters))).scalar_one() or 0)
        stmt = select(UserCoupon, Coupon).join(Coupon, Coupon.coupon_id == UserCoupon.coupon_id).where(*filters).order_by(UserCoupon.claimed_at.desc(), UserCoupon.user_coupon_id.desc()).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).all()), total

    async def claim_coupon(self, account_id: str, coupon_id: str) -> tuple[UserCoupon, Coupon] | None:
        now = datetime.now(timezone.utc)
        await self.session.rollback()
        try:
            async with self.session.begin():
                coupon = await self.session.scalar(select(Coupon).where(Coupon.coupon_id == coupon_id).with_for_update())
                if coupon is None or coupon.status != "active" or (coupon and self._aware(coupon.start_at) and self._aware(coupon.start_at) > now) or (coupon and self._aware(coupon.end_at) and self._aware(coupon.end_at) < now):
                    return None
                if coupon.total_count > 0 and coupon.claimed_count >= coupon.total_count:
                    return None
                owned = int((await self.session.execute(select(func.count(UserCoupon.user_coupon_id)).where(UserCoupon.account_id == account_id, UserCoupon.coupon_id == coupon_id))).scalar_one() or 0)
                if owned >= max(1, coupon.per_user_limit):
                    return None
                item = UserCoupon(user_coupon_id=self._new_id("uc"), coupon_id=coupon_id, account_id=account_id, status="unused", claimed_at=now)
                coupon.claimed_count += 1
                self.session.add(item)
                await self.session.flush()
                return item, coupon
        except IntegrityError:
            await self.session.rollback()
            return None

    async def create_product_review(self, account_id: str, order_id: str, order_item_id: str, rating: int, content: str, tags: list[str]) -> ProductReview | None:
        if rating < 1 or rating > 5 or not content.strip():
            return None
        row = (await self.session.execute(select(OrderItem, Order).join(Order, Order.order_id == OrderItem.order_id).where(OrderItem.order_item_id == order_item_id, OrderItem.order_id == order_id, Order.account_id == account_id))).first()
        if row is None or row[1].status != "completed":
            return None
        item, _order = row
        review = ProductReview(review_id=self._new_id("rev"), order_id=order_id, order_item_id=order_item_id, product_id=item.product_id, sku_id=item.sku_id, account_id=account_id, rating=rating, content=content.strip(), tags_json=[str(tag).strip() for tag in tags if str(tag).strip()][:20], status="visible")
        self.session.add(review)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            return None
        await self.session.refresh(review)
        return review

    async def list_product_reviews(self, product_id: str, page: int = 1, page_size: int = 10, *, merchant_id: str = "", all_status: bool = False) -> tuple[list[ProductReview], int]:
        filters = [ProductReview.product_id == product_id] if product_id else []
        if merchant_id:
            filters.append(Product.merchant_id == merchant_id)
        if not all_status:
            filters.append(ProductReview.status == "visible")
        stmt_base = select(ProductReview).join(Product, Product.product_id == ProductReview.product_id, isouter=bool(merchant_id)).where(*filters)
        total = len(list((await self.session.execute(stmt_base)).scalars().all()))
        stmt = stmt_base.order_by(ProductReview.created_at.desc(), ProductReview.review_id.desc()).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def reply_review(self, merchant_id: str, review_id: str, reply: str) -> ProductReview | None:
        if not reply.strip():
            return None
        row = (await self.session.execute(select(ProductReview, Product).join(Product, Product.product_id == ProductReview.product_id).where(ProductReview.review_id == review_id, Product.merchant_id == merchant_id))).first()
        if row is None:
            return None
        review = row[0]
        review.merchant_reply = reply.strip()[:1000]
        review.merchant_replied_at = datetime.now(timezone.utc)
        review.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(review)
        return review

    async def update_review_status(self, review_id: str, status: str) -> ProductReview | None:
        item = await self.session.get(ProductReview, review_id)
        if item is None:
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_accounts(self, page: int = 1, page_size: int = 10) -> tuple[list[Account], int]:
        total = int((await self.session.execute(select(func.count(Account.account_id)))).scalar_one() or 0)
        stmt = select(Account).order_by(Account.created_at, Account.account_id).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def update_account_status(self, account_id: str, status: str) -> Account | None:
        item = await self.session.get(Account, account_id)
        if item is None:
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_admin_products(self, page: int = 1, page_size: int = 10) -> tuple[list[tuple[Product, Merchant, ProductSKU | None]], int]:
        total = int((await self.session.execute(select(func.count(Product.product_id)))).scalar_one() or 0)
        stmt = self._product_record_query().order_by(Product.created_at.desc(), Product.product_id).offset((page - 1) * page_size).limit(page_size)
        return [(product, merchant, sku) for product, merchant, sku in (await self.session.execute(stmt)).all()], total

    async def create_product(self, product: Product) -> Product:
        self.session.add(product)
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def update_product(self, product_id: str, merchant_id: str, values: dict[str, object]) -> tuple[Product, Merchant, ProductSKU | None] | None:
        product = await self.session.scalar(select(Product).where(Product.product_id == product_id, Product.merchant_id == merchant_id))
        if product is None:
            return None
        for key, value in values.items():
            if hasattr(product, key) and value is not None and key not in {"product_id", "merchant_id"}:
                setattr(product, key, value)
        product.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return await self.get_product_record(product_id)

    async def update_product_status(self, product_id: str, status: str, merchant_id: str = "") -> Product | None:
        stmt = select(Product).where(Product.product_id == product_id)
        if merchant_id:
            stmt = stmt.where(Product.merchant_id == merchant_id)
        item = await self.session.scalar(stmt)
        if item is None:
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_merchants_admin(self, page: int = 1, page_size: int = 10) -> tuple[list[Merchant], int]:
        total = int((await self.session.execute(select(func.count(Merchant.merchant_id)))).scalar_one() or 0)
        stmt = select(Merchant).order_by(Merchant.created_at, Merchant.merchant_id).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def update_merchant_status(self, merchant_id: str, status: str) -> Merchant | None:
        item = await self.session.get(Merchant, merchant_id)
        if item is None:
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_configs(self, page: int = 1, page_size: int = 10) -> tuple[list[AppConfig], int]:
        filters = [~AppConfig.config_key.like("agent.prompt.%")]
        total = int((await self.session.execute(select(func.count(AppConfig.config_key)).where(*filters))).scalar_one() or 0)
        stmt = select(AppConfig).where(*filters).order_by(AppConfig.config_key).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def upsert_config(self, key: str, value: str, value_type: str, description: str, is_secret: bool) -> AppConfig:
        item = await self.session.get(AppConfig, key)
        now = datetime.now(timezone.utc)
        if item is None:
            item = AppConfig(config_key=key, config_value=value, value_type=value_type or "string", description=description, domain=key.split(".", 1)[0], is_secret=is_secret, updated_at=now)
            self.session.add(item)
        else:
            item.config_value = value
            item.value_type = value_type or item.value_type
            item.description = description
            item.is_secret = is_secret
            item.updated_at = now
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_prompts(self, page: int = 1, page_size: int = 10) -> tuple[list[AgentPrompt], int]:
        latest = select(AgentPrompt.prompt_key, func.max(AgentPrompt.version).label("version")).group_by(AgentPrompt.prompt_key).subquery()
        stmt_base = select(AgentPrompt).join(latest, and_(AgentPrompt.prompt_key == latest.c.prompt_key, AgentPrompt.version == latest.c.version))
        total = len(list((await self.session.execute(stmt_base)).scalars().all()))
        stmt = stmt_base.order_by(AgentPrompt.prompt_key).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def save_prompt_draft(self, prompt_key: str, title: str, content: str, description: str, created_by: str) -> AgentPrompt:
        latest = await self.session.scalar(select(func.max(AgentPrompt.version)).where(AgentPrompt.prompt_key == prompt_key))
        item = AgentPrompt(prompt_id=self._new_id("prm"), prompt_key=prompt_key.strip(), title=title.strip() or prompt_key.strip(), content=content.strip(), status="draft", version=int(latest or 0) + 1, description=description.strip(), created_by=created_by, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def publish_prompt(self, prompt_key: str, published_by: str, target: str = "database") -> tuple[AgentPrompt, AgentPromptPublishRecord] | None:
        await self.session.rollback()
        async with self.session.begin():
            prompt = await self.session.scalar(select(AgentPrompt).where(AgentPrompt.prompt_key == prompt_key).order_by(AgentPrompt.version.desc()).limit(1))
            if prompt is None:
                return None
            now = datetime.now(timezone.utc)
            await self.session.execute(update(AgentPrompt).where(AgentPrompt.prompt_key == prompt_key, AgentPrompt.status == "active").values(status="archived", updated_at=now))
            prompt.status = "active"
            prompt.published_at = now
            prompt.updated_at = now
            record = AgentPromptPublishRecord(record_id=self._new_id("prmpub"), prompt_key=prompt_key, prompt_id=prompt.prompt_id, version=prompt.version, published_by=published_by, publish_target=target or "database", created_at=now)
            self.session.add(record)
            await self.session.flush()
        await self.session.refresh(prompt)
        await self.session.refresh(record)
        return prompt, record

    async def list_prompt_publish_records(self, prompt_key: str = "", limit: int = 20) -> list[AgentPromptPublishRecord]:
        stmt = select(AgentPromptPublishRecord)
        if prompt_key:
            stmt = stmt.where(AgentPromptPublishRecord.prompt_key == prompt_key)
        stmt = stmt.order_by(AgentPromptPublishRecord.created_at.desc(), AgentPromptPublishRecord.record_id.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_admin_runs(self, page: int = 1, page_size: int = 10) -> tuple[list[AgentRun], int]:
        total = int((await self.session.execute(select(func.count(AgentRun.run_id)))).scalar_one() or 0)
        stmt = select(AgentRun).order_by(AgentRun.created_at.desc(), AgentRun.run_id.desc()).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def list_admin_trace(self, run_id: str) -> list[AgentTraceEvent]:
        stmt = select(AgentTraceEvent).where(AgentTraceEvent.run_id == run_id).order_by(AgentTraceEvent.created_at, AgentTraceEvent.trace_event_id)
        return list((await self.session.execute(stmt)).scalars().all())


