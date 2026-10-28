from __future__ import annotations

# 本模块说明：领域服务模块：编排跨 Repository 的业务事务。

from app.repositories.sql import SQLRepository


# 领域服务，编排多个组件完成一项业务操作。
class CommerceService:
    """Application boundary for user commerce workflows.

    HTTP handlers depend on this service instead of deciding transaction and
    state-transition details themselves. The repository remains the persistence
    adapter and can be replaced without changing route contracts.
    """

    def __init__(self, repository: SQLRepository) -> None:
        self.repository = repository

    async def discount_preview(self, account_id: str) -> dict[str, object]:
        return await self.repository.preview_cart_discount(account_id)

    async def checkout(self, account_id: str):
        return await self.repository.checkout(account_id)

    async def pay(self, account_id: str, order_id: str, method: str):
        return await self.repository.pay_order(account_id, order_id, method)

    async def cancel(self, account_id: str, order_id: str, reason: str):
        return await self.repository.cancel_order(account_id, order_id, reason)

    async def confirm_receipt(self, account_id: str, order_id: str):
        return await self.repository.confirm_receipt(account_id, order_id)
