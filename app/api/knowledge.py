from __future__ import annotations



from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_current_account, get_repository
from app.core.errors import APIError
from app.domain.models import Account, KnowledgeDocument
from app.domain.schemas import KnowledgeDocumentCreateRequest, KnowledgeDocumentOut, PageResponse
from app.repositories.sql import SQLRepository


router = APIRouter(tags=["knowledge"])


def _merchant_id(account: Account) -> str:
    if account.role == "merchant" and account.merchant_id:
        return account.merchant_id
    raise APIError(403, "forbidden", "当前账号没有知识库权限")


def _out(item: KnowledgeDocument) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(item)


@router.post("/merchant/documents", response_model=KnowledgeDocumentOut)
async def create_document(
    request: KnowledgeDocumentCreateRequest,
    account: Account = Depends(get_current_account),
    repository: SQLRepository = Depends(get_repository),
) -> KnowledgeDocumentOut:
    merchant_id = _merchant_id(account)
    if not request.title.strip() or not request.content.strip():
        raise APIError(400, "empty_document", "文档标题和内容不能为空")
    item = await repository.ingest_knowledge_document(
        merchant_id, request.title, request.doc_type.strip() or "product_detail", request.content,
        request.source_url, request.metadata, request.force_reindex,
    )
    return _out(item)


@router.get("/merchant/documents", response_model=PageResponse[KnowledgeDocumentOut])
async def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    account: Account = Depends(get_current_account),
    repository: SQLRepository = Depends(get_repository),
) -> PageResponse[KnowledgeDocumentOut]:
    merchant_id = _merchant_id(account)
    items, total = await repository.list_knowledge_documents(merchant_id, page, page_size)
    return PageResponse(items=[_out(item) for item in items], page=page, page_size=page_size, total=total)

