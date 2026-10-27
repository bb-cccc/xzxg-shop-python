from __future__ import annotations



from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy import func, select

from app.api.dependencies import get_app_settings, get_current_admin, get_repository
from app.core.config import Settings
from app.core.errors import APIError
from app.domain.models import Account, ProductImageVector
from app.integrations.milvus import MilvusUnavailable
from app.repositories.sql import SQLRepository

router = APIRouter(prefix="/admin", tags=["admin", "vectors"])


def _image_dimension(settings: Settings) -> int:
    provider = str(settings.image_embedding_provider or "").lower()
    return 64 if provider in {"local", "local_histogram", "histogram"} else int(settings.image_embedding_dimension or 0)

@router.get('/vector/status')
async def vector_status(_admin: Account=Depends(get_current_admin), repository: SQLRepository=Depends(get_repository), settings: Settings=Depends(get_app_settings)) -> dict[str, object]:
    image_provider = str(settings.image_embedding_provider or '').strip()
    image_dimension = _image_dimension(settings)
    count_stmt = select(func.count(ProductImageVector.vector_id)).where(ProductImageVector.provider == image_provider, ProductImageVector.dimension == image_dimension)
    count = int((await repository.session.execute(count_stmt)).scalar_one() or 0)
    enabled = bool(settings.rag_vector_enabled and settings.rag_vector_provider.lower() == 'milvus')
    error = 'Milvus provider is not configured' if not enabled else ''
    states = {'service_ready': False, 'collection_ready': False, 'index_ready': count > 0, 'query_ready': False}
    collections: list[str] = []
    if enabled:
        try:
            from app.rag.service import build_image_vector_provider
            provider = build_image_vector_provider(settings)
            if provider is not None:
                collections = [provider.collection]
                states = await provider.probe_image_collection(image_dimension, has_index=count > 0)
        except (MilvusUnavailable, OSError, ValueError, TypeError) as exc:
            error = type(exc).__name__
        if not error and (not all(states.values())):
            error = 'milvus_not_ready'
    return {'enabled': enabled, 'ready': enabled and states['service_ready'] and states['collection_ready'] and states['index_ready'] and states['query_ready'] and (not error), 'states': states, 'address': settings.milvus_address if enabled else '', 'collections': collections, 'sql_vector_count': count, 'error': error, 'updated_at': datetime.now(timezone.utc).isoformat()}

@router.post('/vector/index', status_code=202)
async def rebuild_image_index(request: Request, payload: dict[str, object]=Body(default={}), _admin: Account=Depends(get_current_admin), settings: Settings=Depends(get_app_settings)) -> dict[str, object]:
    limit = max(0, min(int(payload.get('limit') or 0), 10000))
    force = bool(payload.get('force', False))
    manager = getattr(request.app.state, 'image_index_jobs', None)
    if manager is None:
        raise APIError(503, 'index_scheduler_unavailable', '图片索引任务调度器不可用')
    job = await manager.submit(settings, limit=limit, force=force)
    return job.payload()

@router.get('/vector/index/{job_id}')
async def image_index_job(job_id: str, request: Request, _admin: Account=Depends(get_current_admin)) -> dict[str, object]:
    manager = getattr(request.app.state, 'image_index_jobs', None)
    job = await manager.get(job_id) if manager is not None else None
    if job is None:
        raise APIError(404, 'index_job_not_found', '图片索引任务不存在')
    return job.payload()

