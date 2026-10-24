from __future__ import annotations

# 外部服务适配器模块：统一对象存储、向量、重排和配置中心接口。

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import Settings


class LLMUnavailable(RuntimeError):
    pass


# 外部能力适配器，对上层提供稳定的调用接口。
class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.ai_enabled and self.settings.ai_base_url and self.settings.ai_api_key)

    def _url(self) -> str:
        return self.settings.ai_base_url.rstrip("/") + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.ai_api_key}", "Content-Type": "application/json"}

    async def complete(self, messages: list[dict[str, str]], *, model: str | None = None, temperature: float = 0.2) -> str:
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
