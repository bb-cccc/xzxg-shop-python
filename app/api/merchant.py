from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.agent.tools import order_payload
from app.api.dependencies import get_current_merchant, get_repository
from app.api.products import product_card, product_detail
from app.core.errors import APIError
from app.domain.models import Account, Product, ProductReview, PromotionRule
from app.domain.schemas import (
    PageResponse,
    ProductReviewOut,
    ProductUpsertRequest,
    PromotionRuleOut,
    PromotionRuleRequest,
    ReviewReplyRequest,
    StatusRequest,
)
from app.repositories.sql import SQLRepository

router = APIRouter(prefix="/merchant", tags=["merchant"])


def _promotion(item: PromotionRule) -> PromotionRuleOut:
    return PromotionRuleOut(
        promotion_id=item.promotion_id, name=item.name, scope=item.scope, merchant_id=item.merchant_id,
        product_id=item.product_id, category_id=item.category_id, type=item.type,
        threshold_amount=f"{item.threshold_amount:.2f}", discount_amount=f"{item.discount_amount:.2f}",
        discount_rate=f"{item.discount_rate:.4f}", stackable=item.stackable, start_at=item.start_at,
        end_at=item.end_at, status=item.status, created_at=item.created_at, updated_at=item.updated_at,
    )


def _promotion_values(request: PromotionRuleRequest) -> tuple[Decimal, Decimal, Decimal]:
    try:
        return Decimal(request.threshold_amount), Decimal(request.discount_amount), Decimal(request.discount_rate)
    except InvalidOperation as error:
        raise APIError(400, "create_promotion_failed", "促销金额或比例不合法") from error


def _review(item: ProductReview) -> ProductReviewOut:
    return ProductReviewOut(
        review_id=item.review_id, order_id=item.order_id, order_item_id=item.order_item_id,
        product_id=item.product_id, sku_id=item.sku_id, account_id=item.account_id,
        rating=item.rating, content=item.content, tags=list(item.tags_json or []), status=item.status,
        merchant_reply=item.merchant_reply or "", merchant_replied_at=item.merchant_replied_at,
        created_at=item.created_at, updated_at=item.updated_at,
    )


def _product_values(request: ProductUpsertRequest) -> dict[str, object]:
    try:
        price = Decimal(request.price)
        market_price = Decimal(request.market_price)
    except InvalidOperation as error:
        raise APIError(400, "bad_price", "商品价格不合法") from error
    return {
        "name": request.name.strip(), "brand": request.brand.strip(), "category_id": request.category_id.strip(),
        "image_url": request.image_url.strip(),
        "image_urls_json": request.image_urls or ([request.image_url] if request.image_url.strip() else []),
        "price": price, "market_price": market_price,
        "stock_quantity": request.stock_quantity, "stock_status": request.stock_status,
        "tags_json": request.tags, "selling_points_json": request.selling_points,
        "recommend_reason": request.recommend_reason, "risk_notes_json": request.risk_notes,
        "description": request.description,
    }


@router.post("/products", response_model=object)
async def create_product(request: ProductUpsertRequest, account: Account = Depends(get_current_merchant),
                         repository: SQLRepository = Depends(get_repository)):
    if not request.name.strip():
        raise APIError(400, "empty_name", "商品名称不能为空")
    product = Product(product_id=repository._new_id("p"), merchant_id=account.merchant_id, status="active",
                      sort_order=0, **_product_values(request))
    await repository.create_product(product)
    row = await repository.get_product_record(product.product_id)
    assert row is not None
    return product_detail(*row)


@router.patch("/products/{product_id}", response_model=object)
async def update_product(product_id: str, request: ProductUpsertRequest,
                         account: Account = Depends(get_current_merchant),
                         repository: SQLRepository = Depends(get_repository)):
    if not request.name.strip():
        raise APIError(400, "empty_name", "商品名称不能为空")
    row = await repository.update_product(product_id, account.merchant_id, _product_values(request))
    if row is None:
        raise APIError(404, "product_not_found", "商品不存在或不属于当前商家")
    return product_detail(*row)


@router.delete("/products/{product_id}")
async def delete_product(product_id: str, account: Account = Depends(get_current_merchant),
                         repository: SQLRepository = Depends(get_repository)) -> dict[str, str]:
    item = await repository.update_product_status(product_id, "deleted", account.merchant_id)
    if item is None:
        raise APIError(404, "product_not_found", "商品不存在或不属于当前商家")
    return {"product_id": product_id, "status": "deleted"}


