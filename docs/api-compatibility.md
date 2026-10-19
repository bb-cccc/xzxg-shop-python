# Go/Python API 兼容清单

状态：阶段 0 冻结  
基线日期：2026-10-16  
Base URL：`/api/v1`  
参考实现：`backend/src/httpapi/server.go`、`middleware.go`、`speech.go`、`domain/types.go`

本文件冻结 Python 重构期间客户端可观察到的 HTTP 契约。字段名大小写必须保持现状；资源对象中 Go `omitempty` 为空时可以省略，非空字段不能改名。详细历史接口示例仍以 `.ai/api/API接口文档_v3.md` 为准。

## 通用规则

### 鉴权和角色

```http
Authorization: Bearer <token>
```

| 角色 | 值 | 访问范围 |
|---|---|---|
| 公开 | 无 token | health、登录/注册、商品/类目/商家公开读取、促销公开读取、评测接口、静态资源 |
| 用户 | `user` | 账户、购物车、订单、优惠券、Agent、语音；文件和图片搜索也可访问 |
| 商家 | `merchant` | 账户、文件/图片搜索、`/merchant/*` |
| 管理员 | `admin` | 账户、文件/图片搜索、`/admin/*` |

未登录返回 `401 unauthorized`；角色不匹配返回 `403 forbidden`。请求会得到 `X-Request-ID`，错误 JSON 也包含同值 `request_id`。

### 错误和分页

错误对象固定为：

```json
{"code":"bad_request","message":"请求 JSON 不合法","request_id":"<request-id>"}
```

分页请求使用 `page`（默认 1，最小 1）和 `page_size`（默认 10，范围 1—100）；分页响应固定为：

```json
{"items":[],"page":1,"page_size":10,"total":0}
```

金额是字符串；时间是带时区的 RFC3339/ISO-8601 字符串；资源对象的 JSON key 以 Go struct tag 为准。

## 路由冻结表

表中的 `{id}`、`{key}`、`{run_id}` 表示路径参数；同一行的多个方法分别注册。

### 公开、认证和基础资源

| 方法 | 路径 | 权限 | 结果 |
|---|---|---|---|
| GET | `/health` | 公开 | `{"status":"ok"}` |
| POST | `/auth/login` | 公开 | `{token, account}` |
| POST | `/auth/register` | 公开 | `201 {token, account}`，只创建 user |
| POST | `/auth/logout` | 任意已登录角色 | `{ok:true}` |
| GET | `/auth/me` | 已登录 | 当前 `Account` |
| GET/PATCH | `/account/profile` | 已登录 | 当前账号；PATCH 更新 `display_name`/`nickname`/`avatar_url` |
| PATCH | `/account/contact` | 已登录 | 更新 `phone`/`email` |
| DELETE | `/account` | 已登录 | `{ok:true}` |
| POST | `/uploads/avatar` | 已登录 | `{url,mime_type,size}`；JPG/PNG/WebP，最大 2 MiB |
| GET | `/uploads/avatar/{file}` | 公开 | 静态头像字节 |
| GET | `/assets/ecommerce_agent_dataset/{path}` | 公开 | 静态数据集资源 |
| GET | `/categories/tree` | 公开 | `{items: Category[]}` |
| GET | `/merchants` | 公开 | 分页 `Merchant[]` |
| GET | `/products` | 公开 | 分页 `ProductCard[]`；query `keyword/category_id` |
| GET | `/products/{product_id}` | 公开 | `ProductDetail` |
| GET | `/products/{product_id}/skus` | 公开 | 分页 `ProductSKU[]` |
| GET | `/products/{product_id}/reviews` | 公开 | 分页 `ProductReview[]` |
| GET | `/promotions` | 公开 | 分页 `PromotionRule[]` |
| POST | `/eval/intent` | 公开 | 意图评测结果 |
| POST | `/eval/rag` | 公开 | RAG 召回评测结果 |
| POST | `/eval/products` | 公开 | 商品搜索评测结果 |
| POST | `/eval/image-search` | 公开 | 图片搜索评测结果 |

### 用户资源

