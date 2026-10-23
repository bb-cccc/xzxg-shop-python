from __future__ import annotations

# 领域模型模块：定义业务实体、状态和接口数据结构。

from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


# 模块中的核心类型，封装相关状态和行为。
class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# 接口数据模型，负责约束边界输入或输出格式。
class LoginRequest(APIModel):
    username: str
    password: str


# 接口数据模型，负责约束边界输入或输出格式。
class RegisterRequest(APIModel):
    username: str
    password: str
    display_name: str = ""

    # 规范化 normalize_strings 
    @field_validator("username", "password", "display_name", mode="before")
    @classmethod
    def normalize_strings(cls, value: object) -> str:
        return str(value or "").strip()


# 接口数据模型，负责约束边界输入或输出格式。
class AccountOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class AccountProfileUpdateRequest(APIModel):
    display_name: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None


# 接口数据模型，负责约束边界输入或输出格式。
class ContactUpdateRequest(APIModel):
    phone: str | None = None
    email: str | None = None


# 接口数据模型，负责约束边界输入或输出格式。
class AuthResponse(APIModel):
    token: str
    account: AccountOut


# 接口数据模型，负责约束边界输入或输出格式。
class CategoryOut(APIModel):
    category_id: str = Field(alias="categoryId")
    parent_id: str = Field(alias="parentId")
    name: str
    children: list["CategoryOut"] | None = None


# 接口数据模型，负责约束边界输入或输出格式。
class MerchantOut(APIModel):
    merchant_id: str = Field(alias="merchantId")
    name: str
    logo_url: str = Field(alias="logoUrl")
    description: str
    service_phone: str | None = Field(default=None, alias="servicePhone")
    status: str


# 接口数据模型，负责约束边界输入或输出格式。
class ProductCardOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class ProductAttributeOut(APIModel):
    key: str
    value: str
    unit: str | None = None


# 接口数据模型，负责约束边界输入或输出格式。
class ProductDetailOut(ProductCardOut):
    image_urls: list[str] = Field(default_factory=list, alias="imageUrls")
    stock_quantity: int = Field(alias="stockQuantity")
    attributes: list[ProductAttributeOut] = Field(default_factory=list)
    suitable_for: list[str] = Field(default_factory=list, alias="suitableFor")
    not_suitable_for: list[str] = Field(default_factory=list, alias="notSuitableFor")
    description: str = ""


# 接口数据模型，负责约束边界输入或输出格式。
class ProductSKUOut(APIModel):
    sku_id: str = Field(alias="skuId")
    product_id: str = Field(alias="productId")
    sku_name: str = Field(alias="skuName")
    price: str
    stock_quantity: int = Field(alias="stockQuantity")
    stock_status: str = Field(alias="stockStatus")
    specs: dict[str, str] = Field(default_factory=dict)


T = TypeVar("T")


# 接口数据模型，负责约束边界输入或输出格式。
class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int


# 模块中的核心类型，封装相关状态和行为。
class AttachmentIn(APIModel):
    attachment_id: str = ""
    file_id: str | None = None
    type: str = ""
    url: str | None = None
    name: str | None = None
    object_key: str | None = None


# 接口数据模型，负责约束边界输入或输出格式。
class SessionCreateRequest(APIModel):
    title: str = "AI 导购"


# 接口数据模型，负责约束边界输入或输出格式。
class SessionPatchRequest(APIModel):
    title: str = ""
    summary: str = ""


# 接口数据模型，负责约束边界输入或输出格式。
class SessionPinRequest(APIModel):
    pinned: bool


# 接口数据模型，负责约束边界输入或输出格式。
class ChatSessionOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class UserMessageOut(APIModel):
    message_id: str
    session_id: str
    account_id: str | None = None
    client_message_id: str
    content: str
    attachments: list[AttachmentIn] = Field(default_factory=list)
    created_at: datetime


# 接口数据模型，负责约束边界输入或输出格式。
class AgentRunOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class UserMessageWithRunsOut(UserMessageOut):
    runs: list[AgentRunOut] = Field(default_factory=list)


# 接口数据模型，负责约束边界输入或输出格式。
class ChatSessionDetailOut(APIModel):
    session: ChatSessionOut
    messages: list[UserMessageWithRunsOut] = Field(default_factory=list)


# 接口数据模型，负责约束边界输入或输出格式。
class AgentTraceOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class AgentMessageRequest(APIModel):
    client_message_id: str = ""
    content: str
    attachments: list[AttachmentIn] = Field(default_factory=list)


# 接口数据模型，负责约束边界输入或输出格式。
class GuideSuggestionRequest(APIModel):
    page: str
    context: dict[str, Any] = Field(default_factory=dict)
    limit: int = 0


# 模块中的核心类型，封装相关状态和行为。
class GuideSuggestionItem(APIModel):
    id: str
    question: str
    reason: str


# 接口数据模型，负责约束边界输入或输出格式。
class ImageSearchRequest(APIModel):
    file_id: str = ""
    object_key: str = ""
    image_url: str = ""
    top_k: int = Field(default=5, ge=1, le=20)


