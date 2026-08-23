"""POST /ingest and GET /ingest/{job_id}/status — ingestion job endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


class DateRange(BaseModel):
    from_date: str | None = None   # "YYYY-MM-DD"
    to_date: str | None = None


class IngestRequest(BaseModel):
    query: str
    date_range: DateRange | None = None
    source_type: str | None = None
    max_results: int = 0  # 0 = no cap (discover all IA matches)


class IngestResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    sources_total: int | None
    sources_done: int
    chunks_created: int
    error_step: str | None
    error_msg: str | None
    created_at: datetime
    updated_at: datetime


@router.post("/ingest", response_model=IngestResponse, status_code=202)
async def enqueue_ingest(body: IngestRequest) -> IngestResponse:
    """Enqueue an ingestion job. Returns a job_id to poll for status.

    Note: actual worker execution requires the arq worker process to be running.
    The job is persisted to the DB immediately; the worker picks it up from Redis.
    """
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    dr = body.date_range
    date_from = None
    date_to = None
    if dr:
        try:
            if dr.from_date:
                date_from = datetime.fromisoformat(dr.from_date).date()
            if dr.to_date:
                date_to = datetime.fromisoformat(dr.to_date).date()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}")

    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        await conn.execute(
            """
            INSERT INTO ingestion_jobs
                (id, query, date_range_from, date_range_to, source_type,
                 status, sources_done, chunks_created, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, 'queued', 0, 0, $6, $6)
            """,
            job_id, body.query, date_from, date_to, body.source_type, now,
        )
    finally:
        await conn.close()

    # Enqueue to Redis/arq if available
    try:
        import arq
        from arq.connections import RedisSettings
        redis_settings = RedisSettings.from_dsn(settings.redis_url)
        redis = await arq.create_pool(redis_settings)
        await redis.enqueue_job("run_ingestion_job", job_id, body.query,
                                (str(date_from), str(date_to)), body.source_type,
                                max_results=body.max_results)
        await redis.close()
    except Exception as exc:
        logger.warning("Could not enqueue to Redis (worker may not be running): %s", exc)
        # Job is still persisted in DB — worker can pick it up if Redis comes back

    return IngestResponse(job_id=job_id)


@router.get("/ingest/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    """Poll the status of an ingestion job."""
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        row = await conn.fetchrow(
            """
            SELECT id, status, sources_total, sources_done, chunks_created,
                   error_step, error_msg, created_at, updated_at
            FROM ingestion_jobs
            WHERE id = $1
            """,
            job_id,
        )
    finally:
        await conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"})

    return JobStatusResponse(
        job_id=row["id"],
        status=row["status"],
        sources_total=row["sources_total"],
        sources_done=row["sources_done"],
        chunks_created=row["chunks_created"],
        error_step=row["error_step"],
        error_msg=row["error_msg"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
