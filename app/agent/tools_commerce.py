from __future__ import annotations

 

from app.agent.tools_support import *  # noqa: F401,F403


# 能力混入类，把这一领域的操作组合到主类中。
class ToolRegistryCommerceMixin:
    async def get_cart(self, account_id: str) -> ToolResult:
        rows = await self.repository.get_cart_rows(account_id)
        cart = cart_payload(rows)
        return ToolResult(tool='get_cart', ok=True, blocks=[{'type': 'cart_state', 'cart': cart}], result={'cart': cart})

    async def update_cart_item(self, account_id: str, cart_item_id: str, quantity: int | None=None, selected: bool | None=None) -> ToolResult:
        if not cart_item_id or not await self.repository.update_cart_item(account_id, cart_item_id, quantity, selected):
            return ToolResult(tool='update_cart_item', ok=False, message='购物车项不存在或参数不合法')
        cart = cart_payload(await self.repository.get_cart_rows(account_id))
        return ToolResult(tool='update_cart_item', ok=True, message='购物车已更新', blocks=[{'type': 'cart_state', 'cart': cart}], result={'cart': cart})

    async def delete_cart_item(self, account_id: str, cart_item_id: str) -> ToolResult:
        if not cart_item_id or not await self.repository.delete_cart_item(account_id, cart_item_id):
            return ToolResult(tool='delete_cart_item', ok=False, message='购物车项不存在')
        cart = cart_payload(await self.repository.get_cart_rows(account_id))
        return ToolResult(tool='delete_cart_item', ok=True, message='已从购物车移除', blocks=[{'type': 'cart_state', 'cart': cart}], result={'cart': cart})

    async def preview_discount(self, account_id: str) -> ToolResult:
        preview = await self.repository.preview_cart_discount(account_id)
        return ToolResult(tool='preview_discount', ok=True, blocks=[{'type': 'discount_preview', 'preview': preview}], result=preview)

    async def list_orders(self, account_id: str, limit: int=5) -> ToolResult:
        rows, _total = await self.repository.list_orders(account_id=account_id, page=1, page_size=max(1, min(limit, 20)))
        items = [order_payload(order, order_items, merchant.name) for order, merchant, order_items in rows]
        return ToolResult(tool='list_orders', ok=True, blocks=[{'type': 'order_list', 'orders': items}], result={'items': items})

    async def get_order(self, account_id: str, order_id: str) -> ToolResult:
        detail = await self.repository.get_order_detail(account_id, order_id)
        if detail is None:
            return ToolResult(tool='get_order', ok=False, message='订单不存在')
        order, merchant, items, payment = detail
        payload = order_payload(order, items, merchant.name)
        if payment is not None:
            payload['payment'] = {'payment_id': payment.payment_id, 'status': payment.status, 'method': payment.method, 'amount': amount_string(payment.amount)}
        return ToolResult(tool='get_order', ok=True, blocks=[{'type': 'order_detail', 'order': payload}], result={'order': payload})

    async def pay_order(self, account_id: str, order_id: str, method: str='mock_balance') -> ToolResult:
        result = await self.repository.pay_order(account_id, order_id, method)
        if result is None:
            return ToolResult(tool='pay_order', ok=False, message='订单不可支付，可能已支付、取消或超时关闭')
        order, payment = result
        detail = await self.repository.get_order_detail(account_id, order_id)
        payload = order_payload(order, detail[2], detail[1].name) if detail else {'order_id': order.order_id, 'status': order.status}
        return ToolResult(tool='pay_order', ok=True, message='支付已完成', blocks=[{'type': 'order_summary', 'orders': [payload]}], result={'order': payload, 'payment': {'payment_id': payment.payment_id, 'status': payment.status}})

    async def cancel_order(self, account_id: str, order_id: str, reason: str='') -> ToolResult:
        order = await self.repository.cancel_order(account_id, order_id, reason)
        if order is None:
            return ToolResult(tool='cancel_order', ok=False, message='订单不可取消，只有待支付订单可以取消')
        return ToolResult(tool='cancel_order', ok=True, message='订单已取消', result={'order_id': order.order_id, 'status': order.status})

    async def confirm_receipt(self, account_id: str, order_id: str) -> ToolResult:
        order = await self.repository.confirm_receipt(account_id, order_id)
        if order is None:
            return ToolResult(tool='confirm_receipt', ok=False, message='订单不可确认收货，只有已发货订单可以确认')
        return ToolResult(tool='confirm_receipt', ok=True, message='已确认收货', result={'order_id': order.order_id, 'status': order.status})

    async def list_coupons(self, account_id: str, limit: int=5) -> ToolResult:
        items, _total = await self.repository.list_available_coupons(1, max(1, min(limit, 20)))
        payload = [{'coupon_id': item.coupon_id, 'name': item.name, 'threshold_amount': amount_string(item.threshold_amount), 'discount_amount': amount_string(item.discount_amount), 'start_at': item.start_at.isoformat(), 'end_at': item.end_at.isoformat()} for item in items]
        return ToolResult(tool='list_coupons', ok=True, blocks=[{'type': 'coupon_list', 'coupons': payload}], result={'items': payload})

    async def list_user_coupons(self, account_id: str, limit: int=5) -> ToolResult:
        items, _total = await self.repository.list_user_coupons(account_id, 1, max(1, min(limit, 20)))
        payload = [{'user_coupon_id': item.user_coupon_id, 'coupon_id': item.coupon_id, 'name': coupon.name, 'status': item.status, 'end_at': coupon.end_at.isoformat()} for item, coupon in items]
        return ToolResult(tool='list_user_coupons', ok=True, blocks=[{'type': 'coupon_list', 'coupons': payload}], result={'items': payload})

    async def claim_coupon(self, account_id: str, coupon_id: str) -> ToolResult:
        result = await self.repository.claim_coupon(account_id, coupon_id)
        if result is None:
            return ToolResult(tool='claim_coupon', ok=False, message='优惠券不可领取，可能已领过、已过期或已领完')
        item, coupon = result
        return ToolResult(tool='claim_coupon', ok=True, message='优惠券已领取', result={'user_coupon_id': item.user_coupon_id, 'coupon_id': coupon.coupon_id, 'name': coupon.name})

    async def list_reviews(self, product_id: str, limit: int=5) -> ToolResult:
        items, _total = await self.repository.list_product_reviews(product_id, 1, max(1, min(limit, 20)))
        payload = [{'review_id': item.review_id, 'rating': item.rating, 'content': item.content, 'tags': list(item.tags_json or []), 'merchant_reply': item.merchant_reply or ''} for item in items]
        return ToolResult(tool='list_reviews', ok=True, blocks=[{'type': 'review_list', 'reviews': payload}], result={'items': payload})

    async def add_cart_item(self, account_id: str, product_id: str, allowed_product_ids: set[str], sku_id: str='', quantity: int=1) -> ToolResult:
        if product_id not in allowed_product_ids:
            return ToolResult(tool='add_cart_item', ok=False, message='请先从当前推荐结果中明确要加入购物车的商品')
        if not await self.repository.add_cart_item(account_id, product_id, sku_id, quantity):
            return ToolResult(tool='add_cart_item', ok=False, message='商品不存在或当前不可加购')
        rows = await self.repository.get_cart_rows(account_id)
        cart = cart_payload(rows)
        return ToolResult(tool='add_cart_item', ok=True, blocks=[{'type': 'cart_state', 'cart': cart}], result={'cart': cart})

    async def checkout(self, account_id: str) -> ToolResult:
        try:
            orders = await self.repository.checkout(account_id)
        except ValueError as error:
            return ToolResult(tool='checkout', ok=False, message=str(error))
        if not orders:
            return ToolResult(tool='checkout', ok=False, message='请选择购物车商品后再下单')
        payload = [order_payload(order, items, merchant_name) for order, items, merchant_name in orders]
        return ToolResult(tool='checkout', ok=True, blocks=[{'type': 'order_summary', 'orders': payload}], result={'orders': payload})
