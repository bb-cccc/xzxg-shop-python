from __future__ import annotations

# 数据访问模块：把业务查询封装为异步 Repository 操作。

from app.repositories.sql_support import *  # noqa: F401,F403


# 能力混入类，把这一领域的操作组合到主类中。
class AuthRepositoryMixin:
    # get_account_by_username 
    async def get_account_by_username(self, username: str) -> tuple[Account, str] | None:
        stmt = select(Account).where(Account.username == username, Account.status == 'active')
        account = (await self.session.execute(stmt)).scalar_one_or_none()
        if account is None:
            return None
        return (account, account.password_hash)

    # get_account_by_token 
    async def get_account_by_token(self, token: str, now: datetime) -> Account | None:
        stmt = select(Account).join(AuthToken, AuthToken.account_id == Account.account_id).where(AuthToken.token.in_([token_digest(token), token.strip()]), AuthToken.expires_at > now, Account.status.in_(['active', 'risk']))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # 创建 create_auth_token 
    async def create_auth_token(self, account_id: str, token_digest: str, created_at: datetime, expires_at: datetime) -> None:
        self.session.add(AuthToken(token=token_digest, account_id=account_id, created_at=created_at, expires_at=expires_at))
        await self.session.commit()

    # 删除 delete_auth_token 
    async def delete_auth_token(self, raw_token: str) -> None:
        """Revoke a token accepting both the public token and its stored digest."""
        value = raw_token.strip()
        if not value:
            return
        await self.session.execute(delete(AuthToken).where(AuthToken.token.in_([value, token_digest(value)])))
        await self.session.commit()

    # 创建 create_account 
    async def create_account(self, account: Account) -> Account:
        self.session.add(account)
        await self.session.commit()
        await self.session.refresh(account)
        return account

    # 更新 update_password_hash 
    async def update_password_hash(self, account_id: str, password_hash: str) -> None:
        await self.session.execute(update(Account).where(Account.account_id == account_id).values(password_hash=password_hash, updated_at=datetime.now(timezone.utc)))
        await self.session.commit()

    # 更新 update_account_profile 
    async def update_account_profile(self, account_id: str, display_name: str, avatar_url: str) -> Account | None:
        item = await self.session.get(Account, account_id)
        if item is None:
            return None
        if display_name.strip():
            item.display_name = display_name.strip()[:24]
        if avatar_url.strip():
            item.avatar_url = avatar_url.strip()[:512]
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    # 更新 update_account_contact 
    async def update_account_contact(self, account_id: str, phone: str, email: str) -> Account | None:
        item = await self.session.get(Account, account_id)
        if item is None:
            return None
        item.phone = phone.strip()
        item.email = email.strip()
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    # 删除 delete_account 
    async def delete_account(self, account_id: str) -> bool:
        item = await self.session.get(Account, account_id)
        if item is None:
            return False
        now = datetime.now(timezone.utc)
        item.status = 'deleted'
        item.deleted_at = now
        item.updated_at = now
        await self.session.execute(delete(AuthToken).where(AuthToken.account_id == account_id))
        await self.session.commit()
        return True
