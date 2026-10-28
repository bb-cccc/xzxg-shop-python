from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.agent.tools import cart_payload, order_payload
from app.api.dependencies import get_commerce_service, get_current_user, get_repository
from app.core.errors import APIError
from app.domain.models import Account, ProductReview
from app.domain.schemas import (
    CancelOrderRequest,
    CartAddRequest,
    CartOut,
    CartPatchRequest,
    CouponOut,
    DiscountPreviewOut,
    PageResponse,
    OrderOut,
    PaymentOut,
    PaymentRequest,
    ProductReviewOut,
    PromotionRuleOut,
    ReviewRequest,
    UserCouponOut,
)
from app.repositories.sql import SQLRepository
from app.services.commerce import CommerceService

router = APIRouter(tags=["commerce"])


def payment_out(item) -> PaymentOut:
    return PaymentOut(
        payment_id=item.payment_id, order_id=item.order_id, account_id=item.account_id,
        amount=f"{item.amount:.2f}", status=item.status, method=item.method,
        transaction_no=item.transaction_no, expires_at=item.expires_at, paid_at=item.paid_at,
        created_at=item.created_at, updated_at=item.updated_at,
    )


def review_out(item: ProductReview) -> ProductReviewOut:
    return ProductReviewOut(
        review_id=item.review_id, order_id=item.order_id, order_item_id=item.order_item_id,
        product_id=item.product_id, sku_id=item.sku_id, account_id=item.account_id,
        rating=item.rating, content=item.content, tags=list(item.tags_json or []), status=item.status,
        merchant_reply=item.merchant_reply or "", merchant_replied_at=item.merchant_replied_at,
        created_at=item.created_at, updated_at=item.updated_at,
    )


def coupon_out(item) -> CouponOut:
    return CouponOut(
        coupon_id=item.coupon_id, name=item.name, scope=item.scope, merchant_id=item.merchant_id,
        type=item.type, threshold_amount=f"{item.threshold_amount:.2f}", discount_amount=f"{item.discount_amount:.2f}",
        total_count=item.total_count, claimed_count=item.claimed_count, per_user_limit=item.per_user_limit,
        start_at=item.start_at, end_at=item.end_at, status=item.status, created_at=item.created_at,
        updated_at=item.updated_at,
    )


def order_out(order, merchant, items):
    return order_payload(order, items, merchant.name)


def promotion_out(item) -> PromotionRuleOut:
    return PromotionRuleOut(
        promotion_id=item.promotion_id, name=item.name, scope=item.scope, merchant_id=item.merchant_id,
        product_id=item.product_id, category_id=item.category_id, type=item.type,
        threshold_amount=f"{item.threshold_amount:.2f}", discount_amount=f"{item.discount_amount:.2f}",
        discount_rate=f"{item.discount_rate:.4f}", stackable=item.stackable, start_at=item.start_at,
        end_at=item.end_at, status=item.status, created_at=item.created_at, updated_at=item.updated_at,
    )


@router.get("/cart", response_model=CartOut, response_model_exclude_none=True)
async def get_cart(account: Account = Depends(get_current_user),
                   repository: SQLRepository = Depends(get_repository)) -> CartOut:
    return CartOut.model_validate(cart_payload(await repository.get_cart_rows(account.account_id)))


@router.get("/cart/discount-preview")
async def discount_preview(account: Account = Depends(get_current_user),
                           service: CommerceService = Depends(get_commerce_service)) -> dict[str, object]:
    return await service.discount_preview(account.account_id)


@router.post("/cart/items", response_model=CartOut, response_model_exclude_none=True)
async def add_cart(request: CartAddRequest, account: Account = Depends(get_current_user),
                   repository: SQLRepository = Depends(get_repository)) -> CartOut:
    if not await repository.add_cart_item(account.account_id, request.product_id, request.sku_id, request.quantity):
        raise APIError(404, "product_not_found", "商品不存在")
    return CartOut.model_validate(cart_payload(await repository.get_cart_rows(account.account_id)))


