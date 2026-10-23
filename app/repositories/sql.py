from __future__ import annotations

# 数据访问模块：把业务查询封装为异步 Repository 操作。

import secrets
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.sql_admin import AdminRepositoryMixin
from app.repositories.sql_agent import AgentRepositoryMixin
from app.repositories.sql_auth import AuthRepositoryMixin
from app.repositories.sql_catalog import CatalogRepositoryMixin
from app.repositories.sql_commerce import CommerceRepositoryMixin
from app.repositories.sql_rag import RagRepositoryMixin


# 数据访问抽象，隔离业务逻辑与具体数据库实现。
class SQLRepository(
    AuthRepositoryMixin,
    CatalogRepositoryMixin,
    AgentRepositoryMixin,
    RagRepositoryMixin,
    CommerceRepositoryMixin,
    AdminRepositoryMixin,
):
    """SQL persistence facade composed from bounded repository contexts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _prepare_write(self) -> None:
        """End a request's read transaction without expiring loaded entities.

        Authentication and endpoint dependencies share one ``AsyncSession``.
        A rollback here would expire the authenticated account and a later
        attribute access could attempt async lazy IO from synchronous code.
        Repository commands own the write transaction, so committing the
        preceding read-only transaction is the correct boundary.
        """
        if self.session.in_transaction():
            await self.session.commit()

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(10)}"

    @staticmethod
    def _discount_amount(base: Decimal, kind: str, threshold: Decimal, amount: Decimal, rate: Decimal = Decimal("0")) -> Decimal:
        if base < threshold:
            return Decimal("0.00")
        if kind in {"percentage", "percent", "rate"}:
            if rate <= 0 or rate >= 1:
                return Decimal("0.00")
            return min(base, (base * rate).quantize(Decimal("0.01")))
        return min(base, max(Decimal("0.00"), amount))
