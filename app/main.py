from __future__ import annotations

# 本模块说明：Python 后端模块：实现应用的一项独立能力。

from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from app.api.middleware import install_middlewares
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.db import create_engine, initialize_database
from app.core.errors import APIError
from app.core.logging import configure_logging
from app.integrations.nacos import NacosConfigCenter
from app.core.runtime_sync import RuntimeConfigSynchronizer
from app.services.image_index_jobs import ImageIndexJobManager


def create_app(settings: Settings | None = None) -> FastAPI:
    effective_settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_engine(effective_settings)
        app.state.engine = engine
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        await initialize_database(engine, effective_settings)
        app.state.image_index_jobs = ImageIndexJobManager(app.state.session_factory)
        synchronizer = RuntimeConfigSynchronizer(effective_settings, app.state.session_factory, app.state.nacos)
        app.state.runtime_settings = await synchronizer.refresh()
        app.state.settings = app.state.runtime_settings
        refresh_task = None
        if app.state.nacos.enabled and effective_settings.runtime_config_refresh_seconds > 0:
            async def refresh_loop() -> None:
                while True:
                    await asyncio.sleep(effective_settings.runtime_config_refresh_seconds)
                    try:
                        app.state.runtime_settings = await synchronizer.refresh()
                        app.state.settings = app.state.runtime_settings
                    except (OSError, RuntimeError, ValueError, SQLAlchemyError):
                        logging.getLogger("xzxg.config").warning("Runtime configuration refresh failed", exc_info=True)
            refresh_task = asyncio.create_task(refresh_loop())
        yield
        if refresh_task is not None:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
        limiter = getattr(app.state, "rate_limiter", None)
        if limiter is not None:
            await limiter.close()
        jobs = getattr(app.state, "image_index_jobs", None)
        if jobs is not None:
            await jobs.close()
        await engine.dispose()

    app = FastAPI(title="xzxg-shop Python backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = effective_settings
    app.state.nacos = NacosConfigCenter(
        effective_settings.nacos_addr,
        effective_settings.nacos_namespace,
        effective_settings.nacos_group,
        effective_settings.nacos_data_id,
        effective_settings.nacos_prompt_data_id,
        username=effective_settings.nacos_username,
        password=effective_settings.nacos_password,
    )
    install_middlewares(app, effective_settings)
    app.include_router(api_router)

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, error: APIError) -> JSONResponse:
        response = JSONResponse(status_code=error.status_code, content=error.payload(getattr(request.state, "request_id", "")), headers=error.headers)
        response.headers["X-Request-ID"] = getattr(request.state, "request_id", "")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        del error
        request_id = getattr(request.state, "request_id", "")
        response = JSONResponse(status_code=400, content={"code": "bad_request", "message": "请求 JSON 不合法", "request_id": request_id})
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, _error: Exception) -> JSONResponse:
        logging.getLogger("xzxg.api").exception("unhandled request error")
        request_id = getattr(request.state, "request_id", "")
        response = JSONResponse(status_code=500, content={"code": "internal_error", "message": "服务暂时不可用", "request_id": request_id})
        response.headers["X-Request-ID"] = request_id
        return response

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=False)
