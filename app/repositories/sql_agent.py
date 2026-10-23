from __future__ import annotations

# 数据访问模块：把业务查询封装为异步 Repository 操作。

from app.repositories.sql_support import *  # noqa: F401,F403


# 能力混入类，把这一领域的操作组合到主类中。
class AgentRepositoryMixin:
    async def create_session(self, account_id: str, title: str) -> ChatSession:
        now = datetime.now(timezone.utc)
        item = ChatSession(session_id=self._new_id('sess'), account_id=account_id, title=title.strip() or 'AI 导购', summary='', message_count=0, last_message_at=now, created_at=now, updated_at=now)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_session(self, account_id: str, session_id: str) -> ChatSession | None:
        stmt = select(ChatSession).where(ChatSession.account_id == account_id, ChatSession.session_id == session_id, ChatSession.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_sessions(self, account_id: str, page: int, page_size: int) -> tuple[list[ChatSession], int]:
        filters = [ChatSession.account_id == account_id, ChatSession.message_count > 0, ChatSession.deleted_at.is_(None)]
        total = int((await self.session.execute(select(func.count(ChatSession.session_id)).where(*filters))).scalar_one() or 0)
        stmt = select(ChatSession).where(*filters).order_by(ChatSession.pinned_at.is_(None), ChatSession.pinned_at.desc(), ChatSession.last_message_at.desc(), ChatSession.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)

    async def search_sessions(self, account_id: str, keyword: str, page: int, page_size: int) -> tuple[list[ChatSession], int]:
        keyword = keyword.strip()
        if not keyword:
            return await self.list_sessions(account_id, page, page_size)
        like = f'%{keyword}%'
        filters = [ChatSession.account_id == account_id, ChatSession.message_count > 0, ChatSession.deleted_at.is_(None)]
        stmt_base = select(ChatSession).outerjoin(UserMessage, and_(UserMessage.session_id == ChatSession.session_id, UserMessage.account_id == ChatSession.account_id)).where(*filters, or_(ChatSession.title.ilike(like), ChatSession.summary.ilike(like), UserMessage.content.ilike(like))).distinct()
        total = len((await self.session.execute(stmt_base)).scalars().all())
        stmt = stmt_base.order_by(ChatSession.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)

    async def update_session(self, account_id: str, session_id: str, title: str, summary: str) -> ChatSession | None:
        item = await self.get_session(account_id, session_id)
        if item is None:
            return None
        if title.strip():
            item.title = title.strip()[:128]
        if summary.strip():
            item.summary = summary.strip()[:500]
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def pin_session(self, account_id: str, session_id: str, pinned: bool) -> ChatSession | None:
        item = await self.get_session(account_id, session_id)
        if item is None:
            return None
        item.pinned_at = datetime.now(timezone.utc) if pinned else None
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete_session(self, account_id: str, session_id: str) -> bool:
        item = await self.get_session(account_id, session_id)
        if item is None:
            return False
        item.deleted_at = datetime.now(timezone.utc)
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True

    async def create_user_message(self, account_id: str, session_id: str, client_message_id: str, content: str, attachments: list[dict[str, object]]) -> tuple[UserMessage, bool]:
        client_message_id = client_message_id.strip() or f"server_{self._new_id('msg')}"
        existing = await self.session.scalar(select(UserMessage).where(UserMessage.account_id == account_id, UserMessage.session_id == session_id, UserMessage.client_message_id == client_message_id))
        if existing is not None:
            return (existing, False)
        now = datetime.now(timezone.utc)
        item = UserMessage(message_id=self._new_id('msg'), session_id=session_id, account_id=account_id, client_message_id=client_message_id, content=content, attachments_json=attachments, created_at=now)
        self.session.add(item)
        session = await self.get_session(account_id, session_id)
        if session is None:
            raise ValueError('session not found')
        if session.title in ('', 'AI 导购'):
            session.title = content.strip()[:128] or 'AI 导购'
        if not session.summary:
            session.summary = content.strip()[:500]
        session.message_count += 1
        session.last_message_at = now
        session.updated_at = now
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(select(UserMessage).where(UserMessage.account_id == account_id, UserMessage.session_id == session_id, UserMessage.client_message_id == client_message_id))
            if existing is None:
                raise
            return (existing, False)
        await self.session.refresh(item)
        return (item, True)

    async def create_run(self, account_id: str, session_id: str, message_id: str) -> tuple[AgentRun, bool]:
        existing = await self.session.scalar(select(AgentRun).where(AgentRun.account_id == account_id, AgentRun.message_id == message_id))
        if existing is not None:
            return (existing, False)
        now = datetime.now(timezone.utc)
        item = AgentRun(run_id=self._new_id('run'), session_id=session_id, message_id=message_id, account_id=account_id, status='running', trace_id=self._new_id('trace'), content='', blocks_json=[], followups_json=[], segments_json=[], created_at=now, updated_at=now)
        self.session.add(item)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(select(AgentRun).where(AgentRun.account_id == account_id, AgentRun.message_id == message_id))
            if existing is None:
                raise
            return (existing, False)
        await self.session.refresh(item)
        return (item, True)

    async def get_run(self, account_id: str, run_id: str) -> AgentRun | None:
        return await self.session.scalar(select(AgentRun).where(AgentRun.account_id == account_id, AgentRun.run_id == run_id))

    async def update_run_status(self, account_id: str, run_id: str, status: str) -> AgentRun | None:
        item = await self.get_run(account_id, run_id)
        if item is None or (item.status != 'running' and status in {'completed', 'failed', 'canceled'}):
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def update_run_result(self, account_id: str, run_id: str, content: str, blocks: list[dict[str, object]], followups: list[str], segments: list[dict[str, object]]) -> bool:
        item = await self.get_run(account_id, run_id)
        if item is None:
            return False
        item.content = content
        item.blocks_json = blocks
        item.followups_json = followups
        item.segments_json = segments
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True

    async def is_run_canceled(self, run_id: str) -> bool:
        item = await self.session.scalar(select(AgentRun.status).where(AgentRun.run_id == run_id))
        return item == 'canceled'

    async def record_trace(self, run_id: str, trace_id: str, account_id: str, stage: str, event_type: str, status: str='ok', model: str='', duration_ms: int=0, error: str='', metadata: dict[str, object] | None=None) -> None:
        self.session.add(AgentTraceEvent(trace_event_id=self._new_id('trc'), run_id=run_id, trace_id=trace_id, account_id=account_id, stage=stage, event_type=event_type, model=model, status=status, duration_ms=duration_ms, error=error, metadata_json=metadata or {}, created_at=datetime.now(timezone.utc)))
        await self.session.commit()

    async def list_trace(self, account_id: str, run_id: str) -> list[AgentTraceEvent]:
        stmt = select(AgentTraceEvent).where(AgentTraceEvent.account_id == account_id, AgentTraceEvent.run_id == run_id).order_by(AgentTraceEvent.created_at, AgentTraceEvent.trace_event_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_session_detail(self, account_id: str, session_id: str) -> tuple[ChatSession, list[tuple[UserMessage, list[AgentRun]]]] | None:
        session = await self.get_session(account_id, session_id)
        if session is None:
            return None
        messages = list((await self.session.execute(select(UserMessage).where(UserMessage.account_id == account_id, UserMessage.session_id == session_id).order_by(UserMessage.created_at, UserMessage.message_id))).scalars().all())
        result: list[tuple[UserMessage, list[AgentRun]]] = []
        for message in messages:
            runs = list((await self.session.execute(select(AgentRun).where(AgentRun.account_id == account_id, AgentRun.message_id == message.message_id).order_by(AgentRun.created_at, AgentRun.run_id))).scalars().all())
            result.append((message, runs))
        return (session, result)

    async def last_product_ids(self, account_id: str, session_id: str) -> list[str]:
        stmt = select(AgentRun.blocks_json).where(AgentRun.account_id == account_id, AgentRun.session_id == session_id, AgentRun.status == 'completed').order_by(AgentRun.created_at.desc()).limit(5)
        seen: set[str] = set()
        result: list[str] = []
        for blocks in (await self.session.execute(stmt)).scalars().all():
            for block in blocks or []:
                for product_id in block.get('product_ids', []) if isinstance(block, dict) else []:
                    if product_id not in seen:
                        seen.add(product_id)
                        result.append(product_id)
                product = block.get('product') if isinstance(block, dict) else None
                if isinstance(product, dict) and product.get('productId') and (product['productId'] not in seen):
                    seen.add(product['productId'])
                    result.append(product['productId'])
        return result
