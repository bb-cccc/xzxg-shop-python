from __future__ import annotations



import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.agent.output import event, sse_encode
from app.agent.runtime import AgentRuntime, RuntimeResult
from app.api.dependencies import get_app_settings, get_current_user, get_repository
from app.core.runtime_config import apply_database_config
from app.core.config import Settings
from app.core.errors import APIError
from app.domain.models import Account, AgentRun, AgentTraceEvent, ChatSession, UserMessage
from app.domain.schemas import (
    AgentMessageRequest,
    GuideSuggestionItem,
    GuideSuggestionRequest,
    AgentRunOut,
    AgentTraceOut,
    AttachmentIn,
    ChatSessionDetailOut,
    ChatSessionOut,
    PageResponse,
    SessionCreateRequest,
    SessionPatchRequest,
    SessionPinRequest,
    UserMessageOut,
    UserMessageWithRunsOut,
)
from app.repositories.sql import SQLRepository
from app.integrations.image_search import ImageSearchService

router = APIRouter(prefix="/agent", tags=["agent"])


def _context_string(context: dict[str, Any], key: str) -> str:
    value = context.get(key, "")
    if isinstance(value, (dict, list)):
        return ""
    return "" if value is None else " ".join(str(value).strip().split())


def _context_int(context: dict[str, Any], key: str) -> int:
    value = context.get(key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _short_term(value: str, count: int) -> str:
    return "".join(value.split())[:count]


def _suggestions(request: GuideSuggestionRequest) -> list[GuideSuggestionItem]:
    page = request.page.strip()
    limit = min(max(request.limit if request.limit > 0 else 3, 1), 3)
    context = request.context or {}
    items: list[GuideSuggestionItem]
    if page == "products":
        items = []
        keyword = _short_term(_context_string(context, "keyword"), 8)
        category = _short_term(_context_string(context, "category_name"), 8)
        if keyword:
            items.append(GuideSuggestionItem(id="keyword_recommend", question=f"帮我选{keyword}", reason="根据当前搜索词生成可直接发送给导购的选购问题"))
        if category:
            items.append(GuideSuggestionItem(id="category_budget", question=f"{category}怎么选？", reason="根据当前分类引导用户补充预算和偏好"))
        items.extend([
            GuideSuggestionItem(id="compare_visible", question="比较当前商品", reason="用户可能正在浏览多个候选商品"),
            GuideSuggestionItem(id="budget_recommend", question="高性价比推荐", reason="泛选场景下给用户一个低门槛入口"),
        ])
    elif page == "cart":
        items = []
        count = _context_int(context, "cart_item_count")
        if count > 0:
            items.append(GuideSuggestionItem(id="cart_analyze", question=f"帮我分析这{count}件商品", reason="购物车内已有商品，适合做购买决策和优惠分析"))
        items.extend([
            GuideSuggestionItem(id="cart_worth", question="购物车哪些值得买？", reason="引导用户筛选购物车里的高价值商品"),
            GuideSuggestionItem(id="cart_checkout", question="现在适合直接下单吗？", reason="帮助用户确认优惠、库存和下单时机"),
            GuideSuggestionItem(id="cart_coupon", question="看看能省多少", reason="购物车页面常见诉求是优惠试算"),
        ])
    elif page == "orders":
        items = []
        if _context_int(context, "pending_payment_count") > 0:
            items.append(GuideSuggestionItem(id="pending_payment", question="哪些订单还没支付？", reason="当前存在待支付订单"))
        if _context_int(context, "pending_review_count") > 0:
            items.append(GuideSuggestionItem(id="pending_review", question="待评价怎么写？", reason="当前存在可评价订单"))
        items.extend([
            GuideSuggestionItem(id="order_summary", question="总结订单状态", reason="订单页适合聚合物流、支付和售后状态"),
            GuideSuggestionItem(id="order_action", question="哪些订单待办？", reason="帮助用户快速定位待办订单"),
        ])
    elif page == "product_detail":
        items = []
        name = _short_term(_context_string(context, "product_name"), 10)
        if name:
            items.append(GuideSuggestionItem(id="product_worth", question=f"{name}值得买吗？", reason="商品详情页最常见的决策问题"))
        items.extend([
            GuideSuggestionItem(id="product_fit", question="这个商品适合我吗？", reason="引导用户结合自身场景判断适配性"),
            GuideSuggestionItem(id="product_risk", question="这个商品有什么缺点？", reason="帮助用户了解风险和避坑点"),
            GuideSuggestionItem(id="product_compare", question="同类里它值得买吗？", reason="详情页常见横向对比诉求"),
        ])
    else:
        raise APIError(400, "bad_page", "向导建议请求参数不合法")
    output: list[GuideSuggestionItem] = []
    seen: set[str] = set()
    for item in items:
        item.question = item.question.strip()[:10]
        if item.id and item.question and item.question not in seen:
            seen.add(item.question)
            output.append(item)
        if len(output) >= limit:
            break
    return output


@router.post("/guide-suggestions")
async def guide_suggestions(request: GuideSuggestionRequest, account: Account = Depends(get_current_user)) -> dict[str, list[GuideSuggestionItem]]:
    del account
    return {"items": _suggestions(request)}


async def normalize_attachments(account: Account, request_attachments: list[AttachmentIn], repository: SQLRepository) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for attachment in request_attachments:
        item = attachment.model_dump(exclude_none=True)
        item["type"] = str(item.get("type") or "image").lower()
        raw_url = str(item.get("url") or "")
        file_id = str(item.get("file_id") or "") or ImageSearchService.file_id_from_url(raw_url)
        if file_id:
            stored = await repository.get_stored_file(account.account_id, file_id, is_admin=account.role == "admin")
            if stored is None:
                raise APIError(404, "file_not_found", "附件文件不存在")
            item["file_id"] = stored.file_id
            item["url"] = stored.url
            item["object_key"] = stored.object_key
        normalized.append(item)
    return normalized


def session_out(item: ChatSession) -> ChatSessionOut:
    return ChatSessionOut(
        session_id=item.session_id, account_id=item.account_id, title=item.title, summary=item.summary or None,
        message_count=item.message_count, last_message_at=item.last_message_at, pinned_at=item.pinned_at,
        deleted_at=item.deleted_at, created_at=item.created_at, updated_at=item.updated_at,
    )


def message_out(item: UserMessage) -> UserMessageOut:
    attachments = [AttachmentIn(**attachment) for attachment in (item.attachments_json or [])]
    return UserMessageOut(
        message_id=item.message_id, session_id=item.session_id, account_id=item.account_id,
        client_message_id=item.client_message_id, content=item.content, attachments=attachments, created_at=item.created_at,
    )


def run_out(item: AgentRun) -> AgentRunOut:
    return AgentRunOut(
        run_id=item.run_id, session_id=item.session_id, message_id=item.message_id, account_id=item.account_id,
        status=item.status, trace_id=item.trace_id, created_at=item.created_at, updated_at=item.updated_at,
        content=item.content or "", blocks=item.blocks_json or [], followups=item.followups_json or [], segments=item.segments_json or [],
    )


def trace_out(item: AgentTraceEvent) -> AgentTraceOut:
    return AgentTraceOut(
        trace_event_id=item.trace_event_id, run_id=item.run_id, trace_id=item.trace_id, account_id=item.account_id,
        stage=item.stage, event_type=item.event_type, model=item.model or None, status=item.status,
        duration_ms=item.duration_ms, error=item.error or None,
        metadata_json=json.dumps(item.metadata_json or {}, ensure_ascii=False), created_at=item.created_at,
    )


@router.get("/sessions", response_model=PageResponse[ChatSessionOut], response_model_exclude_none=True)
async def list_sessions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
) -> PageResponse[ChatSessionOut]:
    items, total = await repository.list_sessions(account.account_id, page, page_size)
    return PageResponse(items=[session_out(item) for item in items], page=page, page_size=page_size, total=total)


