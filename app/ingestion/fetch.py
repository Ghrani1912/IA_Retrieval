"""Full-text fetch adapter for Internet Archive items.

Priority:
  1. Check filesystem object cache — return immediately on hit.
  2. Check copyright scope — mark metadata_only and return None if blocked.
  3. Call IA Metadata API, find _djvu.txt or _hocr.html.
  4. Download the file, write to cache, return content.
  5. On any failure: mark source appropriately, never raise.
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx

from app.config import settings
from app.ingestion import object_cache
from app.ingestion.copyright import check_copyright_scope

logger = logging.getLogger(__name__)

IA_METADATA_URL = f"{settings.ia_base_url}/metadata"


async def _get_metadata(client: httpx.AsyncClient, identifier: str) -> dict:
    """Fetch IA Metadata API response for an identifier."""
    url = f"{IA_METADATA_URL}/{identifier}"
    response = await client.get(url, timeout=20.0)
    response.raise_for_status()
    return response.json()


def _find_ocr_file(metadata: dict) -> tuple[str | None, str]:
    """Scan the files list for _djvu.txt (preferred) then _hocr.html.

    Returns:
        (download_url, filename) or (None, '') if no OCR file found.
    """
    files = metadata.get("files", [])
    identifier = metadata.get("metadata", {}).get("identifier", "")

    djvu = None
    hocr = None

    for f in files:
        name = f.get("name", "")
        if name.endswith("_djvu.txt"):
            djvu = name
        elif name.endswith("_hocr.html") and hocr is None:
            hocr = name

    chosen = djvu or hocr
    if not chosen:
        return None, ""

    url = f"https://archive.org/download/{identifier}/{chosen}"
    return url, chosen


async def _download_with_retry(
    client: httpx.AsyncClient, url: str, retries: int = 3
) -> str | None:
    """Download a URL with exponential backoff. Returns text content or None."""
    delay = 2.0
    last_exc: Exception | None = None

    for attempt in range(retries):
        try:
            response = await client.get(url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()
            return response.text
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_exc = exc
            logger.warning(
                "Download attempt %d/%d failed for %s: %s — retrying in %.0fs",
                attempt + 1, retries, url, exc, delay,
            )
            await asyncio.sleep(delay)
            delay *= 2

    logger.error("Download failed after %d attempts for %s: %s", retries, url, last_exc)
    return None


async def fetch_fulltext(
    identifier: str,
    pub_date_raw: str | None = None,
    collection: str | None = None,
    ia_metadata_rights: dict | None = None,
) -> str | None:
    """Fetch OCR full text for an IA item, with caching and copyright gating.

    Args:
        identifier: IA item identifier.
        pub_date_raw: Raw publication date string from IA.
        collection: IA collection name.
        ia_metadata_rights: Dict with 'licenseurl'/'rights' keys from IA metadata.

    Returns:
        OCR text string if allowed and available, else None.
        None means the source should be marked metadata_only or fetch_failed.
    """
    # ------------------------------------------------------------------
    # Step 1: Object cache hit — return immediately
    # ------------------------------------------------------------------
    cached = object_cache.read(identifier)
    if cached is not None:
        logger.debug("%s: object cache hit", identifier)
        return cached

    # ------------------------------------------------------------------
    # Step 2: Copyright scope check
    # ------------------------------------------------------------------
    rights_meta = ia_metadata_rights or {}
    allow_fulltext, is_open_access = check_copyright_scope(
        ia_identifier=identifier,
        pub_date_raw=pub_date_raw,
        collection=collection,
        ia_metadata=rights_meta,
    )

    if not allow_fulltext:
        logger.info("%s: blocked by copyright check — marking metadata_only", identifier)
        return None

    # ------------------------------------------------------------------
    # Step 3: Fetch IA Metadata to locate OCR file
    # ------------------------------------------------------------------
    async with httpx.AsyncClient() as client:
        try:
            metadata = await _get_metadata(client, identifier)
        except Exception as exc:
            logger.error("%s: metadata fetch failed: %s", identifier, exc)
            return None

        ocr_url, filename = _find_ocr_file(metadata)

        if not ocr_url:
            logger.info("%s: no OCR file found (in-copyright or missing scan)", identifier)
            return None

        # ------------------------------------------------------------------
        # Step 4: Download OCR file
        # ------------------------------------------------------------------
        logger.info("%s: downloading %s", identifier, filename)
        content = await _download_with_retry(client, ocr_url)

    if content is None:
        logger.error("%s: download failed after retries — marking fetch_failed", identifier)
        return None

    # ------------------------------------------------------------------
    # Step 5: Write to object cache before returning
    # ------------------------------------------------------------------
    object_cache.write(identifier, content)

    logger.info(
        "%s: fetched %d chars from %s",
        identifier,
        len(content),
        filename,
    )
    return content
