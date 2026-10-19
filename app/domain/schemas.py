"""API 输入输出契约：负责边界校验、序列化和金额格式统一。"""

from __future__ import annotations

# 接口数据模型：定义请求、响应和分页数据的校验规则。

from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    """所有接口模型的公共基类，统一 Pydantic 配置和序列化行为。"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LoginRequest(APIModel):
    """LoginRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    username: str
    password: str


class RegisterRequest(APIModel):
    """RegisterRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    username: str
    password: str
    display_name: str = ""

    @field_validator("username", "password", "display_name", mode="before")
    @classmethod
    def normalize_strings(cls, value: object) -> str:
        return str(value or "").strip()


class AccountOut(APIModel):
    """AccountOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    account_id: str
    username: str
    display_name: str
    avatar_url: str | None = None
    phone: str | None = None
    email: str | None = None
    role: str
    merchant_id: str | None = None
    status: str | None = None
    created_at: datetime


class AuthResponse(APIModel):
    """AuthResponse 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    token: str
    account: AccountOut


class CategoryOut(APIModel):
    """CategoryOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    category_id: str = Field(alias="categoryId")
    parent_id: str = Field(alias="parentId")
    name: str
    children: list["CategoryOut"] | None = None


class MerchantOut(APIModel):
    """MerchantOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    merchant_id: str = Field(alias="merchantId")
    name: str
    logo_url: str = Field(alias="logoUrl")
    description: str
    service_phone: str | None = Field(default=None, alias="servicePhone")
    status: str


class ProductCardOut(APIModel):
    """ProductCardOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    product_id: str = Field(alias="productId")
    sku_id: str | None = Field(default=None, alias="skuId")
    merchant_id: str = Field(alias="merchantId")
    merchant_name: str = Field(alias="merchantName")
    name: str
    brand: str
    category_id: str = Field(alias="categoryId")
    image_url: str = Field(alias="imageUrl")
    price: str
    market_price: str | None = Field(default=None, alias="marketPrice")
    stock_status: str = Field(alias="stockStatus")
    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    selling_points: list[str] = Field(default_factory=list, alias="sellingPoints")
    recommend_reason: str = Field(default="", alias="recommendReason")
    risk_notes: list[str] = Field(default_factory=list, alias="riskNotes")


class ProductAttributeOut(APIModel):
    """ProductAttributeOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    key: str
    value: str
    unit: str | None = None


class ProductDetailOut(ProductCardOut):
    """ProductDetailOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    image_urls: list[str] = Field(default_factory=list, alias="imageUrls")
    stock_quantity: int = Field(alias="stockQuantity")
    attributes: list[ProductAttributeOut] = Field(default_factory=list)
    suitable_for: list[str] = Field(default_factory=list, alias="suitableFor")
    not_suitable_for: list[str] = Field(default_factory=list, alias="notSuitableFor")
    description: str = ""


class ProductSKUOut(APIModel):
    """ProductSKUOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    sku_id: str = Field(alias="skuId")
    product_id: str = Field(alias="productId")
    sku_name: str = Field(alias="skuName")
    price: str
    stock_quantity: int = Field(alias="stockQuantity")
    stock_status: str = Field(alias="stockStatus")
    specs: dict[str, str] = Field(default_factory=dict)


T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    """分页响应包装器，统一返回数据列表、总数和分页参数。"""
    items: list[T]
    page: int
    page_size: int
    total: int


class AttachmentIn(APIModel):
    """AttachmentIn 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    attachment_id: str = ""
    file_id: str | None = None
    type: str = ""
    url: str | None = None
    name: str | None = None
    object_key: str | None = None


class SessionCreateRequest(APIModel):
    """SessionCreateRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    title: str = "AI 导购"


class SessionPatchRequest(APIModel):
    """SessionPatchRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    title: str = ""
    summary: str = ""


class SessionPinRequest(APIModel):
    """SessionPinRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    pinned: bool


class ChatSessionOut(APIModel):
    """ChatSessionOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    session_id: str
    account_id: str | None = None
    title: str
    summary: str | None = None
    message_count: int
    last_message_at: datetime | None = None
    pinned_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserMessageOut(APIModel):
    """UserMessageOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    message_id: str
    session_id: str
    account_id: str | None = None
    client_message_id: str
    content: str
    attachments: list[AttachmentIn] = Field(default_factory=list)
    created_at: datetime


class AgentRunOut(APIModel):
    """AgentRunOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    run_id: str
    session_id: str
    message_id: str
    account_id: str | None = None
    status: str
    trace_id: str
    query_title: str | None = None
    created_at: datetime
    updated_at: datetime
    content: str = ""
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    segments: list[dict[str, Any]] = Field(default_factory=list)


