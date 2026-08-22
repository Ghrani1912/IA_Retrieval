"""Qdrant vector indexing.

Key design decisions (per task 9 review):
- chunk.id as Qdrant point ID → upsert is naturally idempotent (Property 14)
- delete_by_filter on ia_identifier before upsert handles removed chunks on re-chunk
- Source metadata in payload for filtered search without DB join at query time
- embedding_id written back to Postgres chunks table after successful upsert
- Qdrant collection created once at startup via ensure_collection(), not per-run
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import settings
from app.ingestion.index_bm25 import SourceRow
from app.models.pydantic_models import ChunkWithEmbedding

logger = logging.getLogger(__name__)

COLLECTION_NAME = settings.qdrant_collection  # "chunks"
VECTOR_DIM = 1024


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def ensure_collection(client: QdrantClient, collection_name: str = COLLECTION_NAME) -> None:
    """Create the Qdrant collection if it doesn't exist.

    Called once at startup or via setup script — not per ingestion run.
    """
    existing = [c.name for c in client.get_collections().collections]
    if collection_name in existing:
        logger.debug("Qdrant collection '%s' already exists", collection_name)
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
    )
    logger.info(
        "Created Qdrant collection '%s' (dim=%d, distance=COSINE)",
        collection_name,
        VECTOR_DIM,
    )


def _delete_vectors_for_source(
    client: QdrantClient, ia_identifier: str, collection_name: str = COLLECTION_NAME
) -> None:
    """Delete all Qdrant points for a given ia_identifier before re-ingestion."""
    client.delete(
        collection_name=collection_name,
        points_selector=FilterSelector(
            filter=Filter(
                must=[
                    FieldCondition(
                        key="ia_identifier",
                        match=MatchValue(value=ia_identifier),
                    )
                ]
            )
        ),
    )
    logger.debug("Deleted existing Qdrant points for ia_identifier=%r", ia_identifier)


def index_vectors(
    chunks: list[ChunkWithEmbedding],
    sources_by_id: dict[int, SourceRow],
    client: QdrantClient | None = None,
    collection_name: str = COLLECTION_NAME,
) -> int:
    """Upsert chunk embeddings into Qdrant.

    Args:
        chunks: ChunkWithEmbedding objects (must have populated id fields).
        sources_by_id: Source metadata map for payload enrichment.
        client: Optional pre-created Qdrant client.
        collection_name: Target Qdrant collection.

    Returns:
        Number of points successfully upserted.
    """
    if not chunks:
        return 0

    if client is None:
        client = get_qdrant_client()

    ensure_collection(client, collection_name)

    # Delete stale vectors for each affected source before upserting new ones
    identifiers_seen: set[str] = set()
    for chunk in chunks:
        src = sources_by_id.get(chunk.source_id)
        if src and src.ia_identifier not in identifiers_seen:
            _delete_vectors_for_source(client, src.ia_identifier, collection_name)
            identifiers_seen.add(src.ia_identifier)

    # Build Qdrant points
    points: list[PointStruct] = []
    skipped = 0

    for chunk in chunks:
        if chunk.id is None:
            logger.warning("Chunk has no id — skipping vector index (not yet persisted)")
            skipped += 1
            continue

        src = sources_by_id.get(chunk.source_id)
        if src is None:
            logger.warning("No source for source_id=%d — skipping", chunk.source_id)
            skipped += 1
            continue

        payload: dict[str, Any] = {
            "source_id": chunk.source_id,
            "ia_identifier": src.ia_identifier,
            "date": src.date_iso(),
            "source_type": src.source_type,
            "collection": src.collection,
            "language": src.language,
            "capture_timestamp": (
                chunk.capture_timestamp.isoformat() if chunk.capture_timestamp else None
            ),
            "chunk_db_id": chunk.id,
            "page_or_section": chunk.page_or_section,
        }

        points.append(
            PointStruct(
                id=chunk.id,
                vector=chunk.embedding,
                payload=payload,
            )
        )

    if not points:
        logger.warning("No indexable vectors (skipped=%d)", skipped)
        return 0

    # Upsert in batches of 100 to avoid large payloads
    batch_size = 100
    total_upserted = 0
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(collection_name=collection_name, points=batch)
        total_upserted += len(batch)
        logger.debug("Upserted batch %d-%d", i, i + len(batch))

    logger.info(
        "Qdrant indexed %d vectors into '%s' (skipped=%d)",
        total_upserted, collection_name, skipped,
    )
    return total_upserted


async def write_embedding_ids_to_db(
    chunks: list[ChunkWithEmbedding],
    db_url: str,
) -> None:
    """Write chunk.id as embedding_id back to the Postgres chunks table.

    Qdrant point ID == chunk.id so embedding_id = chunk.id.
    Skipping this step means losing traceability from DB chunk → vector.
    """
    if not chunks:
        return

    conn = await asyncpg.connect(db_url, ssl=False)
    try:
        await conn.executemany(
            "UPDATE chunks SET embedding_id = $1 WHERE id = $2",
            [(str(c.id), c.id) for c in chunks if c.id is not None],
        )
        logger.info("Wrote embedding_id back to %d chunk rows", len(chunks))
    finally:
        await conn.close()
