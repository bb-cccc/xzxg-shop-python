from __future__ import annotations

from typing import Any


class APIError(Exception):
    """可预期的接口错误，统一携带 HTTP 状态码、业务错误码和响应消息。"""

    def __init__(self, status_code: int, code: str, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}

    def payload(self, request_id: str = "") -> dict[str, Any]:
        # 将内部异常对象转换成稳定的 JSON 结构，避免把堆栈信息暴露给客户端。
        return {"code": self.code, "message": self.message, "request_id": request_id}