@router.patch("/cart/items/{cart_item_id}", response_model=CartOut, response_model_exclude_none=True)
async def patch_cart(cart_item_id: str, request: CartPatchRequest, account: Account = Depends(get_current_user),
                     repository: SQLRepository = Depends(get_repository)) -> CartOut:
    if not await repository.update_cart_item(account.account_id, cart_item_id, request.quantity, request.selected):
        raise APIError(404, "cart_item_not_found", "购物车项不存在")
    return CartOut.model_validate(cart_payload(await repository.get_cart_rows(account.account_id)))


@router.delete("/cart/items/{cart_item_id}", response_model=CartOut, response_model_exclude_none=True)
async def delete_cart(cart_item_id: str, account: Account = Depends(get_current_user),
                      repository: SQLRepository = Depends(get_repository)) -> CartOut:
    if not await repository.delete_cart_item(account.account_id, cart_item_id):
        raise APIError(404, "cart_item_not_found", "购物车项不存在")
    return CartOut.model_validate(cart_payload(await repository.get_cart_rows(account.account_id)))


@router.get("/orders", response_model=PageResponse[OrderOut])
async def list_orders(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                      account: Account = Depends(get_current_user),
                      repository: SQLRepository = Depends(get_repository)) -> PageResponse[OrderOut]:
    await repository.expire_pending_orders()
    rows, total = await repository.list_orders(account_id=account.account_id, page=page, page_size=page_size)
    return PageResponse(items=[order_out(order, merchant, items) for order, merchant, items in rows], page=page,
                        page_size=page_size, total=total)


@router.post("/orders:checkout", response_model=dict[str, list[OrderOut]])
async def checkout(account: Account = Depends(get_current_user),
                   service: CommerceService = Depends(get_commerce_service)) -> dict[str, list[dict[str, object]]]:
    try:
        orders = await service.checkout(account.account_id)
    except ValueError as error:
        raise APIError(400, "checkout_failed", str(error)) from error
    if not orders:
        raise APIError(400, "empty_cart", "请选择购物车商品后再下单")
    return {"items": [order_payload(order, items, merchant_name) for order, items, merchant_name in orders]}


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: str, account: Account = Depends(get_current_user),
                    repository: SQLRepository = Depends(get_repository)) -> dict[str, object]:
    await repository.expire_pending_orders()
    detail = await repository.get_order_detail(account.account_id, order_id)
    if detail is None:
        raise APIError(404, "order_not_found", "订单不存在")
    order, merchant, items, _payment = detail
    return order_out(order, merchant, items)


@router.post("/orders/{order_id}:pay")
async def pay_order(order_id: str, request: PaymentRequest | None = None, account: Account = Depends(get_current_user),
                    repository: SQLRepository = Depends(get_repository),
                    service: CommerceService = Depends(get_commerce_service)) -> dict[str, object]:
    result = await service.pay(account.account_id, order_id, request.method if request else "mock_balance")
    if result is None:
        raise APIError(409, "pay_failed", "订单不可支付，可能已支付、取消或超时关闭")
    order, payment = result
    detail = await repository.get_order_detail(account.account_id, order_id)
    assert detail is not None
    return {"order": order_out(order, detail[1], detail[2]), "payment": payment_out(payment).model_dump()}


@router.post("/orders/{order_id}:cancel")
async def cancel_order(order_id: str, request: CancelOrderRequest | None = None,
                       account: Account = Depends(get_current_user),
                       repository: SQLRepository = Depends(get_repository),
                       service: CommerceService = Depends(get_commerce_service)) -> dict[str, object]:
    order = await service.cancel(account.account_id, order_id, request.reason if request else "")
    if order is None:
        raise APIError(409, "cancel_failed", "订单不可取消，只有待支付订单可以取消")
    detail = await repository.get_order_detail(account.account_id, order_id)
    assert detail is not None
    return order_out(order, detail[1], detail[2])


