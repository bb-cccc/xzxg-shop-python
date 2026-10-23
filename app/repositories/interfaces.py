from __future__ import annotations

# 数据访问模块：把业务查询封装为异步 Repository 操作。

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Account, Category, Merchant, Product, ProductSKU


# 数据访问抽象，隔离业务逻辑与具体数据库实现。
class Repository(Protocol):
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
