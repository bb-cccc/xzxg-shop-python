from __future__ import annotations



from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.config import Settings
from app.domain.models import Account
from app.repositories.sql import SQLRepository
from app.services.commerce import CommerceService
from app.security.auth import bearer_token


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


async def get_repository(session: AsyncSession = Depends(get_db)) -> SQLRepository:
    return SQLRepository(session)


async def get_commerce_service(repository: SQLRepository = Depends(get_repository)) -> CommerceService:
    return CommerceService(repository)


def get_app_settings(request: Request) -> Settings:
    return getattr(request.app.state, "runtime_settings", request.app.state.settings)


async def get_current_account(
    authorization: str | None = Header(default=None),
    repository: SQLRepository = Depends(get_repository),
) -> Account:
    token = bearer_token(authorization)
    if not token:
        raise APIError(401, "unauthorized", "请先登录")
    account = await repository.get_account_by_token(token, datetime.now(timezone.utc))
    if account is None:
        raise APIError(401, "unauthorized", "请先登录")
    return account


async def get_current_user(account: Account = Depends(get_current_account)) -> Account:
    if account.role != "user":
        raise APIError(403, "forbidden", "当前账号不是用户端账号")
    return account


async def get_current_merchant(account: Account = Depends(get_current_account)) -> Account:
    if account.role != "merchant" or not account.merchant_id:
        raise APIError(403, "forbidden", "当前账号不是商家账号")
    return account


async def get_current_admin(account: Account = Depends(get_current_account)) -> Account:
    if account.role != "admin":
        raise APIError(403, "forbidden", "当前账号不是管理员账号")
    return account
