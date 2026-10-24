"""Small Nacos config adapter with database fallback.

The API never requires Nacos for local startup. Deployments can call this
adapter from a refresh task and persist the returned values in ``app_configs``.
"""

from __future__ import annotations

# 外部服务适配器模块：统一对象存储、向量、重排和配置中心接口。

import json
from dataclasses import dataclass, field
from typing import Any

import httpx


class NacosUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class NacosConfigCenter:
    address: str
    namespace: str = ""
    group: str = "XZXG_SHOP"
    data_id: str = "xzxg-shop-app-config.json"
    prompt_data_id: str = "xzxg-shop-prompt-config.json"
    timeout_seconds: float = 5.0
    username: str = ""
    password: str = ""
    _access_token: str = field(default="", init=False, repr=False)

    @property
    def enabled(self) -> bool:
        return bool(self.address.strip())

    async def _auth_params(self, client: httpx.AsyncClient) -> dict[str, str]:
        if self._access_token:
            return {"accessToken": self._access_token}
        if not (self.username.strip() and self.password):
            return {}
        try:
            response = await client.post(
                self.address.rstrip("/") + "/nacos/v1/auth/login",
                data={"username": self.username, "password": self.password},
            )
            response.raise_for_status()
            payload = response.json()
            self._access_token = str(payload.get("accessToken") or "")
            if not self._access_token:
                raise NacosUnavailable("Nacos login response has no access token")
            return {"accessToken": self._access_token}
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise NacosUnavailable("Nacos login failed") from error

    async def read(self, data_id: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise NacosUnavailable("Nacos is not configured")
        params = {"dataId": data_id or self.data_id, "group": self.group}
        if self.namespace:
            params["tenant"] = self.namespace
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                params.update(await self._auth_params(client))
                response = await client.get(self.address.rstrip("/") + "/nacos/v1/cs/configs", params=params)
                response.raise_for_status()
                payload = response.json() if "application/json" in response.headers.get("content-type", "") else json.loads(response.text)
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise NacosUnavailable("Nacos config read failed") from error
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            return {"configs": payload}
        raise NacosUnavailable("Nacos config payload is invalid")

    async def publish(self, document: dict[str, Any], data_id: str | None = None) -> None:
        if not self.enabled:
            raise NacosUnavailable("Nacos is not configured")
        data = {"dataId": data_id or self.data_id, "group": self.group, "content": json.dumps(document, ensure_ascii=False, indent=2)}
        if self.namespace:
            data["tenant"] = self.namespace
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                data.update(await self._auth_params(client))
                response = await client.post(self.address.rstrip("/") + "/nacos/v1/cs/configs", data=data)
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise NacosUnavailable("Nacos config publish failed") from error
