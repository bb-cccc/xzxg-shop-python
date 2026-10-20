from __future__ import annotations
# integrations/llm.py：本模块的中文学习说明。

# 大模型 HTTP 适配器。
# 把提示词、模型名和超时配置转换为远程请求。
# 普通调用返回完整结果，流式调用逐段产生文本。
# 网络异常不能泄露密钥或内部堆栈，应转换为安全错误。

# 大模型适配器：封装远程模型请求和流式响应。

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import Settings


class LLMUnavailable(RuntimeError):
    """LLMUnavailable：封装同一类数据和行为，供上层模块通过稳定接口调用。"""
    pass


class LLMClient:
    """LLMClient：封装同一类数据和行为，供上层模块通过稳定接口调用。"""
    def __init__(self, settings: Settings) -> None:
        """执行 __init__：接收参数 settings，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        self.settings = settings

    @property
    def enabled(self) -> bool:
        """执行 enabled：接收参数 无，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        return bool(self.settings.ai_enabled and self.settings.ai_base_url and self.settings.ai_api_key)
    def _url(self) -> str:
        """执行 _url：接收参数 无，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        return self.settings.ai_base_url.rstrip("/") + "/chat/completions"
    def _headers(self) -> dict[str, str]:
        """执行 _headers：接收参数 无，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        return {"Authorization": f"Bearer {self.settings.ai_api_key}", "Content-Type": "application/json"}
    async def complete(self, messages: list[dict[str, str]], *, model: str | None = None, temperature: float = 0.2) -> str:
        """执行 complete：接收参数 messages、model、temperature，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        if not self.enabled:
            raise LLMUnavailable("LLM is disabled")
        payload = {"model": model or self.settings.ai_large_model, "messages": messages, "temperature": temperature, "stream": False}
        try:
            async with httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds) as client:
                response = await client.post(self._url(), headers=self._headers(), json=payload)
                response.raise_for_status()
                data = response.json()
            return str(data["choices"][0]["message"]["content"] or "")
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise LLMUnavailable("LLM request failed") from error
    async def stream(self, messages: list[dict[str, str]], *, model: str | None = None, temperature: float = 0.2) -> AsyncIterator[str]:
        """执行 stream：接收参数 messages、model、temperature，完成本层的业务处理并返回结果；失败时向上抛出可处理异常。"""
        if not self.enabled:
            raise LLMUnavailable("LLM is disabled")
        payload = {"model": model or self.settings.ai_large_model, "messages": messages, "temperature": temperature, "stream": True}
        try:
            async with httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds) as client:
                async with client.stream("POST", self._url(), headers=self._headers(), json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data: dict[str, Any] = json.loads(raw)
                            delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            continue
                        if delta:
                            yield str(delta)
        except httpx.HTTPError as error:
            raise LLMUnavailable("LLM stream failed") from error
