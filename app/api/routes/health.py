"""GET /health — full service connectivity check."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import asyncpg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


async def _check_postgres() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        conn = await asyncpg.connect(DB_URL, ssl=False, timeout=3.0)
        await conn.fetchval("SELECT 1")
        await conn.close()
        return {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_opensearch() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.opensearch_url}/_cluster/health")
            resp.raise_for_status()
        return {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_qdrant() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(settings.qdrant_url)
            resp.raise_for_status()
        return {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_redis() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        return {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.get("/health")
async def health_check() -> JSONResponse:
    """Full connectivity probe for all backing services.

    Returns 200 if all services healthy, 503 if any are degraded.
    """
    pg, os_, qdrant, redis = await asyncio.gather(
        _check_postgres(),
        _check_opensearch(),
        _check_qdrant(),
        _check_redis(),
    )

    services = {
        "postgres": pg,
        "opensearch": os_,
        "qdrant": qdrant,
        "redis": redis,
    }

    all_ok = all(s["status"] == "ok" for s in services.values())
    status_code = 200 if all_ok else 503
    overall = "healthy" if all_ok else "degraded"

    return JSONResponse(
        status_code=status_code,
        content={"status": overall, "services": services},
    )
