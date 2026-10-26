from __future__ import annotations



import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import get_app_settings, get_current_account, get_repository
from app.core.errors import APIError
from app.core.config import Settings
from app.domain.models import Account
from app.domain.schemas import AccountOut, AuthResponse, LoginRequest, RegisterRequest
from app.repositories.sql import SQLRepository
from app.security.auth import (
    hash_password,
    new_token,
    should_upgrade_password_hash,
    token_digest,
    token_expiry,
    validate_register_input,
    verify_password,
    bearer_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def account_schema(account: Account) -> AccountOut:
    return AccountOut(
        account_id=account.account_id,
        username=account.username,
        display_name=account.display_name,
        avatar_url=account.avatar_url or None,
        phone=account.phone or None,
        email=account.email or None,
        role=account.role,
        merchant_id=account.merchant_id or None,
        status=account.status or None,
        created_at=account.created_at,
    )


async def issue_token(account: Account, repository: SQLRepository, settings: Settings) -> str:
    token = new_token()
    now = datetime.now(timezone.utc)
    await repository.create_auth_token(account.account_id, token_digest(token), now, token_expiry(settings.auth_token_ttl_hours))
    return token


@router.post("/login", response_model=AuthResponse, response_model_exclude_none=True)
async def login(request: LoginRequest, repository: SQLRepository = Depends(get_repository), settings: Settings = Depends(get_app_settings)) -> AuthResponse:
    username = request.username.strip()
    if not username or not request.password:
        raise APIError(400, "empty_credential", "账号和密码不能为空")
    found = await repository.get_account_by_username(username)
    if found is None:
        raise APIError(401, "invalid_credential", "账号或密码错误")
    account, stored_hash = found
    if not verify_password(stored_hash, request.password):
        raise APIError(401, "invalid_credential", "账号或密码错误")
    if should_upgrade_password_hash(stored_hash):
        await repository.update_password_hash(account.account_id, hash_password(request.password))
    return AuthResponse(token=await issue_token(account, repository, settings), account=account_schema(account))


@router.post("/register", response_model=AuthResponse, status_code=201, response_model_exclude_none=True)
async def register(request: RegisterRequest, repository: SQLRepository = Depends(get_repository), settings: Settings = Depends(get_app_settings)) -> AuthResponse:
    username = request.username.strip()
    display_name = request.display_name.strip() or username
    validate_register_input(username, request.password, display_name)
    if await repository.get_account_by_username(username) is not None:
        raise APIError(409, "username_exists", "账号已存在")
    account = Account(
        account_id=f"acct_{secrets.token_hex(10)}",
        username=username,
        password_hash=hash_password(request.password),
        display_name=display_name,
        role="user",
        status="active",
    )
    try:
        await repository.create_account(account)
    except IntegrityError as error:
        await repository.session.rollback()
        raise APIError(409, "username_exists", "账号已存在") from error
    return AuthResponse(token=await issue_token(account, repository, settings), account=account_schema(account))


@router.get("/me", response_model=AccountOut, response_model_exclude_none=True)
async def me(account: Account = Depends(get_current_account)) -> AccountOut:
    return account_schema(account)


@router.post("/logout")
async def logout(
    authorization: str | None = Header(default=None),
    _account: Account = Depends(get_current_account),
    repository: SQLRepository = Depends(get_repository),
) -> dict[str, bool]:
    del _account
    token = bearer_token(authorization)
    if token:
        await repository.delete_auth_token(token)
    return {"ok": True}
