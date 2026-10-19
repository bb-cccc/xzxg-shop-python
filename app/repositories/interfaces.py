"""仓储抽象接口：隔离业务服务与具体数据库实现。"""

from __future__ import annotations

# Repository 抽象接口：描述业务需要的数据操作，不绑定具体数据库。

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Account, Category, Merchant, Product, ProductSKU


class Repository(Protocol):
    """业务层依赖的持久化能力集合，可由 SQL 或测试实现满足。"""
    session: AsyncSession

    async def get_account_by_username(self, username: str) -> tuple[Account, str] | None: ...

    async def get_account_by_token(self, token: str, now: datetime) -> Account | None: ...

    async def create_auth_token(self, account_id: str, token_digest: str, created_at: datetime, expires_at: datetime) -> None: ...

    async def create_account(self, account: Account) -> Account: ...

    async def update_password_hash(self, account_id: str, password_hash: str) -> None: ...

    async def list_product_records(self, keyword: str, category_id: str, page: int, page_size: int) -> tuple[list[tuple[Product, object, ProductSKU | None]], int]: ...

    async def get_product_record(self, product_id: str) -> tuple[Product, object, ProductSKU | None] | None: ...

    async def list_product_skus(self, product_id: str) -> Sequence[ProductSKU]: ...

    async def list_categories(self) -> Sequence[Category]: ...

    async def list_merchants(self, page: int, page_size: int) -> tuple[list[Merchant], int]: ...

