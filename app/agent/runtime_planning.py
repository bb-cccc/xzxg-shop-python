from __future__ import annotations

 

import json
import re

from app.agent.planner import Plan
from app.integrations.llm import LLMUnavailable



# 能力混入类，把这一领域的操作组合到主类中。
class AgentPlanningMixin:
    async def _answer_with_optional_llm(self, query: str, plan: Plan, tool_result: str, fallback: str) -> tuple[str, str]:
        if not self.llm.enabled:
            return (fallback, 'fallback')
        messages = [{'role': 'system', 'content': '你是受控电商导购。只基于提供的工具结果回答，不编造商品、价格、库存或订单。'}, {'role': 'user', 'content': f'route={plan.route}; intent={plan.intent}\n用户问题：{query}\n工具结果：{tool_result}'}]
        try:
            content = (await self.llm.complete(messages, model=self.settings.ai_large_model)).strip()
            allowed_product_ids = set(re.findall('\\bp_[A-Za-z0-9_]+\\b', tool_result))
            if content and (not allowed_product_ids or any((product_id in content for product_id in allowed_product_ids))):
                return (content, self.settings.ai_large_model or 'llm')
        except LLMUnavailable:
            pass
        return (fallback, 'fallback')

    async def _classify_plan(self, query: str) -> tuple[Plan, str]:
        """Use the configured model for routing when available, with a strict rule fallback."""
        fallback = self.planner.classify(query)
        if not self.llm.enabled:
            return (fallback, 'fallback')
        messages = [{'role': 'system', 'content': '你是电商服务意图分类器，只输出 JSON。route 只能是 guide 或 non_guide；intent 只能是 guide_intent、open_explore、image_search、cart_add、cart_update、cart_delete、cart_service、order_service、coupon_service、review_service、after_sales_service、account_service、navigation_service、chitchat。'}, {'role': 'user', 'content': f'用户问题：{query}\n输出 {{"route":"guide|non_guide","intent":"...","level":"","secondary_level":"","reason":""}}'}]
        allowed = {'guide_intent', 'open_explore', 'image_search', 'cart_add', 'cart_update', 'cart_delete', 'cart_service', 'order_service', 'coupon_service', 'review_service', 'after_sales_service', 'account_service', 'navigation_service', 'chitchat'}
        try:
            raw = await self.llm.complete(messages, model=self.settings.ai_small_model or self.settings.ai_large_model, temperature=0.1)
            match = re.search('\\{.*\\}', raw, re.DOTALL)
            payload = json.loads(match.group(0) if match else raw)
            route = str(payload.get('route') or '').strip()
            intent = str(payload.get('intent') or '').strip()
            if route not in {'guide', 'non_guide'} or intent not in allowed:
                return (fallback, 'fallback')
            return (Plan(route, intent, str(payload.get('reason') or 'model classification'), str(payload.get('level') or ''), str(payload.get('secondary_level') or '')), self.settings.ai_small_model or 'llm')
        except (LLMUnavailable, json.JSONDecodeError, AttributeError, TypeError, KeyError):
            return (fallback, 'fallback')
