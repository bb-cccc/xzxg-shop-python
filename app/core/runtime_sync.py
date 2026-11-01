from __future__ import annotations



import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.runtime_config import apply_database_config
from app.domain.models import AgentPrompt, AppConfig
from app.integrations.nacos import NacosConfigCenter, NacosUnavailable
from app.repositories.sql import SQLRepository



class RuntimeConfigSynchronizer:
    """保持数据库配置、Nacos 配置和请求设置三者一致"""

    def __init__(self, base_settings, session_factory: async_sessionmaker, nacos: NacosConfigCenter) -> None:
        self.base_settings = base_settings
        self.session_factory = session_factory
        self.nacos = nacos
        self.logger = logging.getLogger("xzxg.config")

    async def refresh(self):
        async with self.session_factory() as session:
            values = await SQLRepository(session).config_values()

        if self.nacos.enabled:
            try:
                config_document = await self.nacos.read()
                config_items = config_document.get("configs", []) if isinstance(config_document, dict) else []
                if isinstance(config_items, list):
                    async with self.session_factory() as session:
                        for item in config_items:
                            if not isinstance(item, dict) or not item.get("config_key"):
                                continue
                            key = str(item["config_key"])
                            value = str(item.get("config_value") or "")
                            values[key] = value
                            existing = await session.get(AppConfig, key)
                            if existing is None:
                                session.add(AppConfig(config_key=key, config_value=value, value_type=str(item.get("value_type") or "string"), description=str(item.get("description") or ""), domain=str(item.get("domain") or ""), is_secret=bool(item.get("is_secret", False)), updated_at=datetime.now(timezone.utc)))
                            elif not existing.is_secret and existing.config_value != value:
                                existing.config_value = value
                                existing.updated_at = datetime.now(timezone.utc)
                        await session.commit()

                prompt_document = await self.nacos.read(self.nacos.prompt_data_id)
                prompt_items = prompt_document.get("prompts", []) if isinstance(prompt_document, dict) else []
                if isinstance(prompt_items, list):
                    async with self.session_factory() as session:
                        for item in prompt_items:
                            if not isinstance(item, dict) or not item.get("prompt_key") or not item.get("content"):
                                continue
                            key = str(item["prompt_key"])
                            version = int(item.get("version") or 1)
                            existing = await session.scalar(select(AgentPrompt).where(AgentPrompt.prompt_key == key, AgentPrompt.version == version).limit(1))
                            if existing is None:
                                session.add(AgentPrompt(prompt_id=str(item.get("prompt_id") or f"nacos_{key}_{version}"), prompt_key=key, title=str(item.get("title") or key), content=str(item["content"]), status=str(item.get("status") or "active"), version=version, description=str(item.get("description") or ""), created_by="nacos", published_at=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
                            else:
                                existing.title = str(item.get("title") or existing.title)
                                existing.content = str(item["content"])
                                existing.status = str(item.get("status") or existing.status)
                                existing.description = str(item.get("description") or existing.description)
                                existing.updated_at = datetime.now(timezone.utc)
                        await session.commit()
            except NacosUnavailable:
                self.logger.warning("Nacos unavailable; retaining database runtime configuration")
            except (SQLAlchemyError, OSError, ValueError, TypeError):
                self.logger.exception("Runtime configuration refresh failed; retaining previous configuration")

        return apply_database_config(self.base_settings, values)
