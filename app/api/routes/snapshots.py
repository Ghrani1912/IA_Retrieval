"""GET /snapshots/{domain} — Wayback CDX cache stats endpoint."""
from __future__ import annotations

import logging

import asyncpg
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.pydantic_models import SnapshotStats
from app.wayback.stats import compute_snapshot_stats

logger = logging.getLogger(__name__)
router = APIRouter()

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


@router.get("/snapshots/ingested-domains")
async def list_ingested_domains():
    """Return all domains that have been ingested into website_snapshots."""
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        rows = await conn.fetch(
            "SELECT DISTINCT domain, COUNT(*) as snapshot_count, "
            "MIN(snapshot_timestamp) as earliest, MAX(snapshot_timestamp) as latest "
            "FROM website_snapshots GROUP BY domain ORDER BY domain"
        )
        return [
            {
                "domain": r["domain"],
                "snapshot_count": r["snapshot_count"],
                "earliest": r["earliest"].isoformat() if r["earliest"] else None,
                "latest": r["latest"].isoformat() if r["latest"] else None,
            }
            for r in rows
        ]
    finally:
        await conn.close()


@router.get("/snapshots/{domain}", response_model=SnapshotStats)
async def get_snapshots(domain: str) -> SnapshotStats:
    """Return CDX cache statistics for a domain.

    Served entirely from the website_snapshots DB table — never queries CDX live.
    Returns 404 if the domain has not been ingested yet.
    """
    stats = await compute_snapshot_stats(domain, DB_URL)
    if stats.total_count == 0:
        raise HTTPException(
            status_code=404,
            detail={"error": "domain_not_cached",
                    "message": f"No snapshots found for '{domain}'. "
                               f"Run POST /ingest with source_type='website' first."},
        )
    return stats
