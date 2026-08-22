"""On-demand Wayback Memento snapshot content fetch.

Design rules (design.md §7.2):
- Memento API: GET https://web.archive.org/web/{timestamp}/{url}
- Extract main text content (strip nav, ads, boilerplate via readability-lxml).
- capture_timestamp = snapshot_timestamp; pub_date = NULL for web chunks.
- Mark website_snapshots.fetched_flag=true after successful content fetch.
- Rate limit: 1 req/sec. Retry on 429/5xx with exponential backoff (5 retries).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import asyncpg
import httpx

logger = logging.getLogger(__name__)

MEMENTO_BASE = "https://web.archive.org/web"
_RATE_SLEEP = 1.0
_MAX_RETRIES = 5
_BACKOFF_BASE = 2.0

# Minimum content length to consider a fetch successful (bytes)
_MIN_CONTENT_LEN = 200


def _format_memento_ts(ts: datetime) -> str:
    """Convert datetime to Wayback timestamp string: YYYYMMDDHHmmss."""
    return ts.strftime("%Y%m%d%H%M%S")


def _extract_text_readability(html: str, url: str) -> str | None:
    """Extract main article text using readability-lxml, fallback to regex strip."""
    try:
        from readability import Document  # type: ignore[import]
        doc = Document(html)
        summary_html = doc.summary()
        # Strip remaining HTML tags
        text = re.sub(r"<[^>]+>", " ", summary_html)
        text = re.sub(r"\s+", " ", text).strip()
        return text if len(text) >= _MIN_CONTENT_LEN else None
    except ImportError:
        logger.debug("readability-lxml not installed — falling back to regex strip")
    except Exception as exc:
        logger.warning("readability failed for %s: %s", url, exc)

    # Fallback: strip all tags + collapse whitespace
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) >= _MIN_CONTENT_LEN else None


async def fetch_snapshot_content(
    url: str,
    snapshot_timestamp: datetime,
    db_url: str | None = None,
) -> str | None:
    """Fetch and extract the text content of a Wayback snapshot.

    Args:
        url: original URL of the page.
        snapshot_timestamp: the specific snapshot datetime to retrieve.
        db_url: if provided, marks fetched_flag=True in website_snapshots.

    Returns:
        Extracted plain text, or None if fetch failed or content too short.
    """
    ts_str = _format_memento_ts(snapshot_timestamp)
    memento_url = f"{MEMENTO_BASE}/{ts_str}/{url}"

    delay = _BACKOFF_BASE
    content: str | None = None

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": "HistoricalRAG/1.0 (research; wayback-memento)"},
        timeout=30.0,
    ) as client:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                await asyncio.sleep(_RATE_SLEEP)
                resp = await client.get(memento_url)

                if resp.status_code == 404:
                    logger.info("Snapshot not found: %s", memento_url)
                    return None

                if resp.status_code == 429 or resp.status_code >= 500:
                    logger.warning(
                        "Memento %d for %s (attempt %d/%d) — backoff %.1fs",
                        resp.status_code, url, attempt + 1, _MAX_RETRIES, delay,
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue
                    return None

                resp.raise_for_status()
                content = _extract_text_readability(resp.text, url)
                break

            except httpx.HTTPStatusError as exc:
                logger.warning("HTTP error fetching %s: %s", memento_url, exc)
                return None
            except httpx.RequestError as exc:
                logger.warning("Request error (attempt %d): %s", attempt + 1, exc)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    return None

    if content is None:
        logger.info("No extractable content from %s", memento_url)
        return None

    logger.info(
        "Fetched Memento snapshot %s @ %s — %d chars",
        url, ts_str, len(content),
    )

    # Mark fetched_flag in DB if db_url provided
    if db_url:
        await _mark_fetched(db_url, url, snapshot_timestamp)

    return content


async def _mark_fetched(
    db_url: str,
    url: str,
    snapshot_timestamp: datetime,
) -> None:
    """Set fetched_flag=true and fetched_at=now() for a snapshot row."""
    conn = await asyncpg.connect(db_url, ssl=False)
    try:
        now = datetime.now(timezone.utc)
        updated = await conn.fetchval(
            """
            UPDATE website_snapshots
               SET fetched_flag = true, fetched_at = $1
             WHERE url = $2 AND snapshot_timestamp = $3
            RETURNING id
            """,
            now, url, snapshot_timestamp,
        )
        if updated is None:
            logger.warning(
                "No snapshot row found to mark fetched: url=%s ts=%s",
                url, snapshot_timestamp,
            )
    finally:
        await conn.close()


async def check_fetched_flag(
    url: str,
    snapshot_timestamp: datetime,
    db_url: str,
) -> bool:
    """Return True if this snapshot's content has already been fetched and chunked."""
    conn = await asyncpg.connect(db_url, ssl=False)
    try:
        row = await conn.fetchrow(
            """
            SELECT fetched_flag
            FROM website_snapshots
            WHERE url = $1 AND snapshot_timestamp = $2
            """,
            url, snapshot_timestamp,
        )
        return bool(row["fetched_flag"]) if row else False
    finally:
        await conn.close()
