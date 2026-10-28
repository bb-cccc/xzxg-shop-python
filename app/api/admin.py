from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
import json
from pathlib import Path
from fastapi import APIRouter, Body, Depends, Query, Request
import logging
from sqlalchemy import select

from app.agent.output import event
from app.agent.planner import IntentPlanner
from app.agent.tools import ToolRegistry, order_payload
from app.api.auth import account_schema
from app.api.commerce import coupon_out, review_out
from app.api.dependencies import get_current_admin, get_repository
from app.api.dependencies import get_app_settings
from app.api.merchant import _promotion, _promotion_values
from app.core.config import Settings
from app.core.errors import APIError
from app.domain.models import Account, AgentPrompt, AgentRun, AppConfig, ProductReview, PromotionRule
from app.domain.schemas import (
    AccountOut,
    ConfigOut,
    ConfigUpdateRequest,
    CouponOut,
    KnowledgeDocumentOut,
    PageResponse,
    PromptDraftRequest,
    PromptOut,
    PromptPublishRecordOut,
    ProductReviewOut,
    PromotionRuleOut,
    PromotionRuleRequest,
    StatusRequest,
    ImageSearchRequest,
)
from app.integrations.image_embedding import ImageEmbeddingError, build_image_embedder
from app.integrations.image_search import ImageSearchService
from app.integrations.nacos import NacosUnavailable
from app.integrations.objectstore import build_object_store
from app.repositories.sql import SQLRepository

router = APIRouter(prefix="/admin", tags=["admin"])
eval_router = APIRouter(tags=["eval"])


def _config(item: AppConfig) -> ConfigOut:
    return ConfigOut(config_key=item.config_key,
                     config_value="******" if item.is_secret and item.config_value else item.config_value,
                     value_type=item.value_type, description=item.description, domain=item.domain,
                     is_secret=item.is_secret, updated_at=item.updated_at)


def _prompt(item: AgentPrompt) -> PromptOut:
    return PromptOut(prompt_id=item.prompt_id, prompt_key=item.prompt_key, title=item.title, content=item.content,
                     status=item.status, version=item.version, description=item.description, created_by=item.created_by,
                     published_at=item.published_at, created_at=item.created_at, updated_at=item.updated_at)


@router.get("/accounts", response_model=PageResponse[AccountOut])
async def accounts(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                   _admin: Account = Depends(get_current_admin), repository: SQLRepository = Depends(get_repository)) -> \
PageResponse[AccountOut]:
    items, total = await repository.list_accounts(page, page_size)
    return PageResponse(items=[account_schema(item) for item in items], page=page, page_size=page_size, total=total)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account(account_id: str, request: StatusRequest, _admin: Account = Depends(get_current_admin),
                         repository: SQLRepository = Depends(get_repository)) -> AccountOut:
    if request.status not in {"active", "inactive", "risk"}:
        raise APIError(400, "bad_status", "账号状态不合法")
    item = await repository.update_account_status(account_id, request.status)
    if item is None:
        raise APIError(404, "account_not_found", "账号不存在")
    return account_schema(item)


@router.get("/configs", response_model=PageResponse[ConfigOut])
async def configs(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                  _admin: Account = Depends(get_current_admin), repository: SQLRepository = Depends(get_repository)) -> \
PageResponse[ConfigOut]:
    items, total = await repository.list_configs(page, page_size)
    return PageResponse(items=[_config(item) for item in items], page=page, page_size=page_size, total=total)


@router.patch("/configs/{config_key:path}", response_model=ConfigOut)
async def update_config(config_key: str, request: ConfigUpdateRequest, _admin: Account = Depends(get_current_admin),
                        repository: SQLRepository = Depends(get_repository)) -> ConfigOut:
    existing = await repository.session.get(AppConfig, config_key)
    is_secret = request.is_secret if request.is_secret is not None else (
                "key" in config_key.lower() or "secret" in config_key.lower())
    value = existing.config_value if request.value == "******" and existing is not None else request.value
    item = await repository.upsert_config(config_key, value, request.value_type, request.description, is_secret)
    return _config(item)


@router.get("/prompts")
async def prompts(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                  _admin: Account = Depends(get_current_admin), repository: SQLRepository = Depends(get_repository)) -> \
dict[str, object]:
    items, total = await repository.list_prompts(page, page_size)
    records = await repository.list_prompt_publish_records(limit=20)
    return {"items": [_prompt(item) for item in items], "page": page, "page_size": page_size, "total": total,
            "publish_records": [PromptPublishRecordOut.model_validate(item) for item in records]}


