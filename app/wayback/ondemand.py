"""On-demand Wayback snapshot content fetch for query-time domain filtering.

When a user queries with a domain filter (e.g. cs.stanford.edu):
1. Find the most recent snapshot in website_snapshots
2. Fetch its content via Memento API
3. Clean → Chunk → Embed → Index into OpenSearch + Qdrant
4. Return the chunks for inclusion in retrieval evidence

This is the bridge between CDX metadata (already ingested) and
retrievable content chunks (not yet created for website sources).

NEW: When a date range is specified, fetch snapshots from that time period
instead of just the latest. This enables temporal queries like
"What did Stanford AI Lab focus on in the 1990s?"
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


async def _get_latest_snapshot(domain: str) -> dict | None:
    """Get the most recent snapshot for a domain from website_snapshots."""
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        row = await conn.fetchrow(
            """
            SELECT id, url, snapshot_timestamp, status_code, digest
            FROM website_snapshots
            WHERE domain = $1 AND status_code >= 200 AND status_code < 400
            ORDER BY snapshot_timestamp DESC
            LIMIT 1
            """,
            domain,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def _get_closest_snapshot(domain: str, target_year: int) -> dict | None:
    """Get the snapshot closest to a target year.

    Finds the snapshot with timestamp closest to the middle of the target year.
    Returns the snapshot dict or None if no snapshots exist.
    """
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        # Target the middle of the year (July 1)
        target_ts = datetime(target_year, 7, 1, tzinfo=timezone.utc)

        row = await conn.fetchrow(
            """
            SELECT id, url, snapshot_timestamp, status_code, digest
            FROM website_snapshots
            WHERE domain = $1 AND status_code >= 200 AND status_code < 400
            ORDER BY ABS(EXTRACT(EPOCH FROM (snapshot_timestamp - $2::timestamptz)))
            LIMIT 1
            """,
            domain,
            target_ts,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def _get_snapshots_in_range(
    domain: str, year_start: int, year_end: int, max_snapshots: int = 3
) -> list[dict]:
    """Get up to max_snapshots snapshots spread across a date range.

    Returns snapshots evenly distributed across the time range to capture
    temporal evolution. For example, if year_start=1990 and year_end=2000,
    might return snapshots from ~1990, ~1995, and ~2000.
    """
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        # First, get all snapshots in the range
        start_ts = datetime(year_start, 1, 1, tzinfo=timezone.utc)
        end_ts = datetime(year_end, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        rows = await conn.fetch(
            """
            SELECT id, url, snapshot_timestamp, status_code, digest
            FROM website_snapshots
            WHERE domain = $1
              AND status_code >= 200 AND status_code < 400
              AND snapshot_timestamp >= $2 AND snapshot_timestamp <= $3
            ORDER BY snapshot_timestamp
            """,
            domain,
            start_ts,
            end_ts,
        )

        if not rows:
            return []

        snapshots = [dict(r) for r in rows]

        # If we have fewer snapshots than requested, return all
        if len(snapshots) <= max_snapshots:
            return snapshots

        # Evenly sample across the range
        step = len(snapshots) / max_snapshots
        sampled = []
        for i in range(max_snapshots):
            idx = int(i * step)
            sampled.append(snapshots[idx])

        return sampled
    finally:
        await conn.close()


async def _snapshot_already_chunked(url: str, snapshot_ts: datetime) -> bool:
    """Check if this snapshot's content was already fetched and chunked."""
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        row = await conn.fetchrow(
            "SELECT fetched_flag FROM website_snapshots WHERE url = $1 AND snapshot_timestamp = $2",
            url, snapshot_ts,
        )
        return bool(row["fetched_flag"]) if row else False
    finally:
        await conn.close()


async def _upsert_source(domain: str) -> int:
    """Create or get a source row for this domain. Returns source_id."""
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        # Try to find existing source
        row = await conn.fetchrow(
            "SELECT id FROM sources WHERE ia_identifier = $1",
            domain,
        )
        if row:
            return row["id"]

        # Create new source
        source_id = await conn.fetchval(
            """
            INSERT INTO sources (ia_identifier, title, collection, source_type, pub_date_raw)
            VALUES ($1, $2, $3, 'website', NULL)
            RETURNING id
            """,
            domain,
            f"Website: {domain}",
            domain,
        )
        logger.info("Created source row for domain %s: id=%d", domain, source_id)
        return source_id
    finally:
        await conn.close()


