from __future__ import annotations



import hashlib
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_app_settings, get_current_admin, get_current_merchant, get_repository
from app.core.errors import APIError
from app.core.config import Settings
from app.domain.models import Account, KnowledgeDocument
from app.domain.schemas import KnowledgeDocumentOut, UnstructuredIngestRequest, UnstructuredIngestResult
from app.ingest.unstructured import parse
from app.integrations.milvus import MilvusUnavailable
from app.repositories.sql import SQLRepository
from app.rag.service import build_vector_provider


router = APIRouter(tags=["ingestion"])
logger = logging.getLogger("xzxg.ingestion")


def _result(document: KnowledgeDocument, duplicate: bool, text_runes: int) -> UnstructuredIngestResult:
    return UnstructuredIngestResult(document=KnowledgeDocumentOut.model_validate(document), duplicate=duplicate, text_runes=text_runes)


async def _create(request: UnstructuredIngestRequest, merchant_id: str, repository: SQLRepository, settings: Settings) -> UnstructuredIngestResult:
    try:
        parsed = await parse(request)
    except (ValueError, OSError) as error:
        raise APIError(400, "parse_ingestion_failed", str(error)) from error
    digest = hashlib.sha256(parsed.content.encode("utf-8")).hexdigest()
    existing = None if request.force_reindex else await repository.get_knowledge_document_by_hash(merchant_id, digest)
    try:
        document = await repository.ingest_knowledge_document(
            merchant_id, parsed.title, parsed.doc_type, parsed.content, parsed.source_url, parsed.metadata, request.force_reindex
        )
    except SQLAlchemyError as error:
        raise APIError(500, "create_ingestion_failed", "非结构化资料入库失败") from error
    duplicate = existing is not None and not request.force_reindex
    vector_provider = build_vector_provider(settings)
    if vector_provider is not None and not duplicate:
        try:
            await vector_provider.upsert_knowledge(await repository.list_knowledge_chunks(document.document_id))
        except (MilvusUnavailable, OSError, ValueError, TypeError):
            logger.warning("Milvus knowledge indexing failed; SQL retrieval remains available", exc_info=True)
    return _result(document, duplicate, parsed.text_runes)


@router.post("/merchant/unstructured-ingestions", response_model=UnstructuredIngestResult, status_code=status.HTTP_201_CREATED)
async def merchant_ingestion(
    request: UnstructuredIngestRequest,
    account: Account = Depends(get_current_merchant),
    repository: SQLRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> UnstructuredIngestResult:
    return await _create(request, account.merchant_id or "", repository, settings)


@router.post("/admin/unstructured-ingestions", response_model=UnstructuredIngestResult, status_code=status.HTTP_201_CREATED)
async def admin_ingestion(
    request: UnstructuredIngestRequest,
    account: Account = Depends(get_current_admin),
    repository: SQLRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> UnstructuredIngestResult:
    del account
    merchant_id = request.merchant_id.strip()
    if not merchant_id:
        raise APIError(400, "empty_merchant_id", "管理员入库必须指定 merchant_id")
    return await _create(request, merchant_id, repository, settings)
