"""Wayback Machine integration — CDX cache + Memento content fetch."""
from app.wayback.cdx import get_snapshots, is_cache_fresh
from app.wayback.memento import check_fetched_flag, fetch_snapshot_content
from app.wayback.stats import compute_snapshot_stats, compute_snapshot_stats_sync

__all__ = [
    "get_snapshots",
    "is_cache_fresh",
    "fetch_snapshot_content",
    "check_fetched_flag",
    "compute_snapshot_stats",
    "compute_snapshot_stats_sync",
]
