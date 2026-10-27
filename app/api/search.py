from __future__ import annotations



import hashlib
import mimetypes
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import FileResponse, Response

from app.api.dependencies import get_current_account, get_app_settings
from app.core.config import Settings
from app.core.errors import APIError
from app.domain.models import Account, StoredFile
from app.domain.schemas import ImageSearchRequest, StoredFileOut
from app.integrations.image_embedding import ImageEmbeddingError
from app.integrations.image_search import ImageSearchService
from app.integrations.objectstore import ObjectStoreError, build_object_store
from app.repositories.sql import SQLRepository
from app.api.dependencies import get_repository


router = APIRouter()


def _file_payload(item: StoredFile) -> dict[str, object]:
    return StoredFileOut.model_validate(item).model_dump(by_alias=True)


def _service(repository: SQLRepository, settings: Settings, account: Account) -> ImageSearchService:
    from app.integrations.image_embedding import build_image_embedder
    from app.rag.service import build_image_vector_provider

    return ImageSearchService(repository, settings, build_object_store(settings), build_image_embedder(settings), account_id=account.account_id, is_admin=account.role == "admin", vector_provider=build_image_vector_provider(settings))


@router.get("/assets/ecommerce_agent_dataset/{path:path}")
async def get_dataset_asset(path: str) -> FileResponse:
    root = (Path(__file__).resolve().parents[3] / "quality" / "data" / "ecommerce_agent_dataset").resolve()
    candidate = (root / path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise APIError(404, "asset_not_found", "静态资源不存在")
    return FileResponse(candidate)


@router.post("/files", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    account: Account = Depends(get_current_account),
    repository: SQLRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    max_bytes = min(max(1, settings.body_limit_bytes), 10 * 1024 * 1024)
    data = await file.read(max_bytes + 1)
    if not data:
        raise APIError(400, "empty_file", "缺少 file 字段")
    if len(data) > max_bytes:
        raise APIError(413, "file_too_large", "文件超过上传大小限制")
    content_type = (file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream").lower()
    if not (content_type.startswith("image/") or content_type == "application/pdf"):
        raise APIError(400, "unsupported_file_type", "当前只支持图片和 PDF 文件")
    file_id = f"file_{secrets.token_hex(10)}"
    now = datetime.now(timezone.utc)
    extension = mimetypes.guess_extension(content_type) or ""
    object_key = f"uploads/{account.account_id}/{now:%Y/%m}/{file_id}{extension}"
    started = time.perf_counter()
    store = build_object_store(settings)
    try:
        await store.put(object_key, data, content_type)
    except ObjectStoreError as error:
        raise APIError(502, "object_store_unavailable", "对象存储不可用") from error
    item = StoredFile(
        file_id=file_id, account_id=account.account_id, object_key=object_key,
        url=f"/api/v1/files/{file_id}", mime_type=content_type, size_bytes=len(data),
        content_hash=hashlib.sha256(data).hexdigest(), storage_provider=store.provider, created_at=now,
    )
    try:
        await repository.create_stored_file(item)
    except SQLAlchemyError as error:
        raise APIError(500, "save_file_failed", "保存文件元数据失败") from error
    return {"file": _file_payload(item), "upload_duration_ms": int((time.perf_counter() - started) * 1000)}


@router.get("/files/{file_id}")
async def get_file(
    file_id: str,
    account: Account = Depends(get_current_account),
    repository: SQLRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    if not file_id or ".." in file_id:
        raise APIError(400, "bad_file_id", "文件 ID 不合法")
    item = await repository.get_stored_file(account.account_id, file_id, is_admin=account.role == "admin")
    if item is None:
        raise APIError(404, "file_not_found", "文件不存在")
    try:
        stored = await build_object_store(settings).get(item.object_key, item.mime_type)
    except ObjectStoreError as error:
        raise APIError(404, "object_not_found", "对象存储文件不存在") from error
    return Response(content=stored.data, media_type=item.mime_type, headers={"Cache-Control": "private, max-age=3600"})


@router.post("/search/image")
async def search_image(
    request: ImageSearchRequest,
    account: Account = Depends(get_current_account),
    repository: SQLRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    request_started = time.perf_counter()
    file_id = request.file_id.strip()
    image_url = request.image_url.strip()
    if not file_id and image_url:
        file_id = ImageSearchService.file_id_from_url(image_url)
        if file_id:
            image_url = ""
    data: bytes | None = None
    content_type = ""
    download_ms = 0
    if file_id:
        item = await repository.get_stored_file(account.account_id, file_id, is_admin=account.role == "admin")
        if item is None:
            raise APIError(404, "file_not_found", "文件不存在")
        download_started = time.perf_counter()
        try:
            obj = await build_object_store(settings).get(item.object_key, item.mime_type)
        except ObjectStoreError as error:
            raise APIError(404, "object_not_found", "对象存储文件不存在") from error
        data, content_type = obj.data, item.mime_type
        download_ms = int((time.perf_counter() - download_started) * 1000)
    elif not (request.object_key.strip() or image_url):
        raise APIError(400, "empty_image", "file_id、object_key 或 image_url 至少传一个")
    try:
        result = await _service(repository, settings, account).search(
            file_id="", object_key=request.object_key, image_url=image_url,
            data=data, content_type=content_type, top_k=request.top_k,
        )
        result["durations"]["download_ms"] = int(result["durations"].get("download_ms", 0)) + download_ms
        result["durations"]["total_ms"] = int((time.perf_counter() - request_started) * 1000)
        return result
    except FileNotFoundError as error:
        raise APIError(404, "file_not_found", "文件不存在") from error
    except (ImageEmbeddingError, OSError) as error:
        raise APIError(400, "image_embedding_failed", "图片解析失败") from error
    except ObjectStoreError as error:
        raise APIError(502, "object_store_unavailable", "对象存储不可用") from error