@router.patch("/prompts/{prompt_key:path}", response_model=PromptOut)
async def save_prompt(prompt_key: str, request: PromptDraftRequest, admin: Account = Depends(get_current_admin),
                      repository: SQLRepository = Depends(get_repository)) -> PromptOut:
    if not prompt_key.strip() or not request.content.strip():
        raise APIError(400, "save_prompt_failed", "prompt key 和内容不能为空")
    return _prompt(await repository.save_prompt_draft(prompt_key, request.title, request.content, request.description,
                                                      admin.account_id))


@router.post("/prompts/{prompt_key:path}/publish")
async def publish_prompt(prompt_key: str, request: Request, admin: Account = Depends(get_current_admin),
                         repository: SQLRepository = Depends(get_repository)) -> dict[str, object]:
    result = await repository.publish_prompt(prompt_key, admin.account_id, "database")
    if result is None:
        raise APIError(400, "publish_prompt_failed", "prompt 不存在")
    prompt, record = result
    nacos = getattr(request.app.state, "nacos", None)
    if nacos is not None and nacos.enabled:
        try:
            prompts, _total = await repository.list_prompts(page=1, page_size=1000)
            await nacos.publish(
                {"prompts": [{"prompt_id": item.prompt_id, "prompt_key": item.prompt_key, "title": item.title,
                              "content": item.content, "status": item.status, "version": item.version,
                              "description": item.description} for item in prompts if item.status == "active"]},
                nacos.prompt_data_id,
            )
            record.publish_target = "nacos"
            record.nacos_data_id = nacos.prompt_data_id
            await repository.session.commit()
        except NacosUnavailable:
            logging.getLogger("xzxg.config").exception("Prompt published to database but Nacos publication failed",
                                                       extra={"prompt_key": prompt_key})
    return {"prompt": _prompt(prompt), "record": PromptPublishRecordOut.model_validate(record)}


def _eval_type(dataset_id: str) -> str:
    if "no_inventory" in dataset_id:
        return "agent_no_inventory"
    if "rag" in dataset_id:
        return "rag_recall"
    if "intent" in dataset_id:
        return "intent"
    if "image_search" in dataset_id:
        return "image_search_eval"
    if "agent" in dataset_id:
        return "agent_e2e"
    return "custom"


def _eval_dataset_name(dataset_id: str) -> str:
    return {
        "rag_recall_cases": "RAG 召回测试集",
        "intent_cases": "意图识别测试集",
        "image_search_cases": "图片搜索测试集",
        "agent_e2e_queries": "Agent 端到端测试集",
        "agent_no_inventory_cases": "Agent 无库存误挂品测试集",
    }.get(dataset_id, dataset_id)


def _quality_root() -> Path:
    return Path(__file__).resolve().parents[3] / "quality"


