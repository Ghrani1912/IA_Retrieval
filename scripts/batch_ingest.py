"""Bounded batch ingestion: process un-chunked sources from specific collections.

Usage:
    python scripts/batch_ingest.py                    # defaults: 20 sources
    python scripts/batch_ingest.py --limit 10         # process 10 sources
    python scripts/batch_ingest.py --collection arxiv # only arxiv collection
    python scripts/batch_ingest.py --dry-run          # show what would be processed
"""
import asyncio
import argparse
import logging
import sys
import time

import asyncpg
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("batch_ingest")

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")

# Target collections for corpus widening (ordered by relevance)
TARGET_COLLECTIONS = [
    "arxiv",                    # AI/CS academic papers
    "NASA_NTRS_Archive",        # NASA technical reports
    "ericarchive",              # Education research
]


async def get_uningested_sources(
    conn, collection: str | None = None, limit: int = 20
) -> list[dict]:
    """Fetch sources that have no chunks yet, optionally filtered by collection."""
    where = "s.id NOT IN (SELECT DISTINCT source_id FROM chunks WHERE source_id IS NOT NULL)"
    if collection:
        where += f" AND s.collection = '{collection}'"
    
    query = f"""
        SELECT s.id, s.ia_identifier, s.title, s.collection, s.pub_date_raw, s.language
        FROM sources s
        WHERE {where}
        ORDER BY s.id
        LIMIT {limit}
    """
    rows = await conn.fetch(query)
    return [dict(r) for r in rows]


async def ingest_source(conn, source: dict) -> dict:
    """Run full pipeline on a single source: fetch -> clean -> chunk -> embed -> index."""
    from app.ingestion.fetch import fetch_fulltext
    from app.ingestion.cleaner import clean_text
    from app.ingestion.chunker import chunk_text
    from app.ingestion.embed import embed_chunks
    from app.ingestion.index_bm25 import SourceRow, index_bm25
    from app.ingestion.index_vectors import index_vectors, write_embedding_ids_to_db
    from app.models.pydantic_models import ChunkWithEmbedding

    identifier = source["ia_identifier"]
    source_id = source["id"]
    title = (source["title"] or "untitled")[:80]

    # Fetch
    raw_text = await fetch_fulltext(
        identifier=identifier,
        pub_date_raw=source.get("pub_date_raw"),
        collection=source.get("collection"),
    )
    if raw_text is None:
        return {"identifier": identifier, "status": "no_text", "chunks": 0}

    # Clean
    cleaned = clean_text(raw_text)

    # Chunk
    chunks = chunk_text(cleaned, source_id=source_id)
    if not chunks:
        return {"identifier": identifier, "status": "no_chunks", "chunks": 0}

    # Persist to Postgres
    chunk_ids = []
    for chunk in chunks:
        row_id = await conn.fetchval(
            """
            INSERT INTO chunks (source_id, text, page_or_section, char_range_start,
                                 char_range_end, token_count, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, now())
            RETURNING id
            """,
            source_id, chunk.text, chunk.page_or_section,
            chunk.char_range_start, chunk.char_range_end, chunk.token_count,
        )
        chunk_ids.append(row_id)

    # Embed
    persisted = [
        ChunkWithEmbedding(
            id=pg_id, source_id=c.source_id, text=c.text,
            page_or_section=c.page_or_section,
            char_range_start=c.char_range_start, char_range_end=c.char_range_end,
            token_count=c.token_count,
        )
        for c, pg_id in zip(chunks, chunk_ids)
    ]
    embedded = embed_chunks(persisted, batch_size=32)

    # Index BM25 + vectors
    source_row = SourceRow(
        source_id=source_id, ia_identifier=identifier,
        source_type="paper", pub_date_raw=source.get("pub_date_raw"),
        collection=source.get("collection"), language=source.get("language"),
    )
    index_bm25(persisted, {source_id: source_row}, refresh=True)
    index_vectors(embedded, {source_id: source_row})
    await write_embedding_ids_to_db(embedded, DB_URL)

    return {"identifier": identifier, "status": "ok", "chunks": len(chunks)}


async def main():
    parser = argparse.ArgumentParser(description="Batch ingest un-chunked sources")
    parser.add_argument("--limit", type=int, default=20, help="Max sources to process")
    parser.add_argument("--collection", type=str, default=None, help="Filter by collection")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed")
    parser.add_argument("--collections", type=str, nargs="*", default=None,
                        help="Process from these collections in order")
    args = parser.parse_args()

    conn = await asyncpg.connect(DB_URL, ssl=False)

    collections = args.collections or TARGET_COLLECTIONS
    if args.collection:
        collections = [args.collection]

    grand_total_chunks = 0
    grand_total_sources = 0
    batch_start = time.time()

    for coll in collections:
        logger.info(f"=== Collection: {coll} ===")
        sources = await get_uningested_sources(conn, collection=coll, limit=args.limit)
        logger.info(f"  Found {len(sources)} un-ingested sources")

        if not sources:
            logger.info(f"  Nothing to do for {coll}, skipping")
            continue

        if args.dry_run:
            for s in sources[:10]:
                logger.info(f"  [DRY] {s['ia_identifier']}: {(s['title'] or 'untitled')[:60]}")
            if len(sources) > 10:
                logger.info(f"  ... and {len(sources) - 10} more")
            continue

        ok = 0
        skipped = 0
        failed = 0
        total_chunks = 0

        for i, src in enumerate(sources):
            identifier = src["ia_identifier"]
            title = (src["title"] or "untitled")[:50]
            logger.info(f"  [{i+1}/{len(sources)}] {identifier}: {title}")

            try:
                result = await ingest_source(conn, src)
                if result["status"] == "ok":
                    ok += 1
                    total_chunks += result["chunks"]
                    logger.info(f"    OK: {result['chunks']} chunks")
                else:
                    skipped += 1
                    logger.info(f"    SKIPPED: {result['status']}")
            except Exception as exc:
                failed += 1
                logger.error(f"    FAILED: {exc}")

            # Small delay between sources to be nice to IA
            await asyncio.sleep(1)

        logger.info(f"  {coll} done: {ok} ingested, {skipped} skipped, {failed} failed, {total_chunks} chunks")
        grand_total_sources += ok
        grand_total_chunks += total_chunks

        # Delay between collections
        if collections.index(coll) < len(collections) - 1:
            logger.info("  Pausing 5s before next collection...")
            await asyncio.sleep(5)

    elapsed = time.time() - batch_start
    if not args.dry_run:
        logger.info(f"\n=== BATCH COMPLETE ===")
        logger.info(f"  Sources ingested: {grand_total_sources}")
        logger.info(f"  Chunks created: {grand_total_chunks}")
        logger.info(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f}m)")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
