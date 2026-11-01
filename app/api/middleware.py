from __future__ import annotations



import secrets
import time
import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from app.core.config import Settings
from app.core.errors import APIError
from app.core.rate_limit import RateLimiter


def request_id() -> str:
    return secrets.token_hex(12)


def install_middlewares(app: FastAPI, settings: Settings) -> None:
    logger = logging.getLogger("xzxg.http")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_origins != ["*"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Authorization", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.request_id = request.headers.get("X-Request-ID") or request_id()
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "http request completed request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
            int((time.perf_counter() - started) * 1000),
        )
        return response

    @app.middleware("http")
    async def body_limit(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                too_large = int(content_length) > settings.body_limit_bytes
            except ValueError:
                too_large = False
            if too_large:
                return JSONResponse(
                    status_code=413,
                    content={"code": "body_too_large", "message": "请求体过大", "request_id": getattr(request.state, "request_id", "")},
                )
        return await call_next(request)

    limiter = RateLimiter(settings, logger)
    app.state.rate_limiter = limiter

    @app.middleware("http")
    async def rate_limit(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method == "OPTIONS" or request.url.path == "/api/v1/health" or request.url.path.startswith("/api/v1/eval/"):
            return await call_next(request)
        key = request.client.host if request.client else "unknown"
        if not await limiter.allow(key):
            return JSONResponse(
                status_code=429,
                content={"code": "rate_limited", "message": "请求过于频繁，请稍后再试", "request_id": getattr(request.state, "request_id", "")},
            )
        return await call_next(request)