@router.get("/sessions/search", response_model=PageResponse[ChatSessionOut], response_model_exclude_none=True)
async def search_sessions(
    q: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
) -> PageResponse[ChatSessionOut]:
    items, total = await repository.search_sessions(account.account_id, q, page, page_size)
    return PageResponse(items=[session_out(item) for item in items], page=page, page_size=page_size, total=total)


@router.post("/sessions", response_model=ChatSessionOut, response_model_exclude_none=True)
async def create_session(
    request: SessionCreateRequest | None = None,
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
) -> ChatSessionOut:
    item = await repository.create_session(account.account_id, (request.title if request else "AI 导购"))
    return session_out(item)


@router.post("/sessions/{session_id}/messages:stream")
async def stream_message(
    session_id: str,
    request: AgentMessageRequest,
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> StreamingResponse:
    if not request.content.strip():
        raise APIError(400, "empty_content", "消息内容不能为空")
    session = await repository.get_session(account.account_id, session_id)
    if session is None:
        raise APIError(404, "session_not_found", "会话不存在")
    attachments = await normalize_attachments(account, request.attachments, repository)
    message, message_created = await repository.create_user_message(account.account_id, session_id, request.client_message_id, request.content, attachments)
    run, run_created = await repository.create_run(account.account_id, session_id, message.message_id)
    if not message_created or not run_created:
        async def duplicate_stream() -> AsyncIterator[str]:
            yield sse_encode(event("message_start", run.run_id, session_id=run.session_id, user_message_id=message.message_id, trace_id=run.trace_id))
            yield sse_encode(event("error", run.run_id, code="duplicate_message", message="请求已提交过，已返回已有执行记录"))
            yield sse_encode(event("message_end", run.run_id))
        return StreamingResponse(duplicate_stream(), media_type="text/event-stream")

    settings = apply_database_config(settings, await repository.config_values())
    runtime = AgentRuntime(settings)

    async def stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        runtime_result: RuntimeResult | None = None
        runtime_error: Exception | None = None

        async def emit(payload: dict[str, Any]) -> None:
            await queue.put(payload)

        async def worker() -> None:
            nonlocal runtime_result, runtime_error
            try:
                runtime_result = await runtime.run(repository, run, message, emit)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # pragma: no cover - exercised with dependency failures
                # The stream worker is the final task boundary: keep the SSE
                # protocol well-formed and persist the failure instead of
                # leaving a running AgentRun when an unexpected dependency
                # exception escapes the runtime.
                import logging
                logging.getLogger("xzxg.agent").exception("agent stream worker failed", extra={"run_id": run.run_id})
                runtime_error = error
            finally:
                await queue.put(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                payload = await queue.get()
                if payload is None:
                    break
                yield sse_encode(payload)
            await task
            if runtime_error is not None:
                await repository.update_run_status(account.account_id, run.run_id, "failed")
                yield sse_encode(event("error", run.run_id, code="agent_failed", message="Agent 暂时无法完成请求"))
            elif runtime_result is not None:
                await repository.update_run_result(account.account_id, run.run_id, runtime_result.content, runtime_result.blocks, runtime_result.followups, runtime_result.segments)
        except asyncio.CancelledError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await repository.update_run_status(account.account_id, run.run_id, "canceled")
            raise

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailOut, response_model_exclude_none=True)
async def session_detail(
    session_id: str,
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
) -> ChatSessionDetailOut:
    detail = await repository.list_session_detail(account.account_id, session_id)
    if detail is None:
        raise APIError(404, "session_not_found", "会话不存在")
    session, messages = detail
    return ChatSessionDetailOut(session=session_out(session), messages=[UserMessageWithRunsOut(**message_out(message).model_dump(), runs=[run_out(run) for run in runs]) for message, runs in messages])


@router.patch("/sessions/{session_id}", response_model=ChatSessionOut, response_model_exclude_none=True)
async def patch_session(
    session_id: str,
    request: SessionPatchRequest,
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
) -> ChatSessionOut:
    item = await repository.update_session(account.account_id, session_id, request.title, request.summary)
    if item is None:
        raise APIError(404, "session_not_found", "会话不存在")
    return session_out(item)


@router.post("/sessions/{session_id}:pin", response_model=ChatSessionOut, response_model_exclude_none=True)
async def pin_session(
    session_id: str,
    request: SessionPinRequest,
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
) -> ChatSessionOut:
    item = await repository.pin_session(account.account_id, session_id, request.pinned)
    if item is None:
        raise APIError(404, "session_not_found", "会话不存在")
    return session_out(item)


@router.post("/sessions/{session_id}:summarize", response_model=ChatSessionOut, response_model_exclude_none=True)
async def summarize_session(
    session_id: str,
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
) -> ChatSessionOut:
    detail = await repository.list_session_detail(account.account_id, session_id)
    if detail is None:
        raise APIError(404, "session_not_found", "会话不存在")
    session, messages = detail
    texts = [message.content.strip() for message, _runs in messages if message.content.strip()][:3]
    summary = "；".join(texts)[:500] or session.summary
    title = texts[0][:128] if texts else session.title
    item = await repository.update_session(account.account_id, session_id, title, summary)
    if item is None:
        raise APIError(404, "session_not_found", "会话不存在")
    return session_out(item)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
) -> dict[str, str]:
    if not await repository.delete_session(account.account_id, session_id):
        raise APIError(404, "session_not_found", "会话不存在")
    return {"session_id": session_id, "status": "deleted"}


@router.post("/runs/{run_id}:cancel")
async def cancel_run(
    run_id: str,
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
) -> dict[str, str]:
    item = await repository.update_run_status(account.account_id, run_id, "canceled")
    if item is None:
        raise APIError(404, "run_not_found", "执行不存在")
    return {"run_id": item.run_id, "status": item.status}


@router.get("/runs/{run_id}/trace", response_model=dict[str, list[AgentTraceOut]], response_model_exclude_none=True)
async def run_trace(
    run_id: str,
    account: Account = Depends(get_current_user),
    repository: SQLRepository = Depends(get_repository),
) -> dict[str, list[AgentTraceOut]]:
    if await repository.get_run(account.account_id, run_id) is None:
        raise APIError(404, "run_not_found", "执行不存在")
    return {"items": [trace_out(item) for item in await repository.list_trace(account.account_id, run_id)]}
