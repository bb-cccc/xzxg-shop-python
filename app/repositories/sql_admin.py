from __future__ import annotations

# 数据访问模块：把业务查询封装为异步 Repository 操作。

from app.repositories.sql_support import *  # noqa: F401,F403


# 能力混入类，把这一领域的操作组合到主类中。
class AdminRepositoryMixin:

    async def list_accounts(self, page: int=1, page_size: int=10) -> tuple[list[Account], int]:
        total = int((await self.session.execute(select(func.count(Account.account_id)))).scalar_one() or 0)
        stmt = select(Account).order_by(Account.created_at, Account.account_id).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)


    async def update_account_status(self, account_id: str, status: str) -> Account | None:
        item = await self.session.get(Account, account_id)
        if item is None:
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_admin_products(self, page: int=1, page_size: int=10) -> tuple[list[tuple[Product, Merchant, ProductSKU | None]], int]:
        total = int((await self.session.execute(select(func.count(Product.product_id)))).scalar_one() or 0)
        stmt = self._product_record_query().order_by(Product.created_at.desc(), Product.product_id).offset((page - 1) * page_size).limit(page_size)
        return ([(product, merchant, sku) for product, merchant, sku in (await self.session.execute(stmt)).all()], total)

    async def create_product(self, product: Product) -> Product:
        self.session.add(product)
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def update_product(self, product_id: str, merchant_id: str, values: dict[str, object]) -> tuple[Product, Merchant, ProductSKU | None] | None:
        product = await self.session.scalar(select(Product).where(Product.product_id == product_id, Product.merchant_id == merchant_id))
        if product is None:
            return None
        for key, value in values.items():
            if hasattr(product, key) and value is not None and (key not in {'product_id', 'merchant_id'}):
                setattr(product, key, value)
        product.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return await self.get_product_record(product_id)

    async def update_product_status(self, product_id: str, status: str, merchant_id: str='') -> Product | None:
        stmt = select(Product).where(Product.product_id == product_id)
        if merchant_id:
            stmt = stmt.where(Product.merchant_id == merchant_id)
        item = await self.session.scalar(stmt)
        if item is None:
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_merchants_admin(self, page: int=1, page_size: int=10) -> tuple[list[Merchant], int]:
        total = int((await self.session.execute(select(func.count(Merchant.merchant_id)))).scalar_one() or 0)
        stmt = select(Merchant).order_by(Merchant.created_at, Merchant.merchant_id).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)

    async def update_merchant_status(self, merchant_id: str, status: str) -> Merchant | None:
        item = await self.session.get(Merchant, merchant_id)
        if item is None:
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_configs(self, page: int=1, page_size: int=10) -> tuple[list[AppConfig], int]:
        filters = [~AppConfig.config_key.like('agent.prompt.%')]
        total = int((await self.session.execute(select(func.count(AppConfig.config_key)).where(*filters))).scalar_one() or 0)
        stmt = select(AppConfig).where(*filters).order_by(AppConfig.config_key).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)

    async def config_values(self) -> dict[str, str]:
        rows = list((await self.session.execute(select(AppConfig))).scalars().all())
        return {item.config_key: item.config_value for item in rows}

    async def upsert_config(self, key: str, value: str, value_type: str, description: str, is_secret: bool) -> AppConfig:
        item = await self.session.get(AppConfig, key)
        now = datetime.now(timezone.utc)
        if item is None:
            item = AppConfig(config_key=key, config_value=value, value_type=value_type or 'string', description=description, domain=key.split('.', 1)[0], is_secret=is_secret, updated_at=now)
            self.session.add(item)
        else:
            item.config_value = value
            item.value_type = value_type or item.value_type
            item.description = description
            item.is_secret = is_secret
            item.updated_at = now
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_prompts(self, page: int=1, page_size: int=10) -> tuple[list[AgentPrompt], int]:
        latest = select(AgentPrompt.prompt_key, func.max(AgentPrompt.version).label('version')).group_by(AgentPrompt.prompt_key).subquery()
        stmt_base = select(AgentPrompt).join(latest, and_(AgentPrompt.prompt_key == latest.c.prompt_key, AgentPrompt.version == latest.c.version))
        total = len(list((await self.session.execute(stmt_base)).scalars().all()))
        stmt = stmt_base.order_by(AgentPrompt.prompt_key).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)

    async def get_active_prompt(self, prompt_key: str) -> AgentPrompt | None:
        return await self.session.scalar(select(AgentPrompt).where(AgentPrompt.prompt_key == prompt_key, AgentPrompt.status == 'active').order_by(AgentPrompt.version.desc()).limit(1))

    async def save_prompt_draft(self, prompt_key: str, title: str, content: str, description: str, created_by: str) -> AgentPrompt:
        latest = await self.session.scalar(select(func.max(AgentPrompt.version)).where(AgentPrompt.prompt_key == prompt_key))
        item = AgentPrompt(prompt_id=self._new_id('prm'), prompt_key=prompt_key.strip(), title=title.strip() or prompt_key.strip(), content=content.strip(), status='draft', version=int(latest or 0) + 1, description=description.strip(), created_by=created_by, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def publish_prompt(self, prompt_key: str, published_by: str, target: str='database') -> tuple[AgentPrompt, AgentPromptPublishRecord] | None:
        await self._prepare_write()
        async with self.session.begin():
            prompt = await self.session.scalar(select(AgentPrompt).where(AgentPrompt.prompt_key == prompt_key).order_by(AgentPrompt.version.desc()).limit(1))
            if prompt is None:
                return None
            now = datetime.now(timezone.utc)
            await self.session.execute(update(AgentPrompt).where(AgentPrompt.prompt_key == prompt_key, AgentPrompt.status == 'active').values(status='archived', updated_at=now))
            prompt.status = 'active'
            prompt.published_at = now
            prompt.updated_at = now
            record = AgentPromptPublishRecord(record_id=self._new_id('prmpub'), prompt_key=prompt_key, prompt_id=prompt.prompt_id, version=prompt.version, published_by=published_by, publish_target=target or 'database', created_at=now)
            self.session.add(record)
            await self.session.flush()
        await self.session.refresh(prompt)
        await self.session.refresh(record)
        return (prompt, record)

    async def list_prompt_publish_records(self, prompt_key: str='', limit: int=20) -> list[AgentPromptPublishRecord]:
        stmt = select(AgentPromptPublishRecord)
        if prompt_key:
            stmt = stmt.where(AgentPromptPublishRecord.prompt_key == prompt_key)
        stmt = stmt.order_by(AgentPromptPublishRecord.created_at.desc(), AgentPromptPublishRecord.record_id.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_admin_runs(self, page: int=1, page_size: int=10) -> tuple[list[AgentRun], int]:
        total = int((await self.session.execute(select(func.count(AgentRun.run_id)))).scalar_one() or 0)
        stmt = select(AgentRun).order_by(AgentRun.created_at.desc(), AgentRun.run_id.desc()).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)

    async def list_admin_trace(self, run_id: str) -> list[AgentTraceEvent]:
        stmt = select(AgentTraceEvent).where(AgentTraceEvent.run_id == run_id).order_by(AgentTraceEvent.created_at, AgentTraceEvent.trace_event_id)
        return list((await self.session.execute(stmt)).scalars().all())