def _eval_datasets() -> list[dict[str, object]]:
    root = _quality_root() / "data" / "eval"
    result: list[dict[str, object]] = []
    for path in sorted(root.glob("*.jsonl")):
        try:
            count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if
                        line.strip() and not line.lstrip().startswith("#"))
        except OSError:
            count = 0
        dataset_id = path.stem
        result.append({"id": dataset_id, "type": _eval_type(dataset_id), "name": _eval_dataset_name(dataset_id),
                       "path": str(path).replace("\\", "/"), "case_count": count,
                       "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
    return result


def _eval_reports() -> list[dict[str, object]]:
    root = _quality_root() / "reports"
    result: list[dict[str, object]] = []
    for path in sorted(root.glob("*/*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        variants = payload.get("variants") or []
        best = max(variants, key=lambda item: (float(item.get("hit_rate_at_k") or 0), float(item.get("mrr") or 0)),
                   default={})
        total = int(payload.get("total") or payload.get("total_cases") or best.get("total") or 0)
        evaluated = int(payload.get("evaluated") or best.get("total") or 0)
        hits = int(payload.get("hits") or best.get("hits") or 0)
        pass_rate = float(
            payload.get("pass_rate") or payload.get("accuracy") or payload.get("recall_case_hit_rate") or payload.get(
                "hit_rate_at_k") or best.get("hit_rate_at_k") or 0)
        report_id = f"{path.parent.name}/{path.stem}"
        result.append({"id": report_id, "type": payload.get("type", ""), "dataset": payload.get("dataset", ""),
                       "path": str(path).replace("\\", "/"), "generated_at": payload.get("generated_at",
                                                                                         datetime.fromtimestamp(
                                                                                             path.stat().st_mtime,
                                                                                             timezone.utc).isoformat()),
                       "total": total, "evaluated": evaluated, "hits": hits, "pass_rate": pass_rate})
    return result[:50]


@router.get("/evals")
async def eval_dashboard(_admin: Account = Depends(get_current_admin)) -> dict[str, object]:
    datasets = _eval_datasets()
    reports = _eval_reports()
    suite_defs = [("rag_retriever_eval", "RAG 检索召回", "tool", "rag_recall_cases"),
                  ("product_search_eval", "商品召回重排", "tool", "rag_recall_cases"),
                  ("image_search_eval", "图片搜索", "tool", "image_search_cases"),
                  ("intent", "意图识别", "tool", "intent_cases"),
                  ("non_guide_intent", "非导购服务域识别", "tool", "non_guide_intent_cases"),
                  ("agent_e2e", "导购 Agent 端到端", "agent", "agent_e2e_queries"),
                  ("agent_no_inventory", "Agent 无库存误挂品", "agent", "agent_no_inventory_cases")]
    dataset_ids = {str(item["id"]) for item in datasets}
    suites = []
    for suite_id, name, scope, dataset_id in suite_defs:
        latest = next((str(item["id"]) for item in reports if
                       str(item.get("type", "")) == suite_id or suite_id in str(item.get("type", ""))), "")
        suites.append({"id": suite_id, "name": name, "scope": scope,
                       "dataset_id": dataset_id if dataset_id in dataset_ids else "", "latest_report_id": latest,
                       "command": "python -m quality.python_eval all"})
    return {"datasets": datasets, "reports": reports, "tools": suites}


@router.get("/evals/reports/{report_id:path}")
async def eval_report(report_id: str, _admin: Account = Depends(get_current_admin)) -> dict[str, object]:
    if not report_id or ".." in report_id or "/" not in report_id:
        raise APIError(400, "bad_report_id", "报告 ID 应为 run/file")
    path = _quality_root() / "reports" / (report_id.split("/", 1)[0]) / (report_id.split("/", 1)[1] + ".json")
    if not path.is_file():
        raise APIError(404, "report_not_found", "测评报告不存在")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise APIError(500, "bad_report", "测评报告 JSON 不合法") from error
    return {"id": report_id, "path": str(path).replace("\\", "/"), "summary": payload,
            "results": payload.get("results", []), "raw": payload}


@router.get("/agent/runs")
async def admin_runs(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                     _admin: Account = Depends(get_current_admin),
                     repository: SQLRepository = Depends(get_repository)) -> dict[str, object]:
    from app.api.agent import run_out
    items, total = await repository.list_admin_runs(page, page_size)
    return {"items": [run_out(item) for item in items], "page": page, "page_size": page_size, "total": total}


@router.get("/agent/runs/{run_id}/trace")
async def admin_trace(run_id: str, _admin: Account = Depends(get_current_admin),
                      repository: SQLRepository = Depends(get_repository)) -> dict[str, object]:
    if await repository.session.get(AgentRun, run_id) is None:
        raise APIError(404, "run_not_found", "执行不存在")
    from app.api.agent import trace_out
    return {"items": [trace_out(item) for item in await repository.list_admin_trace(run_id)]}


@router.get("/documents", response_model=PageResponse[KnowledgeDocumentOut])
async def admin_documents(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                          _admin: Account = Depends(get_current_admin),
                          repository: SQLRepository = Depends(get_repository)) -> PageResponse[KnowledgeDocumentOut]:
    items, total = await repository.list_knowledge_documents("", page, page_size)
    return PageResponse(items=[KnowledgeDocumentOut.model_validate(item) for item in items], page=page,
                        page_size=page_size, total=total)


@router.get("/orders")
async def admin_orders(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                       _admin: Account = Depends(get_current_admin),
                       repository: SQLRepository = Depends(get_repository)) -> dict[str, object]:
    await repository.expire_pending_orders()
    rows, total = await repository.list_orders(page=page, page_size=page_size)
    return {"items": [order_payload(order, items, merchant.name) for order, merchant, items in rows], "page": page,
            "page_size": page_size, "total": total}


@router.patch("/orders/{order_id}")
async def admin_order_status(order_id: str, request: StatusRequest, _admin: Account = Depends(get_current_admin),
                             repository: SQLRepository = Depends(get_repository)) -> dict[str, object]:
    if request.status not in {"pending_ship", "shipped", "completed", "canceled", "refund_requested", "refunded",
                              "closed_timeout"}:
        raise APIError(400, "bad_status", "订单状态不合法")
    result = await repository.update_order_status(order_id, request.status)
    if result is None:
        raise APIError(409, "order_status_update_failed", "订单不存在或当前状态不允许更新")
    order, merchant, items = result
    return order_payload(order, items, merchant.name)


@router.get("/promotions", response_model=PageResponse[PromotionRuleOut])
async def admin_promotions(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                           _admin: Account = Depends(get_current_admin),
                           repository: SQLRepository = Depends(get_repository)) -> PageResponse[PromotionRuleOut]:
    items, total = await repository.list_promotions("", page, page_size)
    return PageResponse(items=[_promotion(item) for item in items], page=page, page_size=page_size, total=total)


@router.post("/promotions", response_model=PromotionRuleOut)
async def admin_create_promotion(request: PromotionRuleRequest, _admin: Account = Depends(get_current_admin),
                                 repository: SQLRepository = Depends(get_repository)) -> PromotionRuleOut:
    now = datetime.now(timezone.utc)
    threshold, discount, rate = _promotion_values(request)
    item = PromotionRule(promotion_id=repository._new_id("promo"), name=request.name.strip(), scope=request.scope,
                         merchant_id=request.merchant_id, product_id=request.product_id,
                         category_id=request.category_id, type=request.type, threshold_amount=threshold,
                         discount_amount=discount, discount_rate=rate, stackable=request.stackable,
                         start_at=request.start_at or now, end_at=request.end_at or now.replace(year=now.year + 1),
                         status=request.status)
    return _promotion(await repository.create_promotion(item))


@router.patch("/promotions/{promotion_id}", response_model=PromotionRuleOut)
async def admin_update_promotion(promotion_id: str, request: StatusRequest,
                                 _admin: Account = Depends(get_current_admin),
                                 repository: SQLRepository = Depends(get_repository)) -> PromotionRuleOut:
    if request.status not in {"active", "inactive"}:
        raise APIError(400, "bad_status", "促销状态不合法")
    item = await repository.update_promotion_status(promotion_id, request.status)
    if item is None:
        raise APIError(404, "promotion_not_found", "促销不存在")
    return _promotion(item)


@router.get("/reviews", response_model=PageResponse[ProductReviewOut])
async def admin_reviews(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                        _admin: Account = Depends(get_current_admin),
                        repository: SQLRepository = Depends(get_repository)) -> PageResponse[ProductReviewOut]:
    items, total = await repository.list_product_reviews("", page, page_size, all_status=True)
    return PageResponse(items=[review_out(item) for item in items], page=page, page_size=page_size, total=total)


@router.patch("/reviews/{review_id}", response_model=ProductReviewOut)
async def admin_update_review(review_id: str, request: StatusRequest, _admin: Account = Depends(get_current_admin),
                              repository: SQLRepository = Depends(get_repository)) -> ProductReviewOut:
    if request.status not in {"visible", "hidden", "deleted"}:
        raise APIError(400, "bad_status", "评价状态不合法")
    item = await repository.update_review_status(review_id, request.status)
    if item is None:
        raise APIError(404, "review_not_found", "评价不存在")
    return review_out(item)


@router.get("/products")
async def admin_products(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                         _admin: Account = Depends(get_current_admin),
                         repository: SQLRepository = Depends(get_repository)) -> dict[str, object]:
    from app.api.products import product_card
    items, total = await repository.list_admin_products(page, page_size)
    return {"items": [product_card(product, merchant, sku) for product, merchant, sku in items], "page": page,
            "page_size": page_size, "total": total}


@router.patch("/products/{product_id}")
async def admin_product_status(product_id: str, request: StatusRequest, _admin: Account = Depends(get_current_admin),
                               repository: SQLRepository = Depends(get_repository)):
    if request.status not in {"active", "inactive", "deleted", "risk"}:
        raise APIError(400, "bad_status", "商品状态不合法")
    item = await repository.update_product_status(product_id, request.status)
    if item is None:
        raise APIError(404, "product_not_found", "商品不存在")
    row = await repository.get_product_record(product_id)
    return {"product_id": item.product_id, "status": item.status} if row is None else {"product_id": item.product_id,
                                                                                       "status": item.status}


@router.get("/merchants", response_model=PageResponse[dict[str, object]])
async def admin_merchants(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                          _admin: Account = Depends(get_current_admin),
                          repository: SQLRepository = Depends(get_repository)) -> PageResponse[dict[str, object]]:
    items, total = await repository.list_merchants_admin(page, page_size)
    return PageResponse(items=[
        {"merchantId": item.merchant_id, "name": item.name, "logoUrl": item.logo_url, "description": item.description,
         "servicePhone": item.service_phone, "status": item.status} for item in items], page=page, page_size=page_size,
                        total=total)


@router.patch("/merchants/{merchant_id}")
async def admin_merchant_status(merchant_id: str, request: StatusRequest, _admin: Account = Depends(get_current_admin),
                                repository: SQLRepository = Depends(get_repository)) -> dict[str, object]:
    if request.status not in {"active", "inactive", "risk"}:
        raise APIError(400, "bad_status", "商家状态不合法")
    item = await repository.update_merchant_status(merchant_id, request.status)
    if item is None:
        raise APIError(400, "merchant_not_found", "商家不存在")
    return {"merchantId": item.merchant_id, "name": item.name, "logoUrl": item.logo_url,
            "description": item.description, "servicePhone": item.service_phone, "status": item.status}


@router.post("/eval/intent")
async def eval_intent(payload: dict[str, object] = Body(...), _admin: Account = Depends(get_current_admin)) -> dict[
    str, str]:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise APIError(400, "empty_query", "query 不能为空")
    plan = IntentPlanner().classify_for_evaluation(query)
    return {"query": query, "route": plan.evaluation_route or plan.route,
            "intent": plan.evaluation_intent or plan.intent, "level": plan.level,
            "secondary_level": plan.secondary_level}


@router.post("/eval/rag")
async def eval_rag(payload: dict[str, object] = Body(...), _admin: Account = Depends(get_current_admin),
                   repository: SQLRepository = Depends(get_repository),
                   settings: Settings = Depends(get_app_settings)) -> dict[str, object]:
    query = str(payload.get("keyword") or payload.get("query") or "").strip()
    if not query:
        raise APIError(400, "empty_keyword", "keyword 不能为空")
    limit = int(payload.get("top_k") or 5)
    result = await ToolRegistry(repository, settings).search_knowledge(query, max(1, min(limit, 20)))
    return {"keyword": query, "items": result.result.get("items", []), "trace": result.result.get("trace", {})}


@router.post("/eval/products")
async def eval_products(payload: dict[str, object] = Body(...), _admin: Account = Depends(get_current_admin),
                        repository: SQLRepository = Depends(get_repository),
                        settings: Settings = Depends(get_app_settings)) -> dict[str, object]:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise APIError(400, "empty_query", "query 不能为空")
    limit = max(1, min(int(payload.get("limit") or 10), 20))
    arguments = {"constraints": payload.get("constraints", {}), "negative": payload.get("negative", {})}
    result = await ToolRegistry(repository, settings).search_products(query, limit, arguments)
    return {
        "query": query,
        "items": result.result.get("items", []),
        "product_ids": result.product_ids,
        "candidate_product_ids": result.result.get("candidate_product_ids", []),
        "dropped_product_ids": result.result.get("dropped_product_ids", []),
        "relevance_status": result.result.get("relevance_status", "no_match"),
        "relevance_reason": result.result.get("relevance_reason", ""),
        "rerank": result.result.get("rerank", {}),
    }


@router.post("/eval/image-search")
async def eval_image_search(request: ImageSearchRequest, _admin: Account = Depends(get_current_admin),
                            repository: SQLRepository = Depends(get_repository), settings=Depends(get_app_settings)) -> \
dict[str, object]:
    if not (request.file_id.strip() or request.object_key.strip() or request.image_url.strip()):
        raise APIError(400, "empty_image", "file_id、object_key 或 image_url 至少传一个")
    from app.rag.service import build_image_vector_provider
    service = ImageSearchService(repository, settings, build_object_store(settings), build_image_embedder(settings),
                                 is_admin=True, vector_provider=build_image_vector_provider(settings))
    try:
        return await service.search(file_id=request.file_id, object_key=request.object_key, image_url=request.image_url,
                                    top_k=request.top_k)
    except (ImageEmbeddingError, OSError) as error:
        raise APIError(400, "image_embedding_failed", "图片解析失败") from error


eval_router.add_api_route("/eval/intent", eval_intent, methods=["POST"])
eval_router.add_api_route("/eval/rag", eval_rag, methods=["POST"])
eval_router.add_api_route("/eval/products", eval_products, methods=["POST"])
eval_router.add_api_route("/eval/image-search", eval_image_search, methods=["POST"])