class UserMessageWithRunsOut(UserMessageOut):
    """UserMessageWithRunsOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    runs: list[AgentRunOut] = Field(default_factory=list)


class ChatSessionDetailOut(APIModel):
    """ChatSessionDetailOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    session: ChatSessionOut
    messages: list[UserMessageWithRunsOut] = Field(default_factory=list)


class AgentTraceOut(APIModel):
    """AgentTraceOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    trace_event_id: str
    run_id: str
    trace_id: str
    account_id: str | None = None
    stage: str
    event_type: str
    model: str | None = None
    status: str
    duration_ms: int = 0
    error: str | None = None
    metadata_json: str | dict[str, Any] | None = None
    created_at: datetime


class AgentMessageRequest(APIModel):
    """AgentMessageRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    client_message_id: str = ""
    content: str
    attachments: list[AttachmentIn] = Field(default_factory=list)


class ImageSearchRequest(APIModel):
    """ImageSearchRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    file_id: str = ""
    object_key: str = ""
    image_url: str = ""
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeDocumentCreateRequest(APIModel):
    """KnowledgeDocumentCreateRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    title: str
    doc_type: str = ""
    content: str
    source_url: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    force_reindex: bool = False


class KnowledgeDocumentOut(APIModel):
    """KnowledgeDocumentOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    document_id: str
    merchant_id: str
    title: str
    doc_type: str
    status: str
    chunk_count: int
    source_url: str
    content_hash: str
    created_at: datetime


class StoredFileOut(APIModel):
    """StoredFileOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    file_id: str
    account_id: str
    object_key: str
    url: str
    mime_type: str
    size_bytes: int
    content_hash: str
    storage_provider: str
    source_url: str = ""
    created_at: datetime


class CartItemOut(APIModel):
    """CartItemOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    cart_item_id: str = Field(alias="cartItemId")
    product_id: str = Field(alias="productId")
    sku_id: str | None = Field(default=None, alias="skuId")
    name: str
    image_url: str = Field(alias="imageUrl")
    price: str
    quantity: int
    selected: bool
    stock_status: str = Field(alias="stockStatus")
    merchant_id: str = Field(alias="merchantId")
    merchant_name: str = Field(alias="merchantName")


class CartSummaryOut(APIModel):
    """CartSummaryOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    selected_count: int = Field(alias="selectedCount")
    total_amount: str = Field(alias="totalAmount")
    discount_amount: str = Field(alias="discountAmount")
    pay_amount: str = Field(alias="payAmount")


class CartOut(APIModel):
    """CartOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    items: list[CartItemOut] = Field(default_factory=list)
    summary: CartSummaryOut


class CartAddRequest(APIModel):
    """CartAddRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    product_id: str
    sku_id: str = ""
    quantity: int = Field(default=1, ge=1)


class CartPatchRequest(APIModel):
    """CartPatchRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    quantity: int | None = Field(default=None, ge=1)
    selected: bool | None = None


class PaymentRequest(APIModel):
    """PaymentRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    method: str = "mock_balance"


class CancelOrderRequest(APIModel):
    """CancelOrderRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    reason: str = ""


class OrderItemOut(APIModel):
    """OrderItemOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    order_item_id: str
    product_id: str
    sku_id: str | None = None
    name: str
    image_url: str
    price: str
    quantity: int
    merchant_id: str
    merchant_name: str


class OrderOut(APIModel):
    """OrderOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    order_id: str
    order_no: str
    account_id: str
    merchant_id: str
    merchant_name: str = ""
    status: str
    total_amount: str
    discount_amount: str
    pay_amount: str
    payment_deadline_at: datetime | None = None
    paid_at: datetime | None = None
    closed_at: datetime | None = None
    completed_at: datetime | None = None
    cancel_reason: str | None = None
    items: list[OrderItemOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DiscountLineOut(APIModel):
    """DiscountLineOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    type: str
    id: str
    name: str
    amount: str
    description: str | None = None


