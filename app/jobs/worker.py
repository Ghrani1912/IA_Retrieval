"""arq background worker — orchestrates the full ingestion pipeline.

Usage:
    python -m arq app.jobs.worker.WorkerSettings

Pipeline branches on source_type:
    "website" → CDX stats-only via get_snapshots() (Phase 5 hardened).
                 Content fetch is on-demand, NOT in this job.
    "texts"   → IA discover → fetch_fulltext → clean → chunk → embed → index
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

import asyncpg

from app.config import settings

logger = logging.getLogger("app.jobs.worker")

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


# ---------------------------------------------------------------------------
# Job status helpers
# ---------------------------------------------------------------------------

async def _update_job(
    conn: asyncpg.Connection,
    job_id: str,
    *,
    status: str | None = None,
    sources_total: int | None = None,
    sources_done: int | None = None,
    chunks_created: int | None = None,
    error_step: str | None = None,
    error_msg: str | None = None,
) -> None:
    """Update ingestion_jobs row with current progress."""
    sets: list[str] = ["updated_at = now()"]
    params: list = []
    idx = 1

    if status is not None:
        sets.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if sources_total is not None:
        sets.append(f"sources_total = ${idx}")
        params.append(sources_total)
        idx += 1
    if sources_done is not None:
        sets.append(f"sources_done = ${idx}")
        params.append(sources_done)
        idx += 1
    if chunks_created is not None:
        sets.append(f"chunks_created = ${idx}")
        params.append(chunks_created)
        idx += 1
    if error_step is not None:
        sets.append(f"error_step = ${idx}")
        params.append(error_step)
        idx += 1
    if error_msg is not None:
        sets.append(f"error_msg = ${idx}")
        params.append(error_msg)
        idx += 1

    params.append(job_id)
    await conn.execute(
        f"UPDATE ingestion_jobs SET {', '.join(sets)} WHERE id = ${idx}",
        *params,
    )


# ---------------------------------------------------------------------------
# Chunk persistence
# ---------------------------------------------------------------------------

async def _persist_chunks(
    conn: asyncpg.Connection,
    chunks: list,
    source_id: int,
) -> list[int]:
    """Insert chunks into Postgres and return their generated IDs."""
    if not chunks:
        return []
    ids: list[int] = []
    for chunk in chunks:
        row_id = await conn.fetchval(
            """
            INSERT INTO chunks
                (source_id, text, page_or_section, char_range_start,
                 char_range_end, token_count, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, now())
            RETURNING id
            """,
            source_id, chunk.text, chunk.page_or_section,
            chunk.char_range_start, chunk.char_range_end, chunk.token_count,
        )
        ids.append(row_id)
    return ids


# ===========================================================================
# Website branch — CDX stats-only (Phase 5 hardened get_snapshots)
# ===========================================================================

async def _run_website_ingest(
    conn: asyncpg.Connection,
    job_id: str,
    domain: str,
) -> dict:
    """Populate website_snapshots from CDX API (if stale).

    Scope: CDX metadata only — snapshot URLs, timestamps, status codes.
    Content fetch (Memento) is on-demand at query time, NOT here.
    """
    logger.info("WEBSITE branch: calling get_snapshots(%s)", domain)
    await _update_job(conn, job_id, sources_total=1, sources_done=0)

    try:
        from app.wayback.cdx import get_snapshots, CDX_MODE_HOMEPAGE

        snapshots = await get_snapshots(domain, DB_URL, mode=CDX_MODE_HOMEPAGE)
        count = len(snapshots)
        logger.info("WEBSITE branch: %s returned %d snapshots", domain, count)

        if count > 0:
            earliest = min(s.snapshot_timestamp for s in snapshots)
            latest = max(s.snapshot_timestamp for s in snapshots)
            logger.info(
                "WEBSITE branch: %s date range %s — %s",
                domain, earliest.date(), latest.date(),
            )

        await _update_job(
            conn, job_id,
            status="completed",
            sources_done=1,
            chunks_created=count,  # repurpose as snapshot count for websites
        )
        return {"job_id": job_id, "domain": domain, "snapshots": count}

    except Exception as exc:
        await _update_job(
            conn, job_id, status="failed",
            error_step="cdx_fetch", error_msg=str(exc),
        )
        logger.error("WEBSITE branch failed for %s: %s", domain, exc)
        raise


# ===========================================================================
# Texts branch — IA discover → fetch → chunk → embed → index
# ===========================================================================

async def _run_texts_ingest(
    conn: asyncpg.Connection,
    job_id: str,
    query: str,
    date_range: tuple[str | None, str | None],
    source_type: str | None,
) -> dict:
    """Full IA ingestion pipeline: discover → fetch → clean → chunk → embed → index."""
    from app.ingestion.discover import discover
    from app.ingestion.fetch import fetch_fulltext
    from app.ingestion.cleaner import clean_text
    from app.ingestion.chunker import chunk_text
    from app.ingestion.embed import embed_chunks
    from app.ingestion.index_bm25 import SourceRow, index_bm25
    from app.ingestion.index_vectors import index_vectors, write_embedding_ids_to_db
    from app.models.pydantic_models import ChunkWithEmbedding

    # arq serializes (None, None) as ("None", "None") — fix that
    clean_date_range = None
    if date_range and date_range != ("None", "None") and date_range != (None, None):
        clean_date_range = date_range

    # Step 1: Discover
    logger.info("TEXTS branch: discover(%r)", query)
    sources = await discover(query=query, date_range=clean_date_range)
    logger.info("TEXTS branch: %d sources discovered", len(sources))

    if not sources:
        await _update_job(conn, job_id, status="completed", sources_total=0, sources_done=0)
        return {"job_id": job_id, "sources": 0, "chunks": 0}

    await _update_job(conn, job_id, sources_total=len(sources), sources_done=0, chunks_created=0)

    # Step 2: Process each source
    total_chunks = 0
    sources_done = 0

    for i, src_meta in enumerate(sources):
        identifier = src_meta.ia_identifier
        logger.info("[%d/%d] Processing %s — %s", i + 1, len(sources), identifier, src_meta.title)

        try:
            row = await conn.fetchrow(
                "SELECT id FROM sources WHERE ia_identifier = $1", identifier,
            )
            if row is None:
                logger.warning("  %s not found in DB — skipping", identifier)
                continue
            source_id = row["id"]

            existing = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks WHERE source_id = $1", source_id,
            )
            if existing > 0:
                logger.info("  %s already has %d chunks — skipping", identifier, existing)
                sources_done += 1
                await _update_job(conn, job_id, sources_done=sources_done)
                continue

            raw_text = await fetch_fulltext(
                identifier=identifier,
                pub_date_raw=src_meta.pub_date,
                collection=src_meta.collection,
            )
            if raw_text is None:
                logger.info("  %s: no full text (copyright-blocked or missing)", identifier)
                sources_done += 1
                await _update_job(conn, job_id, sources_done=sources_done)
                continue

            cleaned = clean_text(raw_text)
            chunks = chunk_text(cleaned, source_id=source_id)
            logger.info("  %s: %d chunks", identifier, len(chunks))

            if not chunks:
                sources_done += 1
                await _update_job(conn, job_id, sources_done=sources_done)
                continue

            chunk_ids = await _persist_chunks(conn, chunks, source_id)

            persisted_chunks = [
                ChunkWithEmbedding(
                    id=pg_id, source_id=chunk_obj.source_id, text=chunk_obj.text,
                    page_or_section=chunk_obj.page_or_section,
                    char_range_start=chunk_obj.char_range_start,
                    char_range_end=chunk_obj.char_range_end,
                    token_count=chunk_obj.token_count,
                )
                for chunk_obj, pg_id in zip(chunks, chunk_ids)
            ]

            embedded_chunks = embed_chunks(persisted_chunks, batch_size=32)

            source_row = SourceRow(
                source_id=source_id, ia_identifier=identifier,
                source_type=source_type or "metadata_only",
                pub_date_raw=src_meta.pub_date,
                collection=src_meta.collection, language=src_meta.language,
            )
            index_bm25(persisted_chunks, {source_id: source_row}, refresh=True)
            index_vectors(embedded_chunks, {source_id: source_row})
            await write_embedding_ids_to_db(embedded_chunks, DB_URL)

            total_chunks += len(chunks)
            sources_done += 1
            await _update_job(conn, job_id, sources_done=sources_done, chunks_created=total_chunks)
            logger.info("  %s: DONE — %d chunks persisted, embedded, indexed", identifier, len(chunks))

        except Exception as exc:
            logger.error("  %s: FAILED — %s\n%s", identifier, exc, traceback.format_exc())
            sources_done += 1
            await _update_job(conn, job_id, sources_done=sources_done)

    await _update_job(conn, job_id, status="completed")
    logger.info("TEXTS branch DONE: %d sources, %d chunks", sources_done, total_chunks)
    return {"job_id": job_id, "sources": sources_done, "chunks": total_chunks}


# ===========================================================================
# Main entry point — branches on source_type
# ===========================================================================

async def run_ingestion_job(
    ctx: dict,
    job_id: str,
    query: str,
    date_range: tuple[str | None, str | None],
    source_type: str | None = None,
) -> dict:
    """arq job function — routes to the correct pipeline by source_type."""
    logger.info("=== JOB %s STARTED === query=%r source_type=%s", job_id, query, source_type)

    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        await _update_job(conn, job_id, status="running")

        if source_type == "website":
            # query IS the domain (e.g. "ai.mit.edu")
            domain = query.strip().lower()
            return await _run_website_ingest(conn, job_id, domain)
        else:
            # Default: IA document pipeline
            return await _run_texts_ingest(conn, job_id, query, date_range, source_type)

    except Exception as exc:
        try:
            await _update_job(conn, job_id, status="failed", error_step="unknown", error_msg=str(exc))
        except Exception:
            pass
        logger.error("Job %s unhandled error: %s\n%s", job_id, exc, traceback.format_exc())
        raise
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# arq WorkerSettings
# ---------------------------------------------------------------------------

from arq.connections import RedisSettings


class WorkerSettings:
    """arq worker configuration."""

    functions = [run_ingestion_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 1
    job_timeout = 3600
    max_tries = 2
    health_check_interval = 30
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": "standard",
            },
        },
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["console"],
        },
    }
