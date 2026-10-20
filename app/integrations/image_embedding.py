from __future__ import annotations
# integrations/image_embedding.py：本模块的中文学习说明。

# 图片向量生成适配器。
# 输入是图片字节，输出是固定长度的浮点向量。
# 本地直方图实现适合开发测试，远程模型实现适合生产效果。
# 所有实现遵守同一个接口，调用方无需改代码。

# 图片向量适配器：把图片转换为可比较的 embedding。

import base64
import binascii
import io
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional runtime dependency
    Image = None  # type: ignore[assignment,misc]


class ImageEmbeddingError(RuntimeError):
    """A safe, user-facing image embedding failure."""


class ImageEmbedder:
    """ImageEmbedder：封装同一类数据和行为，供上层模块通过稳定接口调用。"""
    provider = "unknown"
    dimension = 0
    async def embed_bytes(self, data: bytes, content_type: str = "") -> list[float]:
        """执行 embed_bytes：接收参数 data、content_type，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        raise NotImplementedError
    async def embed_source(self, source: str) -> list[float]:
        """执行 embed_source：接收参数 source，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        raise NotImplementedError
def _decode_data_url(source: str) -> tuple[bytes, str] | None:
    """执行 _decode_data_url：接收参数 source，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
    if not source.startswith("data:") or "," not in source:
        return None
    header, encoded = source.split(",", 1)
    if ";base64" not in header:
        return None
    try:
        return base64.b64decode(encoded, validate=True), header[5:].split(";", 1)[0] or "application/octet-stream"
    except (binascii.Error, ValueError) as error:
        raise ImageEmbeddingError("图片 data URL 不合法") from error
def resolve_local_source(source: str) -> Path | None:
    """执行 resolve_local_source：接收参数 source，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
    raw = source.strip()
    if raw.startswith("/api/v1/assets/ecommerce_agent_dataset/"):
        raw = raw.removeprefix("/api/v1/assets/ecommerce_agent_dataset/")
        root = Path(__file__).resolve().parents[3] / "quality" / "data" / "ecommerce_agent_dataset"
        candidate = (root / raw).resolve()
        if root.resolve() in candidate.parents:
            return candidate
    if raw.startswith("file://"):
        raw = urlparse(raw).path
    path = Path(raw)
    candidates = [path]
    if not path.is_absolute():
        project_root = Path(__file__).resolve().parents[3]
        candidates.extend([project_root / path, project_root / ".." / path])
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved.is_file():
                return resolved
        except OSError:
            continue
    return None


class LocalHistogramEmbedder(ImageEmbedder):
    """LocalHistogramEmbedder：封装同一类数据和行为，供上层模块通过稳定接口调用。"""
    provider = "local_histogram"
    dimension = 64

    @staticmethod
    def from_bytes(data: bytes) -> list[float]:
        """执行 from_bytes：接收参数 data，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        if not data:
            raise ImageEmbeddingError("图片为空")
        if Image is None:
            raise ImageEmbeddingError("图片解析依赖未安装")
        try:
            image = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as error:
            raise ImageEmbeddingError("图片解析失败") from error
        vector = [0.0] * 64
        total = image.width * image.height
        if total == 0:
            return vector
        for red, green, blue in image.getdata():
            index = (red // 64) * 16 + (green // 64) * 4 + (blue // 64)
            vector[index] += 1.0 / total
        return vector
    async def embed_bytes(self, data: bytes, content_type: str = "") -> list[float]:
        """执行 embed_bytes：接收参数 data、content_type，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        return self.from_bytes(data)
    async def embed_source(self, source: str) -> list[float]:
        """执行 embed_source：接收参数 source，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        decoded = _decode_data_url(source.strip())
        if decoded is not None:
            return self.from_bytes(decoded[0])
        path = resolve_local_source(source)
        if path is None:
            if source.lower().startswith(("http://", "https://")):
                try:
                    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                        response = await client.get(source)
                        response.raise_for_status()
                        return self.from_bytes(response.content)
                except Exception as error:
                    raise ImageEmbeddingError("图片下载失败") from error
            raise ImageEmbeddingError("图片来源不存在")
        try:
            return self.from_bytes(path.read_bytes())
        except OSError as error:
            raise ImageEmbeddingError("图片读取失败") from error


@dataclass
class DashScopeImageEmbedder(ImageEmbedder):
    """DashScopeImageEmbedder：封装同一类数据和行为，供上层模块通过稳定接口调用。"""
    base_url: str
    api_key: str
    model: str = "qwen3-vl-embedding"
    dimension: int = 512
    timeout_seconds: float = 20.0
    provider: str = "dashscope"
    async def embed_bytes(self, data: bytes, content_type: str = "") -> list[float]:
        """执行 embed_bytes：接收参数 data、content_type，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        if not data:
            raise ImageEmbeddingError("图片为空")
        mime = content_type or "image/jpeg"
        image = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        return await self._embed_image(image)
    async def embed_source(self, source: str) -> list[float]:
        """执行 embed_source：接收参数 source，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        source = source.strip()
        decoded = _decode_data_url(source)
        if decoded is not None:
            return await self.embed_bytes(decoded[0], decoded[1])
        if source.lower().startswith(("http://", "https://")):
            return await self._embed_image(source)
        path = resolve_local_source(source)
        if path is None:
            raise ImageEmbeddingError("图片来源不存在")
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        return await self.embed_bytes(path.read_bytes(), mime)
    async def _embed_image(self, image: str) -> list[float]:
        """执行 _embed_image：接收参数 image，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        if not self.api_key.strip():
            raise ImageEmbeddingError("图片 embedding 未配置 API key")
        payload: dict[str, Any] = {
            "model": self.model,
            "input": {"contents": [{"image": image}]},
            "parameters": {"dimension": self.dimension, "output_type": "dense"},
        }
        url = self.base_url.rstrip("/") + "/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, json=payload, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        except httpx.HTTPError as error:
            raise ImageEmbeddingError("图片 embedding 服务不可用") from error
        if response.status_code < 200 or response.status_code >= 300:
            raise ImageEmbeddingError(f"图片 embedding 服务返回 {response.status_code}")
        try:
            body = response.json()
            if body.get("code") not in (None, "", "200", 200):
                raise ImageEmbeddingError("图片 embedding 服务返回错误")
            vector = body["output"]["embeddings"][0]["embedding"]
            if not isinstance(vector, list) or not vector:
                raise KeyError("embedding")
            return [float(value) for value in vector]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ImageEmbeddingError("图片 embedding 响应格式错误") from error
def build_image_embedder(settings) -> ImageEmbedder:
    """执行 build_image_embedder：接收参数 settings，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
    provider = getattr(settings, "image_embedding_provider", "local_histogram").strip().lower()
    if provider == "dashscope":
        return DashScopeImageEmbedder(
            base_url=getattr(settings, "image_embedding_base_url", "https://dashscope.aliyuncs.com"),
            api_key=getattr(settings, "image_embedding_api_key", "") or getattr(settings, "ai_api_key", ""),
            model=getattr(settings, "image_embedding_model", "qwen3-vl-embedding"),
            dimension=int(getattr(settings, "image_embedding_dimension", 512)),
            timeout_seconds=float(getattr(settings, "image_embedding_timeout_seconds", 20.0)),
        )
    return LocalHistogramEmbedder()

