"""GET /corpus/stats — live corpus statistics for the UI."""
from __future__ import annotations

import logging

import asyncpg
from fastapi import APIRouter

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


@router.get("/corpus/stats")
async def corpus_stats():
    """Return live counts of sources and chunks in the database."""
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        total_sources = await conn.fetchval("SELECT COUNT(*) FROM sources")
        total_chunks = await conn.fetchval("SELECT COUNT(*) FROM chunks")
        sources_with_chunks = await conn.fetchval(
            "SELECT COUNT(DISTINCT source_id) FROM chunks WHERE source_id IS NOT NULL"
        )
        by_collection = await conn.fetch(
            """
            SELECT
                COALESCE(collection, 'other') AS collection,
                COUNT(DISTINCT s.id) AS sources,
                COUNT(c.id) AS chunks
            FROM sources s
            LEFT JOIN chunks c ON c.source_id = s.id
            GROUP BY collection
            HAVING COUNT(c.id) > 0
            ORDER BY chunks DESC
            """
        )
    finally:
        await conn.close()

    collections = [
        {"name": r["collection"], "sources": r["sources"], "chunks": r["chunks"]}
        for r in by_collection
    ]

    return {
        "total_sources": total_sources,
        "sources_with_chunks": sources_with_chunks,
        "total_chunks": total_chunks,
        "collections": collections,
    }
