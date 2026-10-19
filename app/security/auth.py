from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt

from app.core.errors import APIError


def hash_password(password: str) -> str:
    # bcrypt 会自动生成随机盐并把盐参数编码进结果，数据库只保存这个结果即可。
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(stored_hash: str, password: str) -> bool:
    """校验新 bcrypt 密码，也兼容历史 SHA-256 密码摘要。"""
    stored_hash = stored_hash.strip()
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            # bcrypt.checkpw 会从 stored_hash 中读取盐和成本参数进行比对。
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except ValueError:
            return False
    # 旧系统只保存 SHA-256 摘要；这里只负责兼容登录，后续应升级为 bcrypt。
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored_hash


def should_upgrade_password_hash(stored_hash: str) -> bool:
    # 非 bcrypt 格式说明仍是旧摘要，登录成功后可重新 hash 并覆盖保存。
    return not stored_hash.strip().startswith("$2")


def new_token() -> str:
    # secrets 使用操作系统安全随机源；token 本身返回给客户端，只保存其摘要。
    return "tok_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def token_digest(token: str) -> str:
    # 数据库保存摘要而不是明文 token，即使数据库泄露也不能直接冒充用户。
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def token_expiry(hours: int) -> datetime:
    # 使用带 UTC 时区的时间，避免服务器部署在不同时区造成过期判断错误。
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def bearer_token(authorization: str | None) -> str:
    """从 Authorization: Bearer <token> 请求头中提取 token；格式不对则返回空串。"""
    if not authorization:
        return ""
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


def validate_register_input(username: str, password: str, display_name: str) -> None:
    """集中校验注册参数；失败时抛出统一 APIError，供接口层转换为 JSON 响应。"""
    username = username.strip()
    password = password.strip()
    display_name = display_name.strip()
    if not username or not password:
        raise APIError(400, "invalid_register_input", "账号和密码不能为空")
    if not 3 <= len(username) <= 32:
        raise APIError(400, "invalid_register_input", "账号长度需要在 3 到 32 个字符之间")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        raise APIError(400, "invalid_register_input", "账号只能包含字母、数字、下划线和短横线")
    if not 8 <= len(password) <= 64:
        raise APIError(400, "invalid_register_input", "密码长度需要在 8 到 64 个字符之间")
    if len(display_name) > 32:
        raise APIError(400, "invalid_register_input", "昵称不能超过 32 个字符")
