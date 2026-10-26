from __future__ import annotations

 

import logging
import re
from typing import Any

from app.agent.output import event
from app.agent.planner import IntentPlanner
from app.agent.runtime_models import Emit, RuntimeResult
from app.agent.runtime_planning import AgentPlanningMixin
from app.agent.runtime_react import AgentReactMixin
from app.agent.tools import ToolRegistry
from app.core.config import Settings
from app.domain.models import Account, AgentRun, UserMessage
from app.integrations.llm import LLMClient
from app.repositories.sql import SQLRepository

PRODUCT_ID_RE = re.compile(r"\bp_[A-Za-z0-9_]+\b")
CART_ITEM_ID_RE = re.compile(r"\bci_[A-Za-z0-9_]+\b")


class AgentRuntime(AgentPlanningMixin, AgentReactMixin):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.planner = IntentPlanner()
        self.llm = LLMClient(settings)
        self.logger = logging.getLogger('xzxg.agent')

    @staticmethod
    def _safe_model_trace(raw: str) -> str:
        value = str(raw or '')
        value = re.sub('(?i)(api[_-]?key|authorization|token|secret)\\s*[:=]\\s*[\'\\"]?[^\\s,\'\\"]+', '\\1=[REDACTED]', value)
        return value[:8000]

    async def _trace(self, repository: SQLRepository, run: AgentRun, stage: str, event_type: str, *, status: str='ok', model: str='', error: str='', metadata: dict[str, Any] | None=None) -> None:
        await repository.record_trace(run.run_id, run.trace_id, run.account_id, stage, event_type, status, model, 0, error, metadata)

    async def _emit_status(self, repository: SQLRepository, run: AgentRun, emit: Emit, stage: str, text: str) -> None:
        await self._trace(repository, run, stage, 'status', metadata={'text': text})
        await emit(event('status', run.run_id, stage=stage, text=text))
        step = {'id': stage, 'title': {'intent': '分析用户需求', 'retrieval': '查找相关商品和资料', 'tool': '执行购物操作', 'answer': '整理回答'}.get(stage, '处理请求'), 'status': 'running', 'order': {'intent': 1, 'retrieval': 2, 'tool': 2, 'answer': 3}.get(stage, 1)}
        await emit(event('thinking_delta', run.run_id, step=step))

    async def _canceled(self, repository: SQLRepository, run: AgentRun, emit: Emit) -> bool:
        if await repository.is_run_canceled(run.run_id):
            await emit(event('error', run.run_id, code='canceled', message='已停止生成'))
            return True
        return False

    @staticmethod
    def _extract_product_ids(content: str) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in PRODUCT_ID_RE.findall(content):
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    @staticmethod
    def _extract_cart_item_ids(content: str) -> list[str]:
        return list(dict.fromkeys(CART_ITEM_ID_RE.findall(content)))

    @staticmethod
    def _split_text(content: str, size: int=28) -> list[str]:
        return [content[index:index + size] for index in range(0, len(content), size)] or ['']

    async def _emit_text(self, run: AgentRun, emit: Emit, content: str, result: RuntimeResult) -> None:
        result.content += content
        result.segments.append({'type': 'text', 'text': content})
        for delta in self._split_text(content):
            await emit(event('text_delta', run.run_id, delta=delta))

    async def run(self, repository: SQLRepository, run: AgentRun, message: UserMessage, emit: Emit) -> RuntimeResult:
        result = RuntimeResult()
        await self._trace(repository, run, 'run', 'start', metadata={'session_id': run.session_id, 'message_id': message.message_id})
        await emit(event('message_start', run.run_id, session_id=run.session_id, user_message_id=message.message_id, trace_id=run.trace_id))
        config_values = await repository.config_values()
        risk_enabled = str(config_values.get('risk.enabled', 'true')).strip().lower() not in {'0', 'false', 'no', 'off'}
        blocked_terms = ('支付密码', '银行卡密码', '绕过风控', '违法', '违禁', '假货')
        block_code = 'unsafe_request'
        block_message = '这个请求涉及敏感操作，我不能协助绕过安全控制。'
        if risk_enabled and any((term in message.content for term in blocked_terms)):
            pass
        else:
            account = await repository.session.get(Account, run.account_id)
            if risk_enabled and account is not None and (account.status.strip().lower() == 'risk'):
                block_code = 'risk_account'
                block_message = config_values.get('risk.account_message', '').strip() or '当前账号命中平台风控限制，暂时无法继续使用导购 Agent。'
            else:
                block_code = ''
        if block_code:
            result.blocks.append({'type': 'warning', 'code': block_code, 'message': block_message})
            await self._emit_text(run, emit, block_message, result)
            await emit(event('block_delta', run.run_id, block=result.blocks[-1]))
            await repository.update_run_status(run.account_id, run.run_id, 'completed')
            await self._trace(repository, run, 'risk', 'blocked', status='blocked')
            await emit(event('message_end', run.run_id))
            return result
        await self._emit_status(repository, run, emit, 'intent', '正在理解你的需求')
        if await self._canceled(repository, run, emit):
            result.status = 'canceled'
            return result
        plan, planner_model = await self._classify_plan(message.content)
        await self._trace(repository, run, 'planner', 'selected', model=planner_model, metadata={'route': plan.route, 'intent': plan.intent, 'level': plan.level, 'secondary_level': plan.secondary_level, 'reason': plan.reason})
        tools = ToolRegistry(repository, self.settings)
        react_result = await self._run_react(repository, run, message, plan, tools, emit)
        if react_result is not None:
            await emit(event('thinking_delta', run.run_id, step={'id': 'answer', 'title': '总结答案', 'status': 'done', 'order': 3}))
            await repository.update_run_status(run.account_id, run.run_id, 'completed')
            await self._trace(repository, run, 'run', 'completed')
            await emit(event('message_end', run.run_id))
            return react_result
        allowed_product_ids: set[str] = set()
        tool_text = ''
        if plan.intent == 'image_search' and message.attachments_json:
            await self._emit_status(repository, run, emit, 'retrieval', '正在按图片查找相似商品')
            tool_result = await tools.search_image_products(run.account_id, self.settings, message.attachments_json)
            await self._trace(repository, run, 'retrieval', 'image_search', status='ok' if tool_result.ok else 'no_match', metadata={'product_ids': tool_result.product_ids, 'provider': tool_result.result.get('provider', ''), 'match_status': tool_result.result.get('match_status', '')})
            for block in tool_result.blocks:
                result.blocks.append(block)
                await emit(event('block_delta', run.run_id, block=block))
            if tool_result.ok:
                answer = f'我按图片找到 {len(tool_result.product_ids)} 个相似商品，你可以继续告诉我预算或使用场景。'
                result.followups = ['比较这些候选', '按预算筛选']
                await emit(event('followups', run.run_id, questions=result.followups))
            else:
                warning = {'type': 'warning', 'code': 'image_search_unavailable', 'message': tool_result.message}
                if not result.blocks or result.blocks[-1].get('type') != 'warning':
                    result.blocks.append(warning)
                    await emit(event('block_delta', run.run_id, block=warning))
                answer = tool_result.message
            await self._emit_text(run, emit, answer, result)
        elif plan.intent == 'image_search':
            await self._emit_status(repository, run, emit, 'retrieval', '正在检查图片附件')
            warning = {'type': 'warning', 'code': 'image_required', 'message': '请先上传一张商品图片，我再帮你找相似商品。'}
            result.blocks.append(warning)
            await emit(event('block_delta', run.run_id, block=warning))
            await self._emit_text(run, emit, warning['message'], result)
        elif plan.intent == 'cart_add':
            previous = await repository.last_product_ids(run.account_id, run.session_id)
            explicit = self._extract_product_ids(message.content)
            allowed_product_ids = set(previous + explicit)
            product_id = explicit[0] if explicit else previous[0] if previous else ''
            await self._emit_status(repository, run, emit, 'tool', '正在加入购物车')
            tool_result = await tools.add_cart_item(run.account_id, product_id, allowed_product_ids)
            await self._trace(repository, run, 'tool', 'add_cart_item', status='ok' if tool_result.ok else 'failed', metadata={'product_id': product_id})
            tool_text = tool_result.message or '购物车已更新'
            if tool_result.ok:
                result.blocks.extend(tool_result.blocks)
                answer = f'{tool_text}。'
            else:
                result.blocks.append({'type': 'warning', 'code': 'need_clarification', 'message': tool_text})
                answer = tool_text
            for block in tool_result.blocks:
                await emit(event('block_delta', run.run_id, block=block))
            if not tool_result.ok:
                await emit(event('block_delta', run.run_id, block=result.blocks[-1]))
            await self._emit_text(run, emit, answer, result)
        elif plan.intent in {'cart_update', 'cart_delete'}:
            ids = self._extract_cart_item_ids(message.content)
            if not ids:
                cart_result = await tools.get_cart(run.account_id)
                rows = cart_result.result.get('cart', {}).get('items', []) if isinstance(cart_result.result.get('cart'), dict) else []
                if rows and isinstance(rows[0], dict) and rows[0].get('cartItemId'):
                    ids = [str(rows[0]['cartItemId'])]
            if plan.intent == 'cart_update':
                quantity_match = re.search('(?:改成|数量|增加|减少)\\s*(\\d+)', message.content)
                quantity = int(quantity_match.group(1)) if quantity_match else None
                await self._emit_status(repository, run, emit, 'tool', '正在更新购物车')
                tool_result = await tools.update_cart_item(run.account_id, ids[0] if ids else '', quantity=quantity)
                tool_name = 'update_cart_item'
            else:
                await self._emit_status(repository, run, emit, 'tool', '正在移除购物车商品')
                tool_result = await tools.delete_cart_item(run.account_id, ids[0] if ids else '')
                tool_name = 'delete_cart_item'
            for block in tool_result.blocks:
                result.blocks.append(block)
                await emit(event('block_delta', run.run_id, block=block))
            answer = tool_result.message
            if not tool_result.ok:
                warning = {'type': 'warning', 'code': f'{tool_name}_failed', 'message': answer}
                result.blocks.append(warning)
                await emit(event('block_delta', run.run_id, block=warning))
            await self._trace(repository, run, 'tool', tool_name, status='ok' if tool_result.ok else 'failed', metadata={'cart_item_id': ids[0] if ids else ''})
            await self._emit_text(run, emit, answer, result)
        elif plan.intent == 'coupon_service':
            await self._emit_status(repository, run, emit, 'tool', '正在查询优惠')
            tool_result = await tools.list_coupons(run.account_id)
            for block in tool_result.blocks:
                result.blocks.append(block)
                await emit(event('block_delta', run.run_id, block=block))
            answer = '这是当前可用的优惠券和优惠活动。' if tool_result.result.get('items') else '当前没有可用优惠券。'
            await self._trace(repository, run, 'tool', 'list_coupons', status='ok')
            await self._emit_text(run, emit, answer, result)
        elif plan.intent == 'review_service':
            await self._emit_status(repository, run, emit, 'retrieval', '正在查找评价信息')
            tool_result = await tools.search_knowledge(message.content)
            for block in tool_result.blocks:
                result.blocks.append(block)
                await emit(event('block_delta', run.run_id, block=block))
            answer = '我找到了相关评价资料，请查看引用内容。' if tool_result.ok else '当前没有找到相关评价资料。'
            await self._trace(repository, run, 'retrieval', 'reviews', status='ok' if tool_result.ok else 'no_match')
            await self._emit_text(run, emit, answer, result)
        elif plan.intent == 'navigation_service':
            target = 'cart' if '购物车' in message.content else 'orders' if '订单' in message.content else 'products'
            label = {'cart': '打开购物车', 'orders': '查看订单', 'products': '打开商品页'}[target]
            block = {'type': 'action', 'message': f'可以去{label}查看。', 'action': {'name': 'navigate', 'target': target, 'label': label}}
            result.blocks.append(block)
            await emit(event('block_delta', run.run_id, block=block))
            await self._emit_text(run, emit, block['message'], result)
        elif plan.intent == 'account_service':
            block = {'type': 'action', 'message': '可以在个人资料页查看和修改账号信息。', 'action': {'name': 'navigate', 'target': 'account', 'label': '打开个人资料'}}
            result.blocks.append(block)
            await emit(event('block_delta', run.run_id, block=block))
            await self._emit_text(run, emit, block['message'], result)
        elif plan.intent == 'order_service':
            if any((term in message.content for term in ('下单', '结算', '去支付', '买下来'))):
                await self._emit_status(repository, run, emit, 'tool', '正在结算购物车')
                tool_result = await tools.checkout(run.account_id)
                answer = '已创建待支付订单，请确认订单后完成支付。' if tool_result.ok else tool_result.message
            else:
                await self._emit_status(repository, run, emit, 'tool', '正在查询订单')
                tool_result = await tools.list_orders(run.account_id)
                answer = '这是你最近的订单信息。' if tool_result.ok else tool_result.message
            for block in tool_result.blocks:
                result.blocks.append(block)
                await emit(event('block_delta', run.run_id, block=block))
            await self._trace(repository, run, 'tool', tool_result.tool, status='ok' if tool_result.ok else 'failed')
            await self._emit_text(run, emit, answer, result)
        elif plan.intent == 'cart_service':
            await self._emit_status(repository, run, emit, 'tool', '正在查看购物车')
            tool_result = await tools.get_cart(run.account_id)
            await self._trace(repository, run, 'tool', 'get_cart', status='ok')
            for block in tool_result.blocks:
                result.blocks.append(block)
                await emit(event('block_delta', run.run_id, block=block))
            await self._emit_text(run, emit, '这是你当前的购物车，我可以继续帮你分析或结算。', result)
        elif plan.intent == 'after_sales_service':
            await self._emit_status(repository, run, emit, 'retrieval', '正在查找商品资料')
            tool_result = await tools.search_knowledge(message.content)
            await self._trace(repository, run, 'retrieval', 'knowledge', status='ok' if tool_result.ok else 'no_match', metadata={'chunk_ids': tool_result.chunk_ids, 'trace': tool_result.result.get('trace', {})})
            for block in tool_result.blocks:
                result.blocks.append(block)
                await emit(event('block_delta', run.run_id, block=block))
            answer = '我找到了相关资料，请结合引用内容查看。' if tool_result.ok else '当前资料库没有找到相关内容，我可以继续根据具体商品帮你确认。'
            await self._emit_text(run, emit, answer, result)
        elif plan.route == 'guide':
            await self._emit_status(repository, run, emit, 'retrieval', '正在查找合适商品')
            tool_result = await tools.search_products(message.content)
            allowed_product_ids = set(tool_result.product_ids)
            await self._trace(repository, run, 'retrieval', 'products', status='ok' if tool_result.ok else 'no_match', metadata={'product_ids': tool_result.product_ids, 'query': tool_result.result.get('query', '')})
            if tool_result.ok and tool_result.product_ids:
                block = {'type': 'product_refs', 'product_ids': tool_result.product_ids}
                result.blocks.append(block)
                await emit(event('block_delta', run.run_id, block=block))
                fallback = f'我先找到 {len(tool_result.product_ids)} 个候选商品。你可以告诉我更看重预算、性能还是使用场景，我再继续帮你筛选。'
                answer, model = await self._answer_with_optional_llm(message.content, plan, str(tool_result.result), fallback)
                await self._trace(repository, run, 'answer', 'generated', model=model, status='ok' if model != 'fallback' else 'fallback')
            else:
                answer = '当前商品库暂时没有找到匹配商品，你可以换一个品类、品牌或使用场景描述。'
                await self._trace(repository, run, 'answer', 'generated', model='fallback', status='fallback')
            await self._emit_text(run, emit, answer, result)
            result.followups = ['按预算帮我筛选', '比较前两个候选']
            await emit(event('followups', run.run_id, questions=result.followups))
        else:
            answer = '你好，我可以帮你搜索商品、比较候选、查看购物车并协助结算。'
            await self._emit_text(run, emit, answer, result)
        if await self._canceled(repository, run, emit):
            result.status = 'canceled'
            return result
        await emit(event('thinking_delta', run.run_id, step={'id': 'answer', 'title': '总结答案', 'status': 'done', 'order': 3}))
        await repository.update_run_status(run.account_id, run.run_id, 'completed')
        await self._trace(repository, run, 'run', 'completed')
        await emit(event('message_end', run.run_id))
        return result