@router.get("/orders", response_model=PageResponse[dict[str, object]])
async def merchant_orders(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                          account: Account = Depends(get_current_merchant),
                          repository: SQLRepository = Depends(get_repository)) -> PageResponse[dict[str, object]]:
    await repository.expire_pending_orders()
    rows, total = await repository.list_orders(merchant_id=account.merchant_id, page=page, page_size=page_size)
    return PageResponse(items=[order_payload(order, items, merchant.name) for order, merchant, items in rows],
                        page=page, page_size=page_size, total=total)


@router.patch("/orders/{order_id}")
async def merchant_order_status(order_id: str, request: StatusRequest, account: Account = Depends(get_current_merchant),
                                repository: SQLRepository = Depends(get_repository)) -> dict[str, object]:
    if request.status not in {"pending_ship", "shipped", "completed", "canceled", "refund_requested", "refunded",
                              "closed_timeout"}:
        raise APIError(400, "bad_status", "订单状态不合法")
    result = await repository.update_order_status(order_id, request.status, account.merchant_id)
    if result is None:
        raise APIError(404, "order_not_found", "订单不存在或不属于当前商家")
    order, merchant, items = result
    return order_payload(order, items, merchant.name)


@router.get("/promotions", response_model=PageResponse[PromotionRuleOut])
async def merchant_promotions(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                              account: Account = Depends(get_current_merchant),
                              repository: SQLRepository = Depends(get_repository)) -> PageResponse[PromotionRuleOut]:
    items, total = await repository.list_promotions(account.merchant_id, page, page_size)
    return PageResponse(items=[_promotion(item) for item in items], page=page, page_size=page_size, total=total)


@router.post("/promotions", response_model=PromotionRuleOut)
async def create_merchant_promotion(request: PromotionRuleRequest, account: Account = Depends(get_current_merchant),
                                    repository: SQLRepository = Depends(get_repository)) -> PromotionRuleOut:
    now = datetime.now(timezone.utc)
    threshold, discount, rate = _promotion_values(request)
    item = PromotionRule(
        promotion_id=repository._new_id("promo"), name=request.name.strip(), scope="merchant",
        merchant_id=account.merchant_id,
        product_id=request.product_id, category_id=request.category_id, type=request.type,
        threshold_amount=threshold, discount_amount=discount, discount_rate=rate,
        stackable=request.stackable, start_at=request.start_at or now,
        end_at=request.end_at or now.replace(year=now.year + 1), status=request.status,
    )
    if not item.name:
        raise APIError(400, "create_promotion_failed", "促销名称不能为空")
    return _promotion(await repository.create_promotion(item))


@router.patch("/promotions/{promotion_id}", response_model=PromotionRuleOut)
async def update_merchant_promotion(promotion_id: str, request: StatusRequest,
                                    account: Account = Depends(get_current_merchant),
                                    repository: SQLRepository = Depends(get_repository)) -> PromotionRuleOut:
    if request.status not in {"active", "inactive"}:
        raise APIError(400, "bad_status", "促销状态不合法")
    item = await repository.update_promotion_status(promotion_id, request.status, account.merchant_id)
    if item is None:
        raise APIError(404, "promotion_not_found", "促销不存在或不属于当前商家")
    return _promotion(item)


@router.get("/reviews", response_model=PageResponse[ProductReviewOut])
async def merchant_reviews(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                           account: Account = Depends(get_current_merchant),
                           repository: SQLRepository = Depends(get_repository)) -> PageResponse[ProductReviewOut]:
    items, total = await repository.list_product_reviews("", page, page_size, merchant_id=account.merchant_id,
                                                         all_status=True)
    return PageResponse(items=[_review(item) for item in items], page=page, page_size=page_size, total=total)


@router.post("/reviews/{review_id}:reply", response_model=ProductReviewOut)
async def reply_review(review_id: str, request: ReviewReplyRequest, account: Account = Depends(get_current_merchant),
                       repository: SQLRepository = Depends(get_repository)) -> ProductReviewOut:
    item = await repository.reply_review(account.merchant_id, review_id, request.reply)
    if item is None:
        raise APIError(404, "review_not_found", "评价不存在或不属于当前商家")
    return _review(item)
