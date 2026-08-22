"""Wayback CDX API client — populates the website_snapshots cache.

Design rules (from design.md §7.1):
- Never query CDX live per user request; always go through the DB cache.
- Rate-limit to 1 req/sec between paginated CDX pages.
- On HTTP 429 or network error: exponential backoff, up to 5 retries.
- Cache freshness: skip CDX call if domain was fetched within the last 24h.
- Upsert rows (domain, url, snapshot_timestamp) — idempotent re-runs.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import asyncpg
import httpx

from app.models.pydantic_models import SnapshotRecord

logger = logging.getLogger(__name__)

CDX_BASE = "https://web.archive.org/cdx/search/cdx"
_PAGE_LIMIT = 10_000        # rows per CDX page
_RATE_SLEEP = 1.0           # seconds between pages (Wayback ToS)
_MAX_RETRIES = 5
_BACKOFF_BASE = 2.0         # seconds; doubles on each retry
_CACHE_TTL_HOURS = 24

# Timeout config: distinguish slow-connect from slow-read (CDX can take 60s under load)
_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)

# CDX query mode:
# "homepage" — queries only the root URL (domain/), fast and reliable.
#              Gives accurate "how many times was this archived" stats.
# "full"     — queries all URLs under the domain (domain/*), much heavier.
#              Use only for small/targeted subdomains.
CDX_MODE_HOMEPAGE = "homepage"
CDX_MODE_FULL = "full"


# ---------------------------------------------------------------------------
# CDX row parsing
# ---------------------------------------------------------------------------

def _parse_cdx_row(row: list[str], domain: str) -> SnapshotRecord | None:
    """Parse a single CDX JSON row into a SnapshotRecord.

    CDX columns (fl=urlkey,timestamp,original,statuscode,digest):
        0: urlkey  1: timestamp  2: original  3: statuscode  4: digest
    """
    if len(row) < 5:
        return None
    try:
        ts_str = row[1]  # "20060101120000"
        ts = datetime(
            int(ts_str[0:4]), int(ts_str[4:6]), int(ts_str[6:8]),
            int(ts_str[8:10]), int(ts_str[10:12]), int(ts_str[12:14]),
            tzinfo=timezone.utc,
        )
    except (ValueError, IndexError):
        return None

    status_code: int | None = None
    try:
        status_code = int(row[3])
    except (ValueError, TypeError):
        pass

    return SnapshotRecord(
        domain=domain,
        url=row[2],
        snapshot_timestamp=ts,
        status_code=status_code,
        digest=row[4] if row[4] != "-" else None,
        fetched_flag=False,
    )


# ---------------------------------------------------------------------------
# CDX HTTP fetch (single page, with retry)
# ---------------------------------------------------------------------------

async def _fetch_cdx_page(
    client: httpx.AsyncClient,
    domain: str,
    from_ts: str = "",
    to_ts: str = "",
    mode: str = CDX_MODE_HOMEPAGE,
) -> list[list[str]]:
    """Fetch one CDX page; retry on 429/5xx/timeout with exponential backoff.

    Args:
        mode: CDX_MODE_HOMEPAGE queries only root URL (fast, reliable for stats).
              CDX_MODE_FULL queries all paths (heavy, may timeout on large sites).
    """
    # No collapse=digest — that forces expensive server-side dedup which times out
    # on large domains. Dedup is handled by ON CONFLICT DO NOTHING in the DB upsert.
    url_pattern = f"{domain}/" if mode == CDX_MODE_HOMEPAGE else f"{domain}/*"

    params: dict[str, str] = {
        "url": url_pattern,
        "output": "json",
        "fl": "urlkey,timestamp,original,statuscode,digest",
        "limit": str(_PAGE_LIMIT),
    }
    if from_ts:
        params["from"] = from_ts
    if to_ts:
        params["to"] = to_ts

    delay = _BACKOFF_BASE
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.get(CDX_BASE, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning(
                    "CDX returned HTTP %d for %s (attempt %d/%d) — backing off %.1fs",
                    resp.status_code, domain, attempt + 1, _MAX_RETRIES, delay,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
            resp.raise_for_status()
            rows: list[list[str]] = resp.json()
            # Strip header row when fl= is used
            if rows and rows[0][0] == "urlkey":
                rows = rows[1:]
            return rows
        except httpx.HTTPStatusError:
            raise
        except httpx.RequestError as exc:
            logger.warning(
                "CDX request error for %s (attempt %d/%d): %s",
                domain, attempt + 1, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise
    return []


# ---------------------------------------------------------------------------
# Bulk upsert via COPY + staging table
# ---------------------------------------------------------------------------

async def _upsert_snapshots_bulk(
    conn: asyncpg.Connection,
    records: list[SnapshotRecord],
) -> int:
    """COPY into a temp staging table, then upsert with a single INSERT.

    This is the standard pattern for fast bulk-upsert in Postgres:
    - COPY's raw speed for the bulk load (no per-row overhead)
    - ON CONFLICT DO NOTHING for idempotent dedup
    - Returns the actual number of rows inserted (post-dedup)

    The staging table is TEMP ON COMMIT DROP — no WAL overhead, auto-cleaned.
    """
    # Deduplicate on (url, snapshot_timestamp) before COPY — CDX can return
    # the same row across paginated results, and DO UPDATE fails on duplicates
    # within the same INSERT batch.
    seen: set[tuple[str, datetime]] = set()
    unique_records: list[SnapshotRecord] = []
    for r in records:
        key = (r.url, r.snapshot_timestamp)
        if key not in seen:
            seen.add(key)
            unique_records.append(r)

    dupes = len(records) - len(unique_records)
    if dupes:
        logger.info("Deduped %d duplicate CDX rows before COPY", dupes)

    rows = [
        (
            r.domain,
            r.url,
            r.snapshot_timestamp,
            r.status_code,
            r.digest,
            False,   # fetched_flag — CDX metadata fetched, not content
        )
        for r in unique_records
    ]

    async with conn.transaction():
        await conn.execute("""
            CREATE TEMP TABLE staging_snapshots (
                domain            TEXT,
                url               TEXT,
                snapshot_timestamp TIMESTAMPTZ,
                status_code       INTEGER,
                digest            TEXT,
                fetched_flag      BOOLEAN
            ) ON COMMIT DROP
        """)

        await conn.copy_records_to_table(
            "staging_snapshots",
            records=rows,
            columns=["domain", "url", "snapshot_timestamp",
                     "status_code", "digest", "fetched_flag"],
        )

        result = await conn.execute("""
            INSERT INTO website_snapshots
                (domain, url, snapshot_timestamp, status_code, digest, fetched_flag,
                 fetched_at)
            SELECT
                domain, url, snapshot_timestamp, status_code, digest, fetched_flag,
                now()
            FROM staging_snapshots
            ON CONFLICT (url, snapshot_timestamp) DO NOTHING
        """)
        # result string is like "INSERT 0 58213" — parse the inserted row count
        inserted = int(result.split()[-1])

    logger.info(
        "Upserted %d/%d records for domain %s (duplicates skipped: %d)",
        inserted, len(records), records[0].domain, len(records) - inserted,
    )
    return inserted


# ---------------------------------------------------------------------------
# Cache freshness check
# ---------------------------------------------------------------------------

async def _is_cache_fresh(conn: asyncpg.Connection, domain: str) -> bool:
    """Return True if this domain was fully fetched within the last 24 hours."""
    row = await conn.fetchrow(
        """
        SELECT MAX(fetched_at) AS last_fetch
        FROM website_snapshots
        WHERE domain = $1 AND fetched_at IS NOT NULL
        """,
        domain,
    )
    if row is None or row["last_fetch"] is None:
        return False
    age_hours = (datetime.now(timezone.utc) - row["last_fetch"]).total_seconds() / 3600
    return age_hours < _CACHE_TTL_HOURS


async def is_cache_fresh(domain: str, db_url: str) -> bool:
    """Public wrapper — returns True if domain CDX cache was populated within 24h."""
    conn = await asyncpg.connect(db_url, ssl=False)
    try:
        return await _is_cache_fresh(conn, domain)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# DB loader
# ---------------------------------------------------------------------------

async def _load_from_db(
    conn: asyncpg.Connection, domain: str
) -> list[SnapshotRecord]:
    """Load all cached snapshot rows for a domain from the DB."""
    db_rows = await conn.fetch(
        """
        SELECT domain, url, snapshot_timestamp, status_code, digest,
               fetched_flag, fetched_at
        FROM website_snapshots
        WHERE domain = $1
        ORDER BY snapshot_timestamp
        """,
        domain,
    )
    return [
        SnapshotRecord(
            domain=r["domain"],
            url=r["url"],
            snapshot_timestamp=r["snapshot_timestamp"],
            status_code=r["status_code"],
            digest=r["digest"],
            fetched_flag=r["fetched_flag"],
            fetched_at=r["fetched_at"],
        )
        for r in db_rows
    ]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def get_snapshots(
    domain: str,
    db_url: str,
    mode: str = CDX_MODE_HOMEPAGE,
) -> list[SnapshotRecord]:
    """Populate website_snapshots from CDX API (if stale) and return all records.

    Args:
        domain: bare domain, e.g. "example.com"
        db_url: asyncpg-compatible connection string
        mode: CDX_MODE_HOMEPAGE (default) or CDX_MODE_FULL.

    Returns:
        All SnapshotRecord rows for the domain from the DB cache.
    """
    conn = await asyncpg.connect(db_url, ssl=False)
    try:
        if await _is_cache_fresh(conn, domain):
            logger.info("CDX cache fresh for %s — skipping API call", domain)
            return await _load_from_db(conn, domain)

        logger.info("Fetching CDX snapshots for %s (mode=%s)...", domain, mode)
        all_records: list[SnapshotRecord] = []

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # First page
            rows = await _fetch_cdx_page(client, domain, mode=mode)
            for row in rows:
                rec = _parse_cdx_row(row, domain)
                if rec is not None:
                    all_records.append(rec)

            if rows:
                await asyncio.sleep(_RATE_SLEEP)

            # Paginate — stop gracefully if a page fails after all retries
            while len(rows) == _PAGE_LIMIT:
                last_ts = rows[-1][1]
                try:
                    rows = await _fetch_cdx_page(
                        client, domain, from_ts=last_ts, mode=mode
                    )
                except Exception as exc:
                    # Pagination stopped — upsert what we have rather than losing it
                    logger.warning(
                        "CDX pagination halted after retries for %s: %s — "
                        "proceeding with %d records already fetched",
                        domain, exc, len(all_records),
                    )
                    rows = []

                for row in rows:
                    rec = _parse_cdx_row(row, domain)
                    if rec is not None:
                        all_records.append(rec)

                if rows:
                    await asyncio.sleep(_RATE_SLEEP)

        logger.info("CDX returned %d records for %s", len(all_records), domain)

        if all_records:
            # Upsert is OUTSIDE the pagination try/except — its own errors propagate cleanly
            inserted = await _upsert_snapshots_bulk(conn, all_records)
            logger.info("Inserted %d new rows for %s", inserted, domain)
            # Refresh fetched_at for all domain rows so cache freshness check works correctly
            await conn.execute(
                "UPDATE website_snapshots SET fetched_at = now() WHERE domain = $1",
                domain,
            )

        return await _load_from_db(conn, domain)
    finally:
        await conn.close()
