from __future__ import annotations
# integrations/objectstore.py：本模块的中文学习说明。

# 对象存储适配器。
# 上层只需要保存、读取和删除文件，不需要知道本地目录还是 MinIO。
# 保存时返回稳定的对象键，读取时返回字节流。
# 路径和文件名必须经过安全处理，不能直接信任用户输入。

# 对象存储适配器：统一本地文件和 MinIO 的读写接口。

import io
import asyncio
from dataclasses import dataclass
from pathlib import Path


class ObjectStoreError(RuntimeError):
    """ObjectStoreError：封装同一类数据和行为，供上层模块通过稳定接口调用。"""
    pass


@dataclass(frozen=True)
class StoredObject:
    """StoredObject：封装同一类数据和行为，供上层模块通过稳定接口调用。"""
    key: str
    content_type: str
    size_bytes: int
    data: bytes


class LocalObjectStore:
    """LocalObjectStore：封装同一类数据和行为，供上层模块通过稳定接口调用。"""
    provider = "local"

    def __init__(self, root: str | Path) -> None:
        """执行 __init__：接收参数 root，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        # 固化根目录的绝对路径，后续所有 key 都必须落在该目录下。
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
    def _path(self, key: str) -> Path:
        """执行 _path：接收参数 key，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        # 统一分隔符并去掉首尾斜杠，减少不同平台路径差异。
        clean = key.replace("\\", "/").strip("/")
        path = (self.root / clean).resolve()
        # resolve 后再次检查父目录，阻止 ../ 路径穿越到存储根目录之外。
        if self.root not in path.parents:
            raise ObjectStoreError("对象 key 不合法")
        return path
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        """执行 put：接收参数 key、data、content_type，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        # 先通过安全路径检查，再创建父目录并写入字节数据。
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(data)
        except OSError as error:
            raise ObjectStoreError("对象存储写入失败") from error
        return StoredObject(key, content_type, len(data), data)
    async def get(self, key: str, content_type: str = "application/octet-stream") -> StoredObject:
        """执行 get：接收参数 key、content_type，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        path = self._path(key)
        try:
            data = path.read_bytes()
        except OSError as error:
            raise ObjectStoreError("对象不存在") from error
        return StoredObject(key, content_type, len(data), data)


class MinioObjectStore:
    """MinioObjectStore：封装同一类数据和行为，供上层模块通过稳定接口调用。"""
    provider = "minio"

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False) -> None:
        """执行 __init__：接收参数 endpoint、access_key、secret_key、bucket、secure，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        try:
            from minio import Minio
        except ImportError as error:  # pragma: no cover - deployment-only dependency
            raise ObjectStoreError("MinIO 依赖未安装") from error
        host = endpoint.split("://", 1)[-1]
        self.client = Minio(host, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
    async def _ensure_bucket(self) -> None:
        """执行 _ensure_bucket：接收参数 无，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        # MinIO SDK 是同步调用，放到线程中避免阻塞 FastAPI 事件循环。
        exists = await asyncio.to_thread(self.client.bucket_exists, self.bucket)
        if not exists:
            await asyncio.to_thread(self.client.make_bucket, self.bucket)
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        """执行 put：接收参数 key、data、content_type，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        try:
            await self._ensure_bucket()
            await asyncio.to_thread(self.client.put_object, self.bucket, key, io.BytesIO(data), len(data), content_type=content_type)
            return StoredObject(key, content_type, len(data), data)
        except Exception as error:  # pragma: no cover - deployment-only integration
            raise ObjectStoreError("MinIO 对象写入失败") from error
    async def get(self, key: str, content_type: str = "application/octet-stream") -> StoredObject:
        """执行 get：接收参数 key、content_type，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        # response 必须在 finally 中关闭并释放连接，否则长期运行会耗尽连接池。
        response = None
        try:
            response = await asyncio.to_thread(self.client.get_object, self.bucket, key)
            data = await asyncio.to_thread(response.read)
            return StoredObject(key, content_type, len(data), data)
        except Exception as error:  # pragma: no cover - deployment-only integration
            raise ObjectStoreError("MinIO 对象读取失败") from error
        finally:
            if response is not None:
                response.close()
                response.release_conn()
def build_object_store(settings) -> LocalObjectStore | MinioObjectStore:
    # MinIO is an optional deployment integration. The local store is deterministic for
    # development and keeps the API usable when no MinIO SDK/service is installed.
    """执行 build_object_store：接收参数 settings，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
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

