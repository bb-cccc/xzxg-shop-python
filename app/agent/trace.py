from __future__ import annotations

 

from typing import Any

from app.repositories.sql import SQLRepository


async def record_trace(
    repository: SQLRepository,
    run_id: str,
    trace_id: str,
    account_id: str,
    stage: str,
    event_type: str,
    *,
    status: str = "ok",
    model: str = "",
    duration_ms: int = 0,
    error: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    await repository.record_trace(run_id, trace_id, account_id, stage, event_type, status, model, duration_ms, error, metadata)
