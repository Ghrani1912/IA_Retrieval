"""Parallel BM25 and vector retrieval with pre-fusion filters.

Executes BM25 and vector queries concurrently via asyncio.gather.
Pre-fusion filters applied before merge to keep top-K budget on in-scope results.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncpg

from app.config import settings
from app.ingestion.opensearch_client import get_client
from app.models.pydantic_models import Chunk, RankedChunk, SourceMetadata, StructuredQuery
from app.retrieval.filters import build_opensearch_filter, build_qdrant_filter

logger = logging.getLogger(__name__)

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")

BM25_TOP_K = 50
VECTOR_TOP_K = 50


# ─────────────────────────────────────────────────────────────────────────────
# BM25 retrieval
# ─────────────────────────────────────────────────────────────────────────────

def _retrieve_bm25_sync(query: StructuredQuery) -> list[RankedChunk]:
    """Synchronous BM25 search (wrapped in async below)."""
    client = get_client()
    os_filter = build_opensearch_filter(query)
    topic = " ".join(query.topic_keywords) if query.topic_keywords else query.raw_query

    body: dict[str, Any] = {
        "query": {
            "bool": {
                "must": {"match": {"text": topic}},
                "filter": os_filter,
            }
        },
        "size": BM25_TOP_K,
        "_source": ["chunk_id", "source_id", "ia_identifier", "text",
                    "page_or_section", "source_type", "collection"],
    }

    resp = client.search(index="chunks", body=body)
    hits = resp["hits"]["hits"]

    results: list[RankedChunk] = []
    for rank, hit in enumerate(hits, start=1):
        s = hit["_source"]
        chunk = Chunk(
            id=s.get("chunk_id"),
            source_id=s.get("source_id", 0),
            text=s.get("text", ""),
            page_or_section=s.get("page_or_section"),
            char_range_start=0,
            char_range_end=len(s.get("text", "")),
        )
        results.append(RankedChunk(
            chunk=chunk,
            rank=rank,
            score=hit["_score"],
        ))

    logger.debug("BM25 returned %d results for query: %r", len(results), topic)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Vector retrieval
# ─────────────────────────────────────────────────────────────────────────────

def _retrieve_vector_sync(query: StructuredQuery) -> list[RankedChunk]:
    """Synchronous vector search (wrapped in async below)."""
    from app.ingestion.embed import embed_chunks, get_model
    from app.ingestion.index_vectors import get_qdrant_client, COLLECTION_NAME
    from qdrant_client.http.models import Filter, FieldCondition, MatchValue, Range

    # Embed the query
    model = get_model()
    topic = " ".join(query.topic_keywords) if query.topic_keywords else query.raw_query
    out = model.encode([topic], batch_size=1, return_dense=True,
                       return_sparse=False, return_colbert_vecs=False)
    query_vec = out["dense_vecs"][0].tolist()

    # Build Qdrant filter — exclude metadata_only + source_type match.
    # Date filtering is done in Python below because Qdrant's Range only
    # supports numeric fields and our date payload is a string 'YYYY-MM-DD'.
    q_filter = Filter(
        must_not=[FieldCondition(key="source_type", match=MatchValue(value="metadata_only"))],
    )
    qdrant_filter_data = build_qdrant_filter(query)
    extra_must = []
    if qdrant_filter_data:
        for cond in qdrant_filter_data.get("must", []):
            if "match" in cond:
                extra_must.append(FieldCondition(
                    key=cond["key"],
                    match=MatchValue(value=cond["match"]["value"]),
                ))
            # Date range handled in Python post-filter below
    if extra_must:
        q_filter = Filter(
            must=extra_must,
            must_not=[FieldCondition(key="source_type", match=MatchValue(value="metadata_only"))],
        )

    qdrant_client = get_qdrant_client()
    if hasattr(qdrant_client, "query_points"):
        res = qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vec,
            query_filter=q_filter,
            limit=VECTOR_TOP_K,
            with_payload=True,
        )
        hits = res.points
    else:
        hits = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vec,
            query_filter=q_filter,
            limit=VECTOR_TOP_K,
            with_payload=True,
        )

    # --- Python-side date filtering (Qdrant Range only supports numerics) ---
    date_start = query.date_range_start  # e.g. 1979
    date_end = query.date_range_end      # e.g. 1998

    results: list[RankedChunk] = []
    for rank, hit in enumerate(hits, start=1):
        p = hit.payload or {}

        # Filter by date if range specified
        if date_start or date_end:
            raw_date = p.get("date", "")  # e.g. "1976-01-01"
            if raw_date:
                try:
                    chunk_year = int(raw_date[:4])
                    if date_start and chunk_year < date_start:
                        continue
                    if date_end and chunk_year > date_end:
                        continue
                except (ValueError, TypeError):
                    continue  # unparseable date → exclude

        chunk = Chunk(
            id=p.get("chunk_db_id"),
            source_id=p.get("source_id", 0),
            text="",  # payload doesn't carry full text; fetched later if needed
            page_or_section=p.get("page_or_section"),
            char_range_start=0,
            char_range_end=0,
        )
        results.append(RankedChunk(
            chunk=chunk,
            rank=len(results) + 1,
            score=hit.score,
        ))

    logger.debug(
        "Vector search returned %d results (date filter: %s–%s)",
        len(results), date_start, date_end,
    )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Async wrappers — run sync functions in thread executor
# ─────────────────────────────────────────────────────────────────────────────

async def retrieve_bm25(query: StructuredQuery) -> list[RankedChunk]:
    """Async BM25 retrieval."""
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _retrieve_bm25_sync, query)
    except Exception as exc:
        logger.error("BM25 retrieval failed: %s", exc)
        return []


async def retrieve_vector(query: StructuredQuery) -> list[RankedChunk]:
    """Async vector retrieval."""
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _retrieve_vector_sync, query)
    except Exception as exc:
        logger.error("Vector retrieval failed: %s", exc)
        return []


async def retrieve_parallel(query: StructuredQuery) -> tuple[list[RankedChunk], list[RankedChunk]]:
    """Execute BM25 and vector retrieval concurrently.

    Returns:
        (bm25_results, vector_results) — either may be empty if retrieval fails.
    """
    bm25_results, vector_results = await asyncio.gather(
        retrieve_bm25(query),
        retrieve_vector(query),
        return_exceptions=False,
    )
    return bm25_results, vector_results


async def hydrate_chunks(ranked: list[RankedChunk]) -> list[RankedChunk]:
    """Fill missing chunk text and source metadata from Postgres.

    Vector search payloads omit full text; reranking and synthesis need it.
    """
    chunk_ids = [r.chunk.id for r in ranked if r.chunk.id is not None]
    if not chunk_ids:
        return ranked

    conn = await asyncpg.connect(DB_URL, ssl=False)
    rows = await conn.fetch(
        """
        SELECT c.id, c.source_id, c.text, c.page_or_section, c.capture_timestamp,
               c.char_range_start, c.char_range_end, c.token_count,
               s.ia_identifier, s.title, s.author, s.publisher, s.pub_date_raw,
               s.language, s.subject, s.collection, s.ia_url, s.source_type
        FROM chunks c
        JOIN sources s ON s.id = c.source_id
        WHERE c.id = ANY($1::int[])
        """,
        chunk_ids,
    )
    await conn.close()

    by_id: dict[int, dict] = {r["id"]: dict(r) for r in rows}
    hydrated: list[RankedChunk] = []

    for item in ranked:
        cid = item.chunk.id
        if cid is None or cid not in by_id:
            hydrated.append(item)
            continue

        row = by_id[cid]
        raw_text = row["text"] or item.chunk.text
        # Parse year from pub_date_raw (e.g. '1975' or '1975-06-01' or None)
        year_val = None
        pub_date_val = row.get("pub_date_raw")
        if pub_date_val:
            try:
                year_val = int(pub_date_val[:4])
            except (ValueError, TypeError):
                pass
        # Parse page_number from page_or_section (e.g. '14' or 'Chapter 3')
        page_num = None
        page_str = row.get("page_or_section")
        if page_str:
            try:
                page_num = int(page_str)
            except (ValueError, TypeError):
                pass
        # Build a 200-char snippet from the chunk text
        snippet = raw_text[:200].replace("\n", " ").strip()
        item.chunk = Chunk(
            id=row["id"],
            source_id=row["source_id"],
            text=raw_text,
            page_or_section=row["page_or_section"],
            capture_timestamp=row["capture_timestamp"],
            char_range_start=row["char_range_start"],
            char_range_end=row["char_range_end"],
            token_count=row["token_count"],
            # Source metadata fields for frontend citation cards
            source_title=row.get("title"),
            author=row.get("author"),
            collection=row.get("collection"),
            source_type=row.get("source_type"),
            ia_url=row.get("ia_url"),
            year=year_val,
            pub_date=pub_date_val,
            page_number=page_num,
            snippet=snippet,
            ia_identifier=row.get("ia_identifier"),
        )
        item.source_metadata = SourceMetadata(
            ia_identifier=row["ia_identifier"],
            title=row["title"],
            author=row["author"],
            publisher=row["publisher"],
            pub_date=row["pub_date_raw"],
            language=row["language"],
            subject=list(row["subject"] or []),
            collection=row["collection"],
            ia_url=row["ia_url"],
        )
        hydrated.append(item)

    return hydrated
