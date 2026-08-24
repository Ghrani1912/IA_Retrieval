"""On-demand IA ingestion for thin retrieval results.

When the retrieval pipeline returns fewer than THIN_THRESHOLD unique sources,
this module searches IA for papers matching the query, ingests the top results,
and indexes them — all in a background task so the user gets an immediate answer
from the existing index.

Usage:
    from app.ingestion.ondemand import on_demand_ingest
    await on_demand_ingest(query="neural networks", max_sources=5)
"""
from __future__ import annotations

import asyncio
import logging
import traceback

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")

# Don't ingest more than this many sources per on-demand request
DEFAULT_MAX_SOURCES = 5

# Minimum unique sources in retrieval results before triggering on-demand
THIN_THRESHOLD = 3


async def on_demand_ingest(
    query: str,
    max_sources: int = DEFAULT_MAX_SOURCES,
) -> dict:
    """Search IA for papers matching query, ingest top results, index them.

    Returns dict with ingestion stats: {sources_found, sources_ingested, chunks_added}.
    Runs the full pipeline synchronously within this async function —
    call from a background task (asyncio.create_task) to avoid blocking.
    """
    from app.ingestion.discover import discover
    from app.ingestion.fetch import fetch_fulltext
    from app.ingestion.cleaner import clean_text
    from app.ingestion.chunker import chunk_text
    from app.ingestion.embed import embed_chunks
    from app.ingestion.index_bm25 import SourceRow, index_bm25
    from app.ingestion.index_vectors import index_vectors, write_embedding_ids_to_db
    from app.models.pydantic_models import ChunkWithEmbedding

    logger.info("[ON-DEMAND] Starting on-demand ingestion for query: %r", query)

    # Step 1: Discover — find IA papers matching the query, limited to max_sources
    # Target ingestible collections: government docs (DTIC) + education research (ERIC)
    # These collections have proven full-text availability on IA.
    targeted_query = f"{query} AND collection:dticarchive"
    try:
        sources = await discover(query=targeted_query, max_results=max_sources)
    except Exception as exc:
        logger.error("[ON-DEMAND] Discover failed: %s", exc)
        return {"sources_found": 0, "sources_ingested": 0, "chunks_added": 0, "error": str(exc)}

    if not sources:
        logger.info("[ON-DEMAND] No sources found for query: %r", query)
        return {"sources_found": 0, "sources_ingested": 0, "chunks_added": 0}

    logger.info("[ON-DEMAND] Found %d sources, processing...", len(sources))

    conn = await asyncpg.connect(DB_URL, ssl=False)
    total_chunks = 0
    sources_ingested = 0

    try:
        for i, src_meta in enumerate(sources):
            identifier = src_meta.ia_identifier

            try:
                # Check if source exists in DB, create if not
                row = await conn.fetchrow(
                    "SELECT id FROM sources WHERE ia_identifier = $1", identifier,
                )
                if row is None:
                    # New source — create source row first
                    source_id = await conn.fetchval(
                        """
                        INSERT INTO sources (ia_identifier, title, collection, source_type, pub_date_raw, language)
                        VALUES ($1, $2, $3, 'metadata_only', $4, 'en')
                        RETURNING id
                        """,
                        identifier,
                        src_meta.title or f"IA: {identifier}",
                        src_meta.collection or "dticarchive",
                        src_meta.pub_date,
                    )
                    logger.info("[ON-DEMAND] Created new source %s (id=%d)", identifier, source_id)
                else:
                    source_id = row["id"]

                # Skip if already ingested
                existing = await conn.fetchval(
                    "SELECT COUNT(*) FROM chunks WHERE source_id = $1", source_id,
                )
                if existing > 0:
                    logger.info("[ON-DEMAND] %s already has %d chunks — skipping", identifier, existing)
                    sources_ingested += 1
                    continue

                # Fetch full text
                raw_text = await fetch_fulltext(
                    identifier=identifier,
                    pub_date_raw=src_meta.pub_date,
                    collection=src_meta.collection,
                )
                if raw_text is None:
                    logger.info("[ON-DEMAND] %s: no full text (copyright-blocked)", identifier)
                    continue

                # Clean + chunk
                cleaned = clean_text(raw_text)
                chunks = chunk_text(cleaned, source_id=source_id)
                if not chunks:
                    logger.info("[ON-DEMAND] %s: 0 chunks after cleaning", identifier)
                    continue

                # Persist to Postgres
                chunk_ids = []
                for chunk in chunks:
                    pg_id = await conn.fetchval(
                        """
                        INSERT INTO chunks
                            (source_id, text, page_or_section, char_range_start,
                             char_range_end, token_count, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, now())
                        RETURNING id
                        """,
                        source_id, chunk.text, chunk.page_or_section,
                        chunk.char_range_start, chunk.char_range_end, chunk.token_count,
                    )
                    chunk_ids.append(pg_id)

                # Create ChunkWithEmbedding objects
                persisted = [
                    ChunkWithEmbedding(
                        id=pg_id, source_id=chunk_obj.source_id, text=chunk_obj.text,
                        page_or_section=chunk_obj.page_or_section,
                        char_range_start=chunk_obj.char_range_start,
                        char_range_end=chunk_obj.char_range_end,
                        token_count=chunk_obj.token_count,
                    )
                    for chunk_obj, pg_id in zip(chunks, chunk_ids)
                ]

                # Embed
                embedded = embed_chunks(persisted, batch_size=32)

                # Index to OpenSearch + Qdrant
                source_row = SourceRow(
                    source_id=source_id, ia_identifier=identifier,
                    source_type=src_meta.collection or "metadata_only",
                    pub_date_raw=src_meta.pub_date,
                    collection=src_meta.collection, language=src_meta.language,
                )
                index_bm25(persisted, {source_id: source_row}, refresh=True)
                index_vectors(embedded, {source_id: source_row})
                await write_embedding_ids_to_db(embedded, DB_URL)

                total_chunks += len(chunks)
                sources_ingested += 1
                logger.info(
                    "[ON-DEMAND] %s: DONE — %d chunks (%s)",
                    identifier, len(chunks), src_meta.title,
                )

            except Exception as exc:
                logger.error(
                    "[ON-DEMAND] %s failed: %s\n%s",
                    identifier, exc, traceback.format_exc(),
                )
                continue

    finally:
        await conn.close()

    logger.info(
        "[ON-DEMAND] Complete: %d sources ingested, %d chunks added",
        sources_ingested, total_chunks,
    )
    return {
        "sources_found": len(sources),
        "sources_ingested": sources_ingested,
        "chunks_added": total_chunks,
    }


def is_thin_results(unique_sources: int) -> bool:
    """Check if retrieval results are thin enough to trigger on-demand ingestion."""
    return unique_sources < THIN_THRESHOLD
