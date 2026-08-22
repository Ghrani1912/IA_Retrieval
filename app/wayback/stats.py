"""Snapshot statistics computation — always from DB cache, never live CDX.

Design rules (design.md §7.1):
- compute_snapshot_stats() reads from website_snapshots table only.
- gap_years: years between earliest and latest snapshot that have zero snapshots.
- per_year: dict[year, count] for all years in the active range.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

import asyncpg

from app.models.pydantic_models import SnapshotStats

logger = logging.getLogger(__name__)


async def compute_snapshot_stats(domain: str, db_url: str) -> SnapshotStats:
    """Compute snapshot statistics for a domain entirely from the DB cache.

    Args:
        domain: bare domain, e.g. "example.com"
        db_url: asyncpg-compatible connection string

    Returns:
        SnapshotStats with earliest, latest, total_count, per_year, gap_years.
        Returns empty SnapshotStats (total_count=0) if domain has no snapshots.
    """
    conn = await asyncpg.connect(db_url, ssl=False)
    try:
        rows = await conn.fetch(
            """
            SELECT snapshot_timestamp
            FROM website_snapshots
            WHERE domain = $1
            ORDER BY snapshot_timestamp
            """,
            domain,
        )

        if not rows:
            logger.info("No snapshots found for domain %s", domain)
            return SnapshotStats(domain=domain)

        timestamps: list[datetime] = [r["snapshot_timestamp"] for r in rows]

        earliest = timestamps[0]
        latest = timestamps[-1]
        total_count = len(timestamps)

        # per_year count
        per_year: dict[int, int] = defaultdict(int)
        for ts in timestamps:
            per_year[ts.year] += 1

        # gap_years: years within [earliest.year, latest.year] with zero snapshots
        active_years = set(range(earliest.year, latest.year + 1))
        snapshot_years = set(per_year.keys())
        gap_years = sorted(active_years - snapshot_years)

        return SnapshotStats(
            domain=domain,
            earliest=earliest,
            latest=latest,
            total_count=total_count,
            per_year=dict(per_year),
            gap_years=gap_years,
        )
    finally:
        await conn.close()


def compute_snapshot_stats_sync(
    snapshots: list,  # list[SnapshotRecord]
) -> SnapshotStats:
    """Pure, synchronous version — computes stats from an in-memory list.

    Used by tests and by the CDX pipeline to avoid an extra DB round-trip
    when records are already loaded into memory.
    """
    if not snapshots:
        domain = snapshots[0].domain if snapshots else ""
        return SnapshotStats(domain=domain)

    domain = snapshots[0].domain
    timestamps = sorted(s.snapshot_timestamp for s in snapshots)

    earliest = timestamps[0]
    latest = timestamps[-1]
    total_count = len(timestamps)

    per_year: dict[int, int] = defaultdict(int)
    for ts in timestamps:
        per_year[ts.year] += 1

    active_years = set(range(earliest.year, latest.year + 1))
    gap_years = sorted(active_years - set(per_year.keys()))

    return SnapshotStats(
        domain=domain,
        earliest=earliest,
        latest=latest,
        total_count=total_count,
        per_year=dict(per_year),
        gap_years=gap_years,
    )
