from __future__ import annotations

#   安全模块：负责密码摘要、token 和认证输入校验。

import base64
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt

from app.core.errors import APIError


#     hash_password：完成本模块的一步处理，并把结果返回给调用方。
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


#     verify_password：完成本模块的一步处理，并把结果返回给调用方。
def verify_password(stored_hash: str, password: str) -> bool:
    stored_hash = stored_hash.strip()
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except ValueError:
            return False
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored_hash


#     should_upgrade_password_hash：完成本模块的一步处理，并把结果返回给调用方。
def should_upgrade_password_hash(stored_hash: str) -> bool:
    return not stored_hash.strip().startswith("$2")


#     new_token：完成本模块的一步处理，并把结果返回给调用方。
def new_token() -> str:
    return "tok_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


#     token_digest：完成本模块的一步处理，并把结果返回给调用方。
def token_digest(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


#     token_expiry：完成本模块的一步处理，并把结果返回给调用方。
def token_expiry(hours: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


#     bearer_token：完成本模块的一步处理，并把结果返回给调用方。
def bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


#  校验 validate_register_input：完成本模块的一步处理，并把结果返回给调用方。
def validate_register_input(username: str, password: str, display_name: str) -> None:
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
