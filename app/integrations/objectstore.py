from __future__ import annotations

# 外部服务适配器模块：统一对象存储、向量、重排和配置中心接口。

import io
import asyncio
from dataclasses import dataclass
from pathlib import Path

try:
    from minio.error import MinioException
except ImportError:  # pragma: no cover - MinIO is optional in local tests
    class MinioException(Exception):
        pass

try:
    from urllib3.exceptions import HTTPError as Urllib3HTTPError
except ImportError:  # pragma: no cover - provided by the MinIO client
    class Urllib3HTTPError(Exception):
        pass


# 自定义异常类型，用于向上层表达可预期的失败。
class ObjectStoreError(RuntimeError):
    pass


# 模块中的核心类型，封装相关状态和行为。
@dataclass(frozen=True)
class StoredObject:
    key: str
    content_type: str
    size_bytes: int
    data: bytes


# 外部能力适配器，对上层提供稳定的调用接口。
class LocalObjectStore:
    provider = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        clean = key.replace("\\", "/").strip("/")
        path = (self.root / clean).resolve()
        if self.root not in path.parents:
            raise ObjectStoreError("对象 key 不合法")
        return path

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(data)
        except OSError as error:
            raise ObjectStoreError("对象存储写入失败") from error
        return StoredObject(key, content_type, len(data), data)

    async def get(self, key: str, content_type: str = "application/octet-stream") -> StoredObject:
        path = self._path(key)
        try:
            data = path.read_bytes()
        except OSError as error:
            raise ObjectStoreError("对象不存在") from error
        return StoredObject(key, content_type, len(data), data)


# 外部能力适配器，对上层提供稳定的调用接口。
class MinioObjectStore:
    provider = "minio"

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False) -> None:
        try:
            from minio import Minio
        except ImportError as error:  # pragma: no cover - deployment-only dependency
            raise ObjectStoreError("MinIO 依赖未安装") from error
        host = endpoint.split("://", 1)[-1]
        self.client = Minio(host, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket

    async def _ensure_bucket(self) -> None:
        exists = await asyncio.to_thread(self.client.bucket_exists, self.bucket)
        if not exists:
            await asyncio.to_thread(self.client.make_bucket, self.bucket)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        try:
            await self._ensure_bucket()
            await asyncio.to_thread(self.client.put_object, self.bucket, key, io.BytesIO(data), len(data), content_type=content_type)
            return StoredObject(key, content_type, len(data), data)
        except (MinioException, Urllib3HTTPError, OSError, ValueError, TypeError) as error:  # pragma: no cover - deployment-only integration
            raise ObjectStoreError("MinIO 对象写入失败") from error

    async def get(self, key: str, content_type: str = "application/octet-stream") -> StoredObject:
        response = None
        try:
            response = await asyncio.to_thread(self.client.get_object, self.bucket, key)
            data = await asyncio.to_thread(response.read)
            return StoredObject(key, content_type, len(data), data)
        except (MinioException, Urllib3HTTPError, OSError, ValueError, TypeError) as error:  # pragma: no cover - deployment-only integration
            raise ObjectStoreError("MinIO 对象读取失败") from error
        finally:
            if response is not None:
                response.close()
                response.release_conn()

def build_object_store(settings) -> LocalObjectStore | MinioObjectStore:
    # MinIO is an optional deployment integration. The local store is deterministic for
    # development and keeps the API usable when no MinIO SDK/service is installed.
    provider = getattr(settings, "file_storage_provider", "local").strip().lower()
    if provider == "minio":
        return MinioObjectStore(
            getattr(settings, "minio_endpoint", "127.0.0.1:9000"),
            getattr(settings, "minio_access_key", ""),
            getattr(settings, "minio_secret_key", ""),
            getattr(settings, "minio_bucket", "xzxg-shop"),
        )
    root = getattr(settings, "file_storage_local_dir", "./backend_py_uploads")
    return LocalObjectStore(root)

