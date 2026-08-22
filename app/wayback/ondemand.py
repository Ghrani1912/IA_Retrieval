"""On-demand Wayback snapshot content fetch for query-time domain filtering.

When a user queries with a domain filter (e.g. cs.stanford.edu):
1. Find the most recent snapshot in website_snapshots
2. Fetch its content via Memento API
3. Clean → Chunk → Embed → Index into OpenSearch + Qdrant
4. Return the chunks for inclusion in retrieval evidence

This is the bridge between CDX metadata (already ingested) and
retrievable content chunks (not yet created for website sources).
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
            chunk_id = await conn.fetchval(
                """
                INSERT INTO chunks (source_id, text, page_or_section, char_range_start, char_range_end, token_count)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                source_id, chunk.text, chunk.page_or_section,
                chunk.char_range_start, chunk.char_range_end, chunk.token_count,
            )
            chunk.id = chunk_id
            result.append(chunk)
        logger.info("Persisted %d web chunks for source_id=%d", len(result), source_id)
        return result
    finally:
        await conn.close()


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
                id=r["id"],
                source_id=r["source_id"],
                text=r["text"],
                page_or_section=r["page_or_section"],
                char_range_start=r["char_range_start"],
                char_range_end=r["char_range_end"],
                token_count=r["token_count"],
                capture_timestamp=r["capture_timestamp"],
            )
            for r in rows
        ]
        logger.info("Found %d existing chunks for domain %s", len(chunks), domain)
        return chunks
    finally:
        await conn.close()


async def fetch_web_content_for_domain(domain: str) -> list:
    """Fetch, process, and index website content for a domain.

    Returns list of Chunk objects ready for retrieval, or empty list on failure.
    """
    logger.info("On-demand fetch for domain: %s", domain)

    # 1. Get latest snapshot
    snapshot = await _get_latest_snapshot(domain)
    if not snapshot:
        logger.warning("No snapshots found for domain %s", domain)
        return []

    url = snapshot["url"]
    ts = snapshot["snapshot_timestamp"]

    # 2. Check if already fetched — return existing chunks from DB
    if await _snapshot_already_chunked(url, ts):
        logger.info("Snapshot already chunked for %s @ %s — returning existing chunks", url, ts)
        return await _get_existing_chunks(domain)

    # 3. Fetch content via Memento
    from app.wayback.memento import fetch_snapshot_content
    content = await fetch_snapshot_content(url, ts, db_url=DB_URL)
    if not content:
        logger.warning("Failed to fetch content for %s @ %s", url, ts)
        return []

    logger.info("Fetched %d chars from %s @ %s", len(content), url, ts)

    # 4. Clean
    from app.ingestion.cleaner import clean_text
    cleaned = clean_text(content)
    if not cleaned.text.strip():
        logger.warning("Cleaned text empty for %s", url)
        return []

    # 5. Chunk
    from app.ingestion.chunker import chunk_text
    source_id = await _upsert_source(domain)
    chunks = chunk_text(cleaned, source_id)

    # Set capture_timestamp on all chunks (web content)
    for chunk in chunks:
        chunk.capture_timestamp = ts

    if not chunks:
        logger.warning("No chunks produced for %s", url)
        return []

    logger.info("Produced %d chunks from %s", len(chunks), url)

    # 6. Persist to DB
    chunks = await _persist_chunks(chunks, source_id)

    # 7. Embed
    from app.ingestion.embed import embed_chunks
    embedded = embed_chunks(chunks)

    # 8. Index into OpenSearch (BM25)
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

    # 9. Index into Qdrant (vectors)
    from app.ingestion.index_vectors import index_vectors, write_embedding_ids_to_db
    from qdrant_client import QdrantClient

    qd_client = QdrantClient(url=settings.qdrant_url)
    index_vectors(embedded, {source_id: web_source}, client=qd_client)
    await write_embedding_ids_to_db(embedded, DB_URL)

    logger.info(
        "On-demand pipeline complete for %s: %d chunks indexed",
        domain, len(embedded),
    )

    # Return Chunk objects (without embedding, for retrieval)
    return chunks