# 接口数据模型，负责约束边界输入或输出格式。
class KnowledgeDocumentCreateRequest(APIModel):
    title: str
    doc_type: str = ""
    content: str
    source_url: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    force_reindex: bool = False


# 接口数据模型，负责约束边界输入或输出格式。
class KnowledgeDocumentOut(APIModel):
    document_id: str
    merchant_id: str
    title: str
    doc_type: str
    status: str
    chunk_count: int
    source_url: str
    content_hash: str
    created_at: datetime


# 接口数据模型，负责约束边界输入或输出格式。
class UnstructuredIngestRequest(APIModel):
    title: str = ""
    source_type: str = "text"
    source_url: str = ""
    content: str = ""
    html: str = ""
    json_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    force_reindex: bool = False
    merchant_id: str = ""


# 模块中的核心类型，封装相关状态和行为。
class UnstructuredIngestResult(APIModel):
    document: KnowledgeDocumentOut
    duplicate: bool
    text_runes: int


# 接口数据模型，负责约束边界输入或输出格式。
class StoredFileOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class CartItemOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class CartSummaryOut(APIModel):
    selected_count: int = Field(alias="selectedCount")
    total_amount: str = Field(alias="totalAmount")
    discount_amount: str = Field(alias="discountAmount")
    pay_amount: str = Field(alias="payAmount")


# 接口数据模型，负责约束边界输入或输出格式。
class CartOut(APIModel):
    items: list[CartItemOut] = Field(default_factory=list)
    summary: CartSummaryOut


# 接口数据模型，负责约束边界输入或输出格式。
class CartAddRequest(APIModel):
    product_id: str = Field(alias="productId")
    sku_id: str = Field(default="", alias="skuId")
    quantity: int = Field(default=1, ge=1)


# 接口数据模型，负责约束边界输入或输出格式。
class CartPatchRequest(APIModel):
    quantity: int | None = Field(default=None, ge=1)
    selected: bool | None = None


# 接口数据模型，负责约束边界输入或输出格式。
class PaymentRequest(APIModel):
    method: str = "mock_balance"


# 接口数据模型，负责约束边界输入或输出格式。
class CancelOrderRequest(APIModel):
    reason: str = ""


# 接口数据模型，负责约束边界输入或输出格式。
class OrderItemOut(APIModel):
    order_item_id: str
    product_id: str
    sku_id: str | None = None
    name: str
    image_url: str
    price: str
    quantity: int
    merchant_id: str
    merchant_name: str


# 接口数据模型，负责约束边界输入或输出格式。
class OrderOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class DiscountLineOut(APIModel):
    type: str
    id: str
    name: str
    amount: str
    description: str | None = None


# 接口数据模型，负责约束边界输入或输出格式。
class DiscountPreviewOut(APIModel):
    total_amount: str
    discount_amount: str
    pay_amount: str
    lines: list[DiscountLineOut] = Field(default_factory=list)


# 接口数据模型，负责约束边界输入或输出格式。
class PaymentOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class CouponOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class UserCouponOut(APIModel):
    user_coupon_id: str
    coupon_id: str
    account_id: str
    status: str
    order_id: str = ""
    claimed_at: datetime
    used_at: datetime | None = None
    coupon: CouponOut


# 接口数据模型，负责约束边界输入或输出格式。
class PromotionRuleRequest(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class PromotionRuleOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class ProductUpsertRequest(APIModel):
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



# 接口数据模型，负责约束边界输入或输出格式。
class ReviewRequest(APIModel):
    rating: int = Field(ge=1, le=5)
    content: str
    tags: list[str] = Field(default_factory=list)


# 接口数据模型，负责约束边界输入或输出格式。
class ReviewReplyRequest(APIModel):
    reply: str


# 接口数据模型，负责约束边界输入或输出格式。
class ReviewStatusRequest(APIModel):
    status: str


# 接口数据模型，负责约束边界输入或输出格式。
class ProductReviewOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class StatusRequest(APIModel):
    status: str


# 接口数据模型，负责约束边界输入或输出格式。
class ConfigUpdateRequest(APIModel):
    value: str
    value_type: str = "string"
    description: str = ""
    is_secret: bool | None = None


# 接口数据模型，负责约束边界输入或输出格式。
class ConfigOut(APIModel):
    config_key: str
    config_value: str
    value_type: str
    description: str
    domain: str = ""
    is_secret: bool
    updated_at: datetime


# 接口数据模型，负责约束边界输入或输出格式。
class PromptDraftRequest(APIModel):
    title: str = ""
    content: str
    description: str = ""


# 接口数据模型，负责约束边界输入或输出格式。
class PromptOut(APIModel):
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


# 接口数据模型，负责约束边界输入或输出格式。
class PromptPublishRecordOut(APIModel):
    record_id: str
    prompt_key: str
    prompt_id: str
    version: int
    published_by: str = ""
    publish_target: str
    created_at: datetime


def amount_string(value: Decimal | int | float | str | None) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):.2f}"
