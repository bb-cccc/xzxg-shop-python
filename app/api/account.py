from __future__ import annotations



from fastapi import APIRouter, Depends

from app.api.auth import account_schema
from app.api.dependencies import get_current_account, get_repository
from app.core.errors import APIError
from app.domain.models import Account
from app.domain.schemas import AccountOut, AccountProfileUpdateRequest, ContactUpdateRequest
from app.repositories.sql import SQLRepository


router = APIRouter(prefix="/account", tags=["account"])


@router.get("/profile", response_model=AccountOut, response_model_exclude_none=True)
async def profile(account: Account = Depends(get_current_account)) -> AccountOut:
    return account_schema(account)


@router.patch("/profile", response_model=AccountOut, response_model_exclude_none=True)
async def update_profile(
    request: AccountProfileUpdateRequest,
    account: Account = Depends(get_current_account),
    repository: SQLRepository = Depends(get_repository),
) -> AccountOut:
    display_name = (request.display_name or "").strip() or (request.nickname or "").strip()
    avatar_url = (request.avatar_url or "").strip()
    if not display_name and not avatar_url:
        raise APIError(400, "empty_profile", "昵称或头像不能为空")
    if len(display_name) > 24:
        raise APIError(400, "bad_display_name", "昵称最多 24 个字符")
    updated = await repository.update_account_profile(account.account_id, display_name, avatar_url)
    if updated is None:
        raise APIError(404, "account_not_found", "账号不存在")
    return account_schema(updated)


@router.patch("/contact", response_model=AccountOut, response_model_exclude_none=True)
async def update_contact(
    request: ContactUpdateRequest,
    account: Account = Depends(get_current_account),
    repository: SQLRepository = Depends(get_repository),
) -> AccountOut:
    phone = (request.phone or "").strip()
    email = (request.email or "").strip()
    if len(phone) > 32 or len(email) > 128:
        raise APIError(400, "bad_contact", "手机号或邮箱过长")
    if email and ("@" not in email or " " in email):
        raise APIError(400, "bad_email", "邮箱格式不正确")
    updated = await repository.update_account_contact(account.account_id, phone, email)
    if updated is None:
        raise APIError(404, "account_not_found", "账号不存在")
    return account_schema(updated)


@router.delete("")
async def delete_account(
    account: Account = Depends(get_current_account),
    repository: SQLRepository = Depends(get_repository),
) -> dict[str, bool]:
    if not await repository.delete_account(account.account_id):
        raise APIError(500, "delete_account_failed", "删除账号失败")
    return {"ok": True}
