from __future__ import annotations

 

import json
import time
from typing import Any

from app.agent.output import event
from app.agent.planner import Plan
from app.agent.policy import allowed_tools, tool_prompt
from app.agent.react_protocol import parse_model_output, validate_tool_arguments
from app.agent.tools import ToolRegistry
from app.agent.runtime_models import Emit, RuntimeResult
from app.domain.models import AgentRun, UserMessage
from app.integrations.llm import LLMUnavailable
from app.repositories.sql import SQLRepository



# 能力混入类，把这一领域的操作组合到主类中。
class AgentReactMixin:
    async def _react_system_prompt(self, repository: SQLRepository, plan: Plan) -> str:
        prompt = await repository.get_active_prompt('agent.prompt.main_template')
        protocol = await repository.get_active_prompt('agent.prompt.tool_call_protocol')
        rules = await repository.get_active_prompt('agent.prompt.final_output_rules')
        intent_prompt = await repository.get_active_prompt(f'agent.prompt.intent.{plan.intent}')
        parts = [prompt.content if prompt else '你是受控电商导购，只能基于工具结果回答，不得编造商品、价格、库存或订单。', protocol.content if protocol else '需要工具时输出 JSON：{"type":"tool_call","tool":"工具名","arguments":{}}；完成时输出 <final>回答</final>。', rules.content if rules else '商品 ID 必须来自工具结果，资料结论必须有知识引用。', intent_prompt.content if intent_prompt else '', tool_prompt(plan), f'当前 route={plan.route}，intent={plan.intent}。最多连续调用 6 次工具。']
        return '\n\n'.join((item.strip() for item in parts if item and item.strip()))

    async def _execute_react_tool(self, tools: ToolRegistry, account_id: str, tool: str, arguments: dict[str, Any], attachments: list[dict[str, object]], allowed_product_ids: set[str]) -> Any:
        if tool == 'search_products':
            query = str(arguments.get('query') or '').strip()
            return await tools.search_products(query, int(arguments.get('limit') or 5), arguments)
        if tool == 'search_knowledge':
            return await tools.search_knowledge(str(arguments.get('query') or ''), int(arguments.get('limit') or 5))
        if tool == 'search_image_products':
            return await tools.search_image_products(account_id, self.settings, attachments, int(arguments.get('limit') or 5))
        if tool == 'get_cart':
            return await tools.get_cart(account_id)
        if tool == 'add_cart_item':
            return await tools.add_cart_item(account_id, str(arguments.get('product_id') or ''), allowed_product_ids, str(arguments.get('sku_id') or ''), int(arguments.get('quantity') or 1))
        if tool == 'update_cart_item':
            return await tools.update_cart_item(account_id, str(arguments.get('cart_item_id') or ''), arguments.get('quantity'), arguments.get('selected'))
        if tool == 'delete_cart_item':
            return await tools.delete_cart_item(account_id, str(arguments.get('cart_item_id') or ''))
        if tool == 'preview_discount':
            return await tools.preview_discount(account_id)
        if tool == 'checkout':
            return await tools.checkout(account_id)
        if tool == 'list_orders':
            return await tools.list_orders(account_id, int(arguments.get('limit') or 5))
        if tool == 'get_order':
            return await tools.get_order(account_id, str(arguments.get('order_id') or ''))
        if tool == 'pay_order':
            return await tools.pay_order(account_id, str(arguments.get('order_id') or ''), str(arguments.get('method') or 'mock_balance'))
        if tool == 'cancel_order':
            return await tools.cancel_order(account_id, str(arguments.get('order_id') or ''), str(arguments.get('reason') or ''))
        if tool == 'confirm_receipt':
            return await tools.confirm_receipt(account_id, str(arguments.get('order_id') or ''))
        if tool == 'list_coupons':
            return await tools.list_coupons(account_id, int(arguments.get('limit') or 5))
        if tool == 'list_user_coupons':
            return await tools.list_user_coupons(account_id, int(arguments.get('limit') or 5))
        if tool == 'claim_coupon':
            return await tools.claim_coupon(account_id, str(arguments.get('coupon_id') or ''))
        if tool == 'list_reviews':
            return await tools.list_reviews(str(arguments.get('product_id') or ''), int(arguments.get('limit') or 5))
        return None

    async def _run_react(self, repository: SQLRepository, run: AgentRun, message: UserMessage, plan: Plan, tools: ToolRegistry, emit: Emit) -> RuntimeResult | None:
        if not self.llm.enabled:
            return None
        permitted = allowed_tools(plan)
        if not permitted:
            return None
        result = RuntimeResult()
        messages: list[dict[str, str]] = [{'role': 'system', 'content': await self._react_system_prompt(repository, plan)}, {'role': 'user', 'content': f'用户问题：{message.content}\n只在信息足够时输出 <final>...</final>。'}]
        attachments = list(message.attachments_json or [])
        product_ids: list[str] = []
        chunk_ids: list[str] = []
        previous_calls: list[str] = []
        for step in range(1, 7):
            if await self._canceled(repository, run, emit):
                result.status = 'canceled'
                return result
            started = time.perf_counter()
            try:
                parts: list[str] = []
                async for delta in self.llm.stream(messages, model=self.settings.ai_large_model or self.settings.ai_small_model, temperature=0.2):
                    parts.append(delta)
                raw = ''.join(parts)
            except LLMUnavailable:
                return None
            await self._trace(repository, run, f'react.step.{step}', 'decision', model=self.settings.ai_large_model or self.settings.ai_small_model, metadata={'raw_output': self._safe_model_trace(raw), 'step': step, 'duration_ms': int((time.perf_counter() - started) * 1000)})
            action = parse_model_output(raw)
            if action.kind == 'final':
                if plan.route == 'guide' and 'search_products' in permitted and (not product_ids):
                    messages.extend([{'role': 'assistant', 'content': raw}, {'role': 'user', 'content': '你还没有执行真实商品工具，不能直接给出商品答案。请严格输出 search_products 的 tool_call JSON，等待 Observation 后再回答。'}])
                    continue
                await self._emit_text(run, emit, action.content, result)
                result.blocks.append({'type': 'product_refs', 'product_ids': product_ids}) if product_ids else None
                result.blocks.append({'type': 'citations', 'chunk_ids': chunk_ids}) if chunk_ids else None
                for block in result.blocks:
                    await emit(event('block_delta', run.run_id, block=block))
                return result
            if action.kind != 'tool':
                messages.extend([{'role': 'assistant', 'content': raw}, {'role': 'user', 'content': '协议错误。请严格输出 tool_call JSON 或 <final>回答</final>。'}])
                continue
            tool = action.tool
            valid_arguments, arguments = validate_tool_arguments(tool, action.arguments)
            if not valid_arguments:
                messages.extend([{'role': 'assistant', 'content': raw}, {'role': 'user', 'content': '工具参数不符合协议。请按工具定义重新输出 JSON，或输出 <final>。'}])
                await self._trace(repository, run, 'tool', tool or 'invalid', status='failed', error='invalid_arguments')
                continue
            if tool not in permitted:
                messages.extend([{'role': 'assistant', 'content': raw}, {'role': 'user', 'content': f"工具 {tool or '空'} 不在允许列表中，请重新选择或输出 <final>。"}])
                continue
            await self._emit_status(repository, run, emit, 'tool', f'正在执行 {tool}')
            call_signature = f'{tool}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}'
            previous_calls.append(call_signature)
            if len(previous_calls) >= 3 and previous_calls[-1] == previous_calls[-2] == previous_calls[-3]:
                messages.append({'role': 'user', 'content': '你已经连续三次重复同一工具调用。请停止调用并输出当前能力边界或最终答案。'})
                continue
            try:
                observation = await self._execute_react_tool(tools, run.account_id, tool, arguments, attachments, set(product_ids))
            except (OSError, RuntimeError, ValueError, TypeError, SQLAlchemyError) as error:
                self.logger.exception('ReAct tool failed', extra={'tool': tool, 'run_id': run.run_id})
                await self._trace(repository, run, 'tool', tool, status='failed', error=type(error).__name__, metadata={'arguments': arguments})
                messages.extend([{'role': 'assistant', 'content': raw}, {'role': 'user', 'content': f'工具 {tool} 执行失败，请不要重复调用，改用其他允许工具或输出能力边界说明。'}])
                continue
            if observation is None:
                messages.append({'role': 'user', 'content': '工具执行失败，请改用允许的工具或输出能力边界说明。'})
                continue
            product_ids.extend((item for item in observation.product_ids if item not in product_ids))
            chunk_ids.extend((item for item in observation.chunk_ids if item not in chunk_ids))
            for block in observation.blocks:
                result.blocks.append(block)
                await emit(event('block_delta', run.run_id, block=block))
            await self._trace(repository, run, 'tool', tool, status='ok' if observation.ok else 'failed', metadata={'arguments': arguments, 'result': observation.result, 'message': observation.message})
            messages.extend([{'role': 'assistant', 'content': raw}, {'role': 'user', 'content': 'Observation:\n' + json.dumps({'ok': observation.ok, 'message': observation.message, 'result': observation.result}, ensure_ascii=False) + '\n继续，必要时调用工具，否则输出 <final>回答</final>。'}])
        if plan.route == 'guide' and 'search_products' in permitted and (not product_ids):
            return None
        await self._emit_text(run, emit, '我已根据当前可用信息完成查询。', result)
        return result
