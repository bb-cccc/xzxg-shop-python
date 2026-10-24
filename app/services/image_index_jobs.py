from __future__ import annotations

# 编排跨 Repository 的业务事务。

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.integrations.image_embedding import build_image_embedder
from app.rag.image_index import index_product_images
from app.rag.service import build_image_vector_provider
from app.repositories.sql import SQLRepository


@dataclass(slots=True)
class ImageIndexJob:
    job_id: str
    status: str = "queued"
    limit: int = 0
    force: bool = False
    report: dict[str, object] | None = None
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str = ""
    finished_at: str = ""

    def payload(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "limit": self.limit,
            "force": self.force,
            "report": self.report,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class ImageIndexJobManager:
    """Run image indexing outside the request transaction and expose state."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.jobs: dict[str, ImageIndexJob] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger("xzxg.image_index")

    async def submit(self, settings, *, limit: int = 0, force: bool = False) -> ImageIndexJob:
        async with self._lock:
            for old_id in list(self.jobs):
                if len(self.jobs) <= 100:
                    break
                old = self.jobs[old_id]
                if old.status not in {"queued", "running"}:
                    self.jobs.pop(old_id, None)
                    self.tasks.pop(old_id, None)
            active = next((item for item in self.jobs.values() if item.status in {"queued", "running"}), None)
            if active is not None:
                return active
            job = ImageIndexJob(job_id=f"imgidx_{secrets.token_urlsafe(10)}", limit=limit, force=force)
            self.jobs[job.job_id] = job
            self.tasks[job.job_id] = asyncio.create_task(self._run(job, settings))
            return job

    async def _run(self, job: ImageIndexJob, settings) -> None:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc).isoformat()
        try:
            async with self.session_factory() as session:
                repository = SQLRepository(session)
                report = await index_product_images(
                    repository,
                    build_image_embedder(settings),
                    limit=job.limit,
                    force=job.force,
                    vector_provider=build_image_vector_provider(settings),
                )
                job.report = report.payload()
                job.status = "completed_with_errors" if report.failed or report.vector_failed else "completed"
        except asyncio.CancelledError:
            job.status = "canceled"
            raise
        except Exception as error:  # task boundary: persist failure instead of losing the job
            self.logger.exception("image index job failed", extra={"job_id": job.job_id})
            job.status = "failed"
            job.error = type(error).__name__
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()

    async def get(self, job_id: str) -> ImageIndexJob | None:
        async with self._lock:
            return self.jobs.get(job_id)

    async def close(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