| 方法 | 路径 | 请求/关键行为 |
|---|---|---|
| GET | `/coupons/available` | 分页可领取优惠券 |
| GET | `/coupons/mine` | 分页当前用户优惠券 |
| POST | `/coupons/{coupon_id}:claim` | 领取优惠券；失败 `409 claim_failed` |
| POST | `/files` | multipart 文件上传，返回 `StoredFile` |
| GET | `/files/{file_id}` | 文件下载；仅文件所有者或管理员 |
| POST | `/search/image` | `file_id/object_key/image_url` 三选一，返回相似商品 |
| GET | `/cart` | 当前购物车 `Cart` |
| GET | `/cart/discount-preview` | `DiscountPreview` |
| POST | `/cart/items` | `{product_id,sku_id?,quantity?}`；返回更新后的 `Cart` |
| PATCH | `/cart/items/{cart_item_id}` | `{quantity?,selected?}`；返回 `Cart` |
| DELETE | `/cart/items/{cart_item_id}` | 删除后返回 `Cart` |
| GET | `/orders` | 分页当前用户订单 |
| POST | `/orders:checkout` | 购物车选中项结算；返回 `{items: Order[]}` |
| GET | `/orders/{order_id}` | 订单详情 |
| POST | `/orders/{order_id}:pay` | `{method?}`；返回 `{order,payment}` |
| POST | `/orders/{order_id}:cancel` | `{reason?}`；返回 `Order` |
| POST | `/orders/{order_id}:confirm-receipt` | 确认收货；返回 `Order` |
| POST | `/orders/{order_id}/items/{order_item_id}:review` | `{rating,content,tags}`；返回 `ProductReview` |
| GET | `/speech/realtime` | WebSocket 代理，query `sample_rate=16000` |
| GET | `/speech/tts/config` | 返回当前 TTS 能力配置 |
| POST | `/speech/tts` | `{text,voice?}`；成功返回音频字节 |
| POST | `/agent/guide-suggestions` | 页面上下文向导问题，返回最多 3 条 `items` |
| GET | `/agent/sessions` | 分页会话列表 |
| GET | `/agent/sessions/search` | query `q`，分页会话搜索 |
| POST | `/agent/sessions` | `{title?}`；返回 `ChatSession` |
| GET | `/agent/sessions/{session_id}` | `ChatSessionDetail` |
| PATCH | `/agent/sessions/{session_id}` | `{title,summary}`；返回 `ChatSession` |
| DELETE | `/agent/sessions/{session_id}` | `{session_id,status:"deleted"}` |
| POST | `/agent/sessions/{session_id}:pin` | `{pinned}`；返回 `ChatSession` |
| POST | `/agent/sessions/{session_id}:summarize` | 返回更新后的 `ChatSession` |
| POST | `/agent/sessions/{session_id}/messages:stream` | `{client_message_id,content,attachments}`；SSE |
| POST | `/agent/runs/{run_id}:cancel` | 返回 `{run_id,status:"canceled"}` |
| GET | `/agent/runs/{run_id}/trace` | `{items: AgentTraceEvent[]}` |

### 商家资源

所有 `/merchant/*` 均要求 `role=merchant`。`merchant_id` 由当前 token 决定，客户端提交的归属字段不能越权覆盖。

| 方法 | 路径 |
|---|---|
| GET/POST | `/merchant/documents` |
| POST | `/merchant/unstructured-ingestions` |
| GET/PATCH | `/merchant/orders`、`/merchant/orders/{order_id}` |
| GET/POST/PATCH | `/merchant/promotions`、`/merchant/promotions/{promotion_id}` |
| GET/POST | `/merchant/reviews`、`/merchant/reviews/{review_id}:reply` |
| POST/PATCH/DELETE | `/merchant/products`、`/merchant/products/{product_id}` |

列表接口使用统一分页；创建/更新接口返回对应 domain 对象；状态非法返回 `400 bad_status`，资源不存在返回对应 `*_not_found`。

### 管理员资源

所有 `/admin/*` 均要求 `role=admin`。