class DiscountPreviewOut(APIModel):
    """DiscountPreviewOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    total_amount: str
    discount_amount: str
    pay_amount: str
    lines: list[DiscountLineOut] = Field(default_factory=list)


class PaymentOut(APIModel):
    """PaymentOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    payment_id: str
    order_id: str
    account_id: str
    amount: str
    status: str
    method: str
    transaction_no: str = ""
    expires_at: datetime
    paid_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CouponOut(APIModel):
    """CouponOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    coupon_id: str
    name: str
    scope: str
    merchant_id: str = ""
    type: str
    threshold_amount: str
    discount_amount: str
    total_count: int
    claimed_count: int
    per_user_limit: int
    start_at: datetime
    end_at: datetime
    status: str
    created_at: datetime
    updated_at: datetime


class UserCouponOut(APIModel):
    """UserCouponOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    user_coupon_id: str
    coupon_id: str
    account_id: str
    status: str
    order_id: str = ""
    claimed_at: datetime
    used_at: datetime | None = None
    coupon: CouponOut


class PromotionRuleRequest(APIModel):
    """PromotionRuleRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    name: str
    scope: str = "platform"
    merchant_id: str = ""
    product_id: str = ""
    category_id: str = ""
    type: str = "full_reduction"
    threshold_amount: str = "0.00"
    discount_amount: str = "0.00"
    discount_rate: str = "0.0000"
    stackable: bool = True
    start_at: datetime | None = None
    end_at: datetime | None = None
    status: str = "active"


class PromotionRuleOut(APIModel):
    """PromotionRuleOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    promotion_id: str
    name: str
    scope: str
    merchant_id: str = ""
    product_id: str = ""
    category_id: str = ""
    type: str
    threshold_amount: str
    discount_amount: str
    discount_rate: str
    stackable: bool
    start_at: datetime
    end_at: datetime
    status: str
    created_at: datetime
    updated_at: datetime


class ProductUpsertRequest(APIModel):
    """ProductUpsertRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    name: str
    brand: str = ""
    category_id: str = ""
    image_url: str = ""
    image_urls: list[str] = Field(default_factory=list)
    price: str = "0.00"
    market_price: str = "0.00"
    stock_quantity: int = 0
    stock_status: str = "out_of_stock"
    tags: list[str] = Field(default_factory=list)
    selling_points: list[str] = Field(default_factory=list)
    recommend_reason: str = ""
    risk_notes: list[str] = Field(default_factory=list)
    description: str = ""



class ReviewRequest(APIModel):
    """ReviewRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    rating: int = Field(ge=1, le=5)
    content: str
    tags: list[str] = Field(default_factory=list)


class ReviewReplyRequest(APIModel):
    """ReviewReplyRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    reply: str


class ReviewStatusRequest(APIModel):
    """ReviewStatusRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    status: str


class ProductReviewOut(APIModel):
    """ProductReviewOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    review_id: str
    order_id: str
    order_item_id: str
    product_id: str
    sku_id: str = ""
    account_id: str
    username: str = ""
    rating: int
    content: str
    tags: list[str] = Field(default_factory=list)
    status: str
    merchant_reply: str = ""
    merchant_replied_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class StatusRequest(APIModel):
    """StatusRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    status: str


class ConfigUpdateRequest(APIModel):
    """ConfigUpdateRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    value: str
    value_type: str = "string"
    description: str = ""
    is_secret: bool | None = None


class ConfigOut(APIModel):
    """ConfigOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    config_key: str
    config_value: str
    value_type: str
    description: str
    domain: str = ""
    is_secret: bool
    updated_at: datetime


class PromptDraftRequest(APIModel):
    """PromptDraftRequest 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    title: str = ""
    content: str
    description: str = ""


class PromptOut(APIModel):
    """PromptOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    prompt_id: str
    prompt_key: str
    title: str
    content: str
    status: str
    version: int
    description: str
    created_by: str = ""
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PromptPublishRecordOut(APIModel):
    """PromptPublishRecordOut 的请求或响应数据模型，负责边界校验与 JSON 序列化。"""
    record_id: str
    prompt_key: str
    prompt_id: str
    version: int
    published_by: str = ""
    publish_target: str
    created_at: datetime


def amount_string(value: Decimal | int | float | str | None) -> str:
    """将金额安全转换为两位小数字符串，避免浮点值直接暴露给前端。"""
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):.2f}"
