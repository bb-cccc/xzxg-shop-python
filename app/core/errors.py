from __future__ import annotations

#核心基础设施模块：集中管理配置、日志、限流和运行时状态。

from typing import Any


#自定义异常类型，用于向上层表达可预期的失败。
class APIError(Exception):
    """An expected API error with the same shape as the Go service."""

    def __init__(self, status_code: int, code: str, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}

    def payload(self, request_id: str = "") -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "request_id": request_id}
