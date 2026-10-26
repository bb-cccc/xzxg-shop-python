from __future__ import annotations

 

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.domain.models import CartItem, KnowledgeChunk, Merchant, Order, OrderItem, Product, ProductSKU
from app.domain.schemas import amount_string
from app.integrations.image_embedding import ImageEmbeddingError, build_image_embedder
from app.integrations.image_search import ImageSearchService
from app.integrations.objectstore import build_object_store
from app.integrations.rerank import ProductReranker, RerankUnavailable
from app.rag.service import RAGService, build_vector_provider
from app.core.config import Settings
from app.repositories.sql import SQLRepository


CATEGORY_LABELS = {
    "c_phone": "手机",
    "c_mouse": "鼠标",
}

@dataclass
class ToolResult:
    tool: str
    ok: bool
    message: str = ''
    product_ids: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)

def product_payload(product: Product, merchant: Merchant, sku: ProductSKU | None=None) -> dict[str, Any]:
    return {'productId': product.product_id, 'skuId': sku.sku_id if sku and sku.sku_id else None, 'merchantId': merchant.merchant_id, 'merchantName': merchant.name, 'name': product.name, 'brand': product.brand, 'categoryId': product.category_id, 'imageUrl': product.image_url, 'price': amount_string(product.price), 'marketPrice': amount_string(product.market_price), 'stockStatus': product.stock_status, 'tags': list(product.tags_json or []), 'sellingPoints': list(product.selling_points_json or []), 'recommendReason': product.recommend_reason, 'riskNotes': list(product.risk_notes_json or [])}

def cart_payload(rows: list[tuple[CartItem, Product, Merchant, ProductSKU | None]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    total = Decimal('0.00')
    selected_count = 0
    for cart_item, product, merchant, _sku in rows:
        unit_price = None
        unit_price = next((value for value in [getattr(_sku, 'price', None), product.price] if value is not None), product.price)
        amount = Decimal(str(unit_price)) * cart_item.quantity
        total += amount
        if cart_item.selected:
            selected_count += 1
        items.append({'cartItemId': cart_item.cart_item_id, 'productId': cart_item.product_id, 'skuId': cart_item.sku_id or None, 'name': product.name, 'imageUrl': product.image_url, 'price': amount_string(unit_price), 'quantity': cart_item.quantity, 'selected': cart_item.selected, 'stockStatus': product.stock_status, 'merchantId': merchant.merchant_id, 'merchantName': merchant.name})
    return {'items': items, 'summary': {'selectedCount': selected_count, 'totalAmount': amount_string(total), 'discountAmount': '0.00', 'payAmount': amount_string(total)}}

def order_payload(order: Order, items: list[OrderItem], merchant_name: str) -> dict[str, Any]:
    iso = lambda value: value.isoformat() if value is not None else None
    return {'order_id': order.order_id, 'order_no': order.order_no, 'account_id': order.account_id, 'merchant_id': order.merchant_id, 'merchant_name': merchant_name, 'status': order.status, 'total_amount': amount_string(order.total_amount), 'discount_amount': amount_string(order.discount_amount), 'pay_amount': amount_string(order.pay_amount), 'payment_deadline_at': iso(order.payment_deadline_at), 'paid_at': iso(order.paid_at), 'closed_at': iso(order.closed_at), 'completed_at': iso(order.completed_at), 'cancel_reason': order.cancel_reason or None, 'items': [{'order_item_id': item.order_item_id, 'product_id': item.product_id, 'sku_id': item.sku_id or None, 'name': item.name, 'image_url': item.image_url, 'price': amount_string(item.price), 'quantity': item.quantity, 'merchant_id': item.merchant_id, 'merchant_name': item.merchant_name} for item in items], 'created_at': iso(order.created_at), 'updated_at': iso(order.updated_at)}