| 方法 | 路径 |
|---|---|
| GET/PATCH | `/admin/accounts`、`/admin/accounts/{account_id}` |
| GET/PATCH | `/admin/configs`、`/admin/configs/{config_key}` |
| GET/PATCH/POST | `/admin/prompts`、`/admin/prompts/{prompt_key}`、`/admin/prompts/{prompt_key}/publish` |
| GET | `/admin/vector/status` |
| GET | `/admin/evals`、`/admin/evals/reports/{report_id}` |
| GET | `/admin/agent/runs`、`/admin/agent/runs/{run_id}/trace` |
| GET | `/admin/documents` |
| POST | `/admin/unstructured-ingestions` |
| GET/PATCH | `/admin/orders`、`/admin/orders/{order_id}` |
| GET/POST/PATCH | `/admin/promotions`、`/admin/promotions/{promotion_id}` |
| GET/PATCH | `/admin/reviews`、`/admin/reviews/{review_id}` |
| GET/PATCH | `/admin/products`、`/admin/products/{product_id}` |
| GET/PATCH | `/admin/merchants`、`/admin/merchants/{merchant_id}` |

## 核心 JSON 对象

### 账号、会话和 run

```json
{
  "account_id":"acct_xxx","username":"user","display_name":"用户",
  "avatar_url":"/api/v1/uploads/avatar/a.webp","phone":"","email":"",
  "role":"user","merchant_id":"","status":"active","created_at":"2026-10-16T00:00:00+08:00"
}
```

```json
{
  "session_id":"sess_xxx","title":"AI 导购","summary":"","message_count":0,
  "last_message_at":"2026-10-16T00:00:00+08:00","created_at":"2026-10-16T00:00:00+08:00","updated_at":"2026-10-16T00:00:00+08:00"
}
```

发送消息必须支持客户端幂等键：`(account_id, session_id, client_message_id)` 唯一。重复提交返回已有 run 的 SSE 快照，事件为 `message_start → error(code=duplicate_message) → message_end`，不会重新执行 Agent。

### 商品和 block

商品公开字段使用 camelCase：`productId/skuId/merchantId/merchantName/categoryId/imageUrl/marketPrice/stockStatus/sellingPoints/recommendReason/riskNotes`。订单、购物车、Trace 和管理对象沿用 Go 的 snake_case 字段。

Agent block 最小字段集合如下，未知字段必须被客户端安全忽略：

```json
{"type":"product_refs","product_ids":["p_001"]}
{"type":"comparison_table","columns":["商品","价格"],"rows":[{"productId":"p_001","values":["商品 A","2999.00"]}]}
{"type":"cart_state","cart":{"items":[],"summary":{"selectedCount":0,"totalAmount":"0.00","discountAmount":"0.00","payAmount":"0.00"}}
{"type":"order_summary","orders":[]}
{"type":"citation","citation":{"chunkId":"ck_001","title":"售后政策","snippet":"...","source":"doc_001"}}
{"type":"warning","code":"need_clarification","message":"请明确要操作的商品。"}
```

## 错误码基线

通用错误：`bad_request`、`not_found`、`method_not_allowed`、`unauthorized`、`forbidden`、`rate_limited`、`stream_unsupported`。

认证/账户：`empty_credential`、`invalid_credential`、`invalid_register_input`、`username_exists`、`account_not_found`、`empty_profile`、`bad_display_name`、`bad_contact`、`bad_email`。

Agent：`empty_content`、`session_not_found`、`create_message_failed`、`create_run_failed`、`run_not_found`、`duplicate_message`、`canceled`。

商品/交易：`product_not_found`、`empty_product_id`、`cart_item_not_found`、`empty_cart`、`pay_failed`、`cancel_failed`、`confirm_failed`、`review_failed`、`order_not_found`。

文件/语音：`missing_file`、`file_too_large`、`bad_image_type`、`speech_not_enabled`、`bad_sample_rate`、`tts_not_enabled`、`empty_text`、`text_too_long`、`tts_failed`。

Python 新增错误必须使用新 code；不能复用已有 code 改变含义。