@router.post("/orders/{order_id}:confirm-receipt")
async def confirm_receipt(order_id: str, account: Account = Depends(get_current_user),
                          repository: SQLRepository = Depends(get_repository),
                          service: CommerceService = Depends(get_commerce_service)) -> dict[str, object]:
    order = await service.confirm_receipt(account.account_id, order_id)
    if order is None:
        raise APIError(409, "confirm_failed", "订单不可确认收货，只有已发货订单可以确认")
    detail = await repository.get_order_detail(account.account_id, order_id)
    assert detail is not None
    return order_out(order, detail[1], detail[2])


@router.get("/coupons/available", response_model=PageResponse[CouponOut])
async def available_coupons(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                            account: Account = Depends(get_current_user),
                            repository: SQLRepository = Depends(get_repository)) -> PageResponse[CouponOut]:
    del account
    items, total = await repository.list_available_coupons(page, page_size)
    return PageResponse(items=[coupon_out(item) for item in items], page=page, page_size=page_size, total=total)


@router.get("/promotions", response_model=PageResponse[PromotionRuleOut])
async def promotions(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                     repository: SQLRepository = Depends(get_repository)) -> PageResponse[PromotionRuleOut]:
    items, total = await repository.list_promotions("", page, page_size)
    return PageResponse(items=[promotion_out(item) for item in items], page=page, page_size=page_size, total=total)


@router.get("/coupons/mine", response_model=PageResponse[UserCouponOut])
async def mine_coupons(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                       account: Account = Depends(get_current_user),
                       repository: SQLRepository = Depends(get_repository)) -> PageResponse[UserCouponOut]:
    items, total = await repository.list_user_coupons(account.account_id, page, page_size)
    return PageResponse(items=[
        UserCouponOut(user_coupon_id=item.user_coupon_id, coupon_id=item.coupon_id, account_id=item.account_id,
                      status=item.status, order_id=item.order_id, claimed_at=item.claimed_at, used_at=item.used_at,
                      coupon=coupon_out(coupon)) for item, coupon in items], page=page, page_size=page_size,
                        total=total)


@router.post("/coupons/{coupon_id}:claim", response_model=UserCouponOut)
async def claim_coupon(coupon_id: str, account: Account = Depends(get_current_user),
                       repository: SQLRepository = Depends(get_repository)) -> UserCouponOut:
    result = await repository.claim_coupon(account.account_id, coupon_id)
    if result is None:
        raise APIError(409, "claim_failed", "优惠券不可领取，可能已领过、已过期或已领完")
    item, coupon = result
    return UserCouponOut(user_coupon_id=item.user_coupon_id, coupon_id=item.coupon_id, account_id=item.account_id,
                         status=item.status, order_id=item.order_id, claimed_at=item.claimed_at, used_at=item.used_at,
                         coupon=coupon_out(coupon))


@router.get("/products/{product_id}/reviews", response_model=PageResponse[ProductReviewOut])
async def product_reviews(product_id: str, page: int = Query(default=1, ge=1),
                          page_size: int = Query(default=10, ge=1, le=100),
                          repository: SQLRepository = Depends(get_repository)) -> PageResponse[ProductReviewOut]:
    items, total = await repository.list_product_reviews(product_id, page, page_size)
    return PageResponse(items=[review_out(item) for item in items], page=page, page_size=page_size, total=total)


@router.post("/orders/{order_id}/items/{order_item_id}:review", response_model=ProductReviewOut)
async def create_review(order_id: str, order_item_id: str, request: ReviewRequest,
                        account: Account = Depends(get_current_user),
                        repository: SQLRepository = Depends(get_repository)) -> ProductReviewOut:
    item = await repository.create_product_review(account.account_id, order_id, order_item_id, request.rating,
                                                  request.content, request.tags)
    if item is None:
        raise APIError(409, "review_failed", "评价失败，只有已完成订单项可评价且不可重复评价")
    return review_out(item)
