"""Internet Archive Advanced Search discovery adapter.

Calls https://archive.org/advancedsearch.php, paginates through all results,
upserts each item into the sources table immediately.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date
from typing import AsyncGenerator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy import text

from app.config import settings
from app.models.pydantic_models import SourceMetadata

logger = logging.getLogger(__name__)

# IA Advanced Search API endpoint
IA_SEARCH_URL = f"{settings.ia_base_url}/advancedsearch.php"

# Maximum results per page (IA caps at 10,000 total)
PAGE_SIZE = 100

# Fields to request from IA search
FIELDS = [
    "identifier",
    "title",
    "creator",
    "publisher",
    "date",
    "language",
    "subject",
    "collection",
    "licenseurl",
    "rights",
]


def _parse_subject(raw) -> list[str]:
    """IA returns subject as a string or list — normalise to list."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(s) for s in raw if s]
    return [str(raw)]


def _parse_collection(raw) -> str | None:
    """IA returns collection as a string or list — use the first value."""
    if not raw:
        return None
    if isinstance(raw, list):
        return str(raw[0]) if raw else None
    return str(raw) or None


def _parse_scalar(raw) -> str | None:
    """Normalise any IA field that may be a string or a list to a single string.
    
    IA frequently returns creator, publisher, language etc. as a list when
    multiple values are present. We join lists with ' ; ' for storage.
    """
    if not raw:
        return None
    if isinstance(raw, list):
        joined = " ; ".join(str(v) for v in raw if v)
        return joined or None
    val = str(raw).strip()
    return val or None


def _parse_date_raw(raw) -> str | None:
    """Return the raw date string from IA, or None if absent."""
    if not raw:
        return None
    return str(raw).strip() or None


def _build_ia_url(identifier: str) -> str:
    return f"https://archive.org/details/{identifier}"


async def _fetch_page(
    client: httpx.AsyncClient,
    query: str,
    media_type: str,
    page: int,
    rows: int,
    retries: int = 3,
) -> dict:
    """Fetch a single page from IA Advanced Search with exponential backoff."""
    params = {
        "q": query,
        "fl[]": FIELDS,
        "output": "json",
        "rows": rows,
        "page": page,
    }
    if media_type:
        params["q"] = f"({query}) AND mediatype:{media_type}"

    delay = 2.0
    last_exc: Exception | None = None

    for attempt in range(retries):
        try:
            response = await client.get(
                IA_SEARCH_URL,
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_exc = exc
            logger.warning(
                "IA search page %d attempt %d/%d failed: %s — retrying in %.0fs",
                page,
                attempt + 1,
                retries,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
            delay *= 2

    logger.error("IA search page %d failed after %d attempts: %s", page, retries, last_exc)
    raise last_exc


async def discover(
    query: str,
    date_range: tuple[str, str] | None = None,
    media_type: str = "texts",
    max_results: int = 0,
) -> list[SourceMetadata]:
    """Discover IA items matching query and upsert into sources table.

    Args:
        query: IA Advanced Search query string.
        date_range: Optional (start_date, end_date) as ISO strings e.g. ("1975-01-01", "1990-12-31").
        media_type: IA media type filter (default "texts").
        max_results: Stop after collecting this many items. 0 = no cap (up to IA's 10k limit).

    Returns:
        List of SourceMetadata for all discovered items.
    """
    # Build final query with optional date range
    full_query = query
    if date_range:
        full_query = f"({query}) AND date:[{date_range[0]} TO {date_range[1]}]"

    logger.info("Starting IA discovery: query=%r media_type=%r", full_query, media_type)

    all_items: list[SourceMetadata] = []
    page = 1

    async with httpx.AsyncClient() as client:
        while True:
            data = await _fetch_page(client, full_query, media_type=media_type, page=page, rows=PAGE_SIZE)

            response_block = data.get("response", {})
            docs = response_block.get("docs", [])
            num_found = response_block.get("numFound", 0)

            if not docs:
                break

            for doc in docs:
                identifier = doc.get("identifier")
                if not identifier:
                    continue

                item = SourceMetadata(
                    ia_identifier=identifier,
                    title=_parse_scalar(doc.get("title")),
                    author=_parse_scalar(doc.get("creator")),
                    publisher=_parse_scalar(doc.get("publisher")),
                    pub_date=_parse_date_raw(doc.get("date")),
                    language=_parse_scalar(doc.get("language")),
                    subject=_parse_subject(doc.get("subject")),
                    collection=_parse_collection(doc.get("collection")),
                    ia_url=_build_ia_url(identifier),
                    licenseurl=_parse_scalar(doc.get("licenseurl")),
                    rights=_parse_scalar(doc.get("rights")),
                )
                all_items.append(item)

            logger.info(
                "Fetched page %d: %d docs (total found: %d, collected so far: %d)",
                page,
                len(docs),
                num_found,
                len(all_items),
            )

            # IA caps at 10,000 results; stop if we've collected all
            if len(all_items) >= min(num_found, 10_000):
                break
            if len(docs) < PAGE_SIZE:
                break
            # User-specified cap
            if max_results > 0 and len(all_items) >= max_results:
                all_items = all_items[:max_results]
                break

            page += 1

    logger.info("Discovery complete: %d items found", len(all_items))

    # Upsert into sources table
    await _upsert_sources(all_items)

    return all_items


async def _upsert_sources(items: list[SourceMetadata]) -> None:
    """Upsert SourceMetadata records into the sources table."""
    if not items:
        return

    # asyncpg requires ssl to be passed as a connect_arg, not a URL query param
    engine = create_async_engine(
        settings.database_url,
        connect_args={"ssl": False},
        echo=False,
    )

    async with engine.begin() as conn:
        for item in items:
            await conn.execute(
                text("""
                    INSERT INTO sources (
                        ia_identifier, source_type, title, author, publisher,
                        pub_date_raw, language, subject, collection, ia_url,
                        is_open_access
                    ) VALUES (
                        :ia_identifier, 'metadata_only', :title, :author, :publisher,
                        :pub_date_raw, :language, :subject, :collection, :ia_url,
                        false
                    )
                    ON CONFLICT (ia_identifier) DO UPDATE SET
                        title         = EXCLUDED.title,
                        author        = EXCLUDED.author,
                        publisher     = EXCLUDED.publisher,
                        pub_date_raw  = EXCLUDED.pub_date_raw,
                        language      = EXCLUDED.language,
                        subject       = EXCLUDED.subject,
                        collection    = EXCLUDED.collection,
                        ia_url        = EXCLUDED.ia_url,
                        updated_at    = now()
                """),
                {
                    "ia_identifier": item.ia_identifier,
                    "title": item.title,
                    "author": item.author,
                    "publisher": item.publisher,
                    "pub_date_raw": item.pub_date,
                    "language": item.language,
                    "subject": item.subject or [],
                    "collection": item.collection,
                    "ia_url": item.ia_url,
                },
            )

    logger.info("Upserted %d sources into database", len(items))
    await engine.dispose()
