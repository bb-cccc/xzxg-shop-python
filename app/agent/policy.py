from __future__ import annotations

 

from app.agent.planner import Plan


TOOL_DESCRIPTIONS = {
    "search_products": "搜索商品。参数 {query, limit, constraints:{brands,terms,categories}, negative:{brands,terms,categories}}。",
    "search_knowledge": "搜索知识库。参数 {query, limit}。",
    "search_image_products": "按附件或图片 URL 找相似商品。参数 {file_id,object_key,image_url,limit}。",
    "get_cart": "读取购物车。参数 {}。",
    "add_cart_item": "加购。参数 {product_id,sku_id,quantity}，product_id 必须来自搜索结果。",
    "update_cart_item": "修改购物车。参数 {cart_item_id,quantity,selected}。",
    "delete_cart_item": "删除购物车项。参数 {cart_item_id}。",
    "preview_discount": "试算购物车优惠。参数 {}。",
    "checkout": "创建待支付订单。参数 {}。",
    "list_orders": "查询订单。参数 {limit}。",
    "get_order": "查询订单详情。参数 {order_id}。",
    "pay_order": "支付订单。参数 {order_id,method}。",
    "cancel_order": "取消订单。参数 {order_id,reason}。",
    "confirm_receipt": "确认收货。参数 {order_id}。",
    "list_coupons": "查询可领取优惠券。参数 {limit}。",
    "list_user_coupons": "查询已领取优惠券。参数 {limit}。",
    "claim_coupon": "领取优惠券。参数 {coupon_id}。",
    "list_reviews": "查询商品评价。参数 {product_id,limit}。",
}


def allowed_tools(plan: Plan) -> set[str]:
    if plan.intent == "image_search":
        return {"search_image_products", "search_products", "search_knowledge"}
    if plan.intent == "cart_add":
        return {"get_cart", "add_cart_item"}
    if plan.intent == "cart_update":
        return {"get_cart", "update_cart_item"}
    if plan.intent == "cart_delete":
        return {"get_cart", "delete_cart_item"}
    if plan.intent == "cart_service":
        return {"get_cart", "preview_discount", "update_cart_item", "delete_cart_item", "checkout"}
    if plan.intent == "order_service":
        return {"get_cart", "checkout", "list_orders", "get_order", "pay_order", "cancel_order", "confirm_receipt"}
    if plan.intent == "coupon_service":
        return {"list_coupons", "list_user_coupons", "claim_coupon", "preview_discount"}
    if plan.intent == "review_service":
        return {"search_knowledge", "list_orders", "list_reviews"}
    if plan.route == "guide":
        return {"search_products", "search_knowledge", "search_image_products"}
    if plan.intent == "after_sales_service":
        return {"search_knowledge", "list_orders", "get_order", "list_reviews"}
    return set()


def tool_prompt(plan: Plan) -> str:
    names = allowed_tools(plan)
    lines = [f"- {name}: {TOOL_DESCRIPTIONS[name]}" for name in sorted(names)]
    return "当前允许的工具只能从以下列表选择：\n" + ("\n".join(lines) if lines else "- 无")
