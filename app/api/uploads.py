from __future__ import annotations



import secrets
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from app.api.dependencies import get_app_settings, get_current_account
from app.core.config import Settings
from app.core.errors import APIError
from app.domain.models import Account


router = APIRouter(tags=["uploads"])
_MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _avatar_root(settings: Settings) -> Path:
    return Path(settings.avatar_upload_root).expanduser().resolve()


def _image_type(data: bytes) -> tuple[str, str] | None:
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            fmt = (image.format or "").upper()
    except (UnidentifiedImageError, OSError):
        return None
    return {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp")}.get(fmt)


@router.post("/uploads/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    account: Account = Depends(get_current_account),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    data = await file.read(_MAX_AVATAR_BYTES + 1)
    if not data:
        raise APIError(400, "missing_file", "请选择头像文件")
    if len(data) > _MAX_AVATAR_BYTES:
        raise APIError(400, "file_too_large", "头像不能超过 2MB")
    image_type = _image_type(data)
    if image_type is None:
        raise APIError(400, "bad_image_type", "头像仅支持 JPG、PNG 或 WebP")
    mime_type, extension = image_type
    root = _avatar_root(settings)
    try:
        root.mkdir(parents=True, exist_ok=True)
        filename = f"{account.account_id}_{secrets.token_hex(8)}{extension}"
        (root / filename).write_bytes(data)
    except OSError as error:
        raise APIError(500, "save_file_failed", "保存头像失败") from error
    return {"url": f"/api/v1/uploads/avatar/{filename}", "mime_type": mime_type, "size": len(data)}


@router.get("/uploads/avatar/{filename}")
async def get_avatar(filename: str, settings: Settings = Depends(get_app_settings)) -> FileResponse:
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise APIError(400, "bad_avatar_name", "头像文件名不合法")
    root = _avatar_root(settings)
    candidate = (root / filename).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise APIError(404, "avatar_not_found", "头像不存在")
    return FileResponse(candidate, headers={"Cache-Control": "public, max-age=86400"})