async def _persist_chunks(chunks: list, source_id: int) -> list:
    """Insert chunks into DB and return them with IDs populated."""
    if not chunks:
        return []

    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        result = []
        for chunk in chunks:
            ts = chunk.capture_timestamp
            chunk_id = await conn.fetchval(
                """
                INSERT INTO chunks (source_id, text, page_or_section, capture_timestamp, char_range_start, char_range_end, token_count)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                source_id, chunk.text, chunk.page_or_section,
                ts, chunk.char_range_start, chunk.char_range_end, chunk.token_count,
            )
            chunk.id = chunk_id
            result.append(chunk)
        logger.info("Persisted %d web chunks for source_id=%d", len(result), source_id)
        return result
    finally:
        await conn.close()


def _filter_web_chunks(chunks: list) -> list:
    """Remove junk chunks from web content.

    Filters out JS/HTML noise, duplicate text, and chunks that are
    only page markers. Deduplicates by first 100 chars of stripped text.
    """
    import re
    JUNK_RE = re.compile(
        r"(window\.|function\s|var\s|const\s|let\s|__wm\."
        r"|<script|<style|<html|<head|<body|<div|<span|<link|<meta"
        r"|RufflePlayer|archive\.org/web/|_wm\.)",
        re.IGNORECASE,
    )
    seen = set()
    filtered = []
    for chunk in chunks:
        # Strip page markers and whitespace for checking
        text = chunk.text.strip()
        clean = re.sub(r"\[\[PAGE:\d+\]\]", "", text).strip()
        # Skip empty or very short chunks
        if len(clean) < 40:
            continue
        # Skip JS/HTML junk
        if JUNK_RE.search(clean):
            # Check if it's MORE than 50% junk (allow some chunks with a JS prefix)
            junk_ratio = len(re.findall(r"[{};=()]", clean)) / max(len(clean), 1)
            if junk_ratio > 0.05:  # >5% special chars = likely code
                continue
        # Deduplicate by first 100 chars
        dedup_key = clean[:100].lower()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        filtered.append(chunk)
    logger.info("Filtered web chunks: %d -> %d (removed %d junk/duplicates)",
                len(chunks), len(filtered), len(chunks) - len(filtered))
    return filtered


async def _get_existing_chunks(domain: str) -> list:
    """Return existing chunks for a domain from the DB (already fetched/indexed)."""
    from app.models.pydantic_models import Chunk
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        rows = await conn.fetch(
            """
            SELECT c.id, c.source_id, c.text, c.page_or_section,
                   c.char_range_start, c.char_range_end, c.token_count,
                   c.capture_timestamp
            FROM chunks c
            JOIN sources s ON c.source_id = s.id
            WHERE s.ia_identifier = $1
            ORDER BY c.id
            """,
            domain,
        )
        chunks = [
            Chunk(
                id=r["id"], source_id=r["source_id"], text=r["text"],
                page_or_section=r["page_or_section"],
                char_range_start=r["char_range_start"], char_range_end=r["char_range_end"],
                token_count=r["token_count"], capture_timestamp=r["capture_timestamp"],
            )
            for r in rows
        ]
        logger.info("Found %d existing chunks for domain %s", len(chunks), domain)
        return _filter_web_chunks(chunks)
    finally:
        await conn.close()


async def _ingest_single_snapshot(
    domain: str,
    snapshot: dict,
    source_id: int,
) -> list:
    """Fetch, process, and index a single snapshot. Returns chunks."""
    from app.models.pydantic_models import Chunk

    url = snapshot["url"]
    ts = snapshot["snapshot_timestamp"]

    # Check if already fetched
    if await _snapshot_already_chunked(url, ts):
        # Check if chunks actually exist for this snapshot
        existing = await _get_existing_chunks(domain)
        has_chunks_for_ts = any(c.capture_timestamp == ts for c in existing)
        if has_chunks_for_ts:
            logger.info("Snapshot already chunked: %s @ %s", url, ts)
            return []
        else:
            logger.info("Snapshot marked fetched but no chunks found, retrying: %s @ %s", url, ts)

    # Fetch content via Memento
    from app.wayback.memento import fetch_snapshot_content
    content = await fetch_snapshot_content(url, ts, db_url=DB_URL)
    if not content:
        logger.warning("Failed to fetch content for %s @ %s", url, ts)
        return []

    logger.info("Fetched %d chars from %s @ %s", len(content), url, ts)

    # Clean
    from app.ingestion.cleaner import clean_text
    cleaned = clean_text(content)
    if not cleaned.text.strip():
        logger.warning("Cleaned text empty for %s", url)
        return []

    # Chunk
    from app.ingestion.chunker import chunk_text
    chunks = chunk_text(cleaned, source_id)

    # Set capture_timestamp on all chunks (web content)
    for chunk in chunks:
        chunk.capture_timestamp = ts

    if not chunks:
        logger.warning("No chunks produced for %s", url)
        return []

    logger.info("Produced %d chunks from %s @ %s", len(chunks), url, ts)

    # Persist to DB
    chunks = await _persist_chunks(chunks, source_id)

    # Embed
    from app.ingestion.embed import embed_chunks
    embedded = embed_chunks(chunks)

    # Index into OpenSearch (BM25)
    from app.ingestion.index_bm25 import index_bm25, SourceRow
    from app.ingestion.opensearch_client import get_client

    web_source = SourceRow(
        source_id=source_id,
        ia_identifier=domain,
        source_type="website",
        pub_date_raw=None,
        collection=domain,
        language="en",
    )
    os_client = get_client()
    index_bm25(embedded, {source_id: web_source}, client=os_client, refresh=True)

    # Index into Qdrant (vectors)
    from app.ingestion.index_vectors import index_vectors, write_embedding_ids_to_db
    from qdrant_client import QdrantClient

    qd_client = QdrantClient(url=settings.qdrant_url)
    index_vectors(embedded, {source_id: web_source}, client=qd_client)
    await write_embedding_ids_to_db(embedded, DB_URL)

    return chunks


async def fetch_web_content_for_domain(
    domain: str,
    date_range_start: int | None = None,
    date_range_end: int | None = None,
) -> list:
    """Fetch, process, and index website content for a domain.

    When date_range_start/end are provided, fetch snapshots from that time
    period instead of just the latest. This enables temporal queries like
    "What did X focus on in the 1990s?" to retrieve era-appropriate content.

    Args:
        domain: Website domain (e.g. "cs.stanford.edu")
        date_range_start: Start year for temporal queries (optional)
        date_range_end: End year for temporal queries (optional)

    Returns list of Chunk objects ready for retrieval, or empty list on failure.
    """
    logger.info(
        "On-demand fetch for domain: %s (date_range: %s-%s)",
        domain, date_range_start, date_range_end,
    )

    source_id = await _upsert_source(domain)

    # Determine which snapshots to fetch based on date range
    if date_range_start or date_range_end:
        # Temporal query: fetch snapshots from the specified time period
        year_start = date_range_start or 1990  # fallback if only end specified
        year_end = date_range_end or 2025      # fallback if only start specified

        snapshots = await _get_snapshots_in_range(domain, year_start, year_end, max_snapshots=3)
        if not snapshots:
            # No snapshots in range — try closest to the start year
            closest = await _get_closest_snapshot(domain, year_start)
            if closest:
                snapshots = [closest]

        if not snapshots:
            logger.warning("No snapshots found for domain %s in range %d-%d", domain, year_start, year_end)
            return []
    else:
        # Default: try multiple snapshots from different eras to maximize content
        # Start with the latest, then try historical snapshots if the latest fails
        latest = await _get_latest_snapshot(domain)
        if not latest:
            logger.warning("No snapshots found for domain %s", domain)
            return []
        
        # Also get snapshots from different historical periods
        era_targets = list(range(1996, 2027, 2))  # Try every 2 years for better coverage
        historical = []
        for year in era_targets:
            snap = await _get_closest_snapshot(domain, year)
            if snap and snap["url"] != latest["url"]:
                historical.append(snap)
        
        # Combine: latest first, then historical (deduplicate by URL)
        seen_urls = {latest["url"]}
        snapshots = [latest]
        for h in historical:
            if h["url"] not in seen_urls:
                snapshots.append(h)
                seen_urls.add(h["url"])
        
        # Try up to 15 snapshots for better coverage
        snapshots = snapshots[:15]

    logger.info("Will fetch %d snapshot(s) for domain %s", len(snapshots), domain)

    # Fetch and process each snapshot, stop early if we get enough content
    all_chunks = []
    min_chunks_target = 5   # Old web pages are short, 5 chunks is enough
    for snapshot in snapshots:
        if len(all_chunks) >= min_chunks_target:
            logger.info("Got enough chunks (%d >= %d), skipping remaining snapshots",
                       len(all_chunks), min_chunks_target)
            break
        try:
            chunks = await _ingest_single_snapshot(domain, snapshot, source_id)
            all_chunks.extend(chunks)
            logger.info("Snapshot %s @ %s produced %d chunks (total: %d)",
                       snapshot["url"], snapshot["snapshot_timestamp"], len(chunks), len(all_chunks))
        except Exception as exc:
            logger.warning("Failed to ingest snapshot %s @ %s: %s",
                          snapshot["url"], snapshot["snapshot_timestamp"], exc)

    # Also return any previously indexed chunks for this domain
    existing_chunks = await _get_existing_chunks(domain)

    # Combine new + existing, filter junk, deduplicate
    combined = all_chunks + existing_chunks
    filtered = _filter_web_chunks(combined)

    logger.info(
        "On-demand pipeline complete for %s: %d new chunks, %d existing, %d total after filtering",
        domain, len(all_chunks), len(existing_chunks), len(filtered),
    )

    return filtered
