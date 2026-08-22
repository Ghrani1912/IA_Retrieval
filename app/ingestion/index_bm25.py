"""BM25 indexing into OpenSearch using the bulk API.

Key design decisions (per task 8 review):
- Uses chunk.id as OpenSearch _id → re-ingestion overwrites, not duplicates (Property 13)
- Bulk API, not one-by-one (1,296 chunks: ~2s bulk vs ~2min sequential)
- Source metadata (date, source_type, collection, language) pulled from sources_by_id
  join, since chunks don't carry that data directly
- delete_by_query on ia_identifier before bulk-insert handles stale chunks on re-chunk
- refresh=True only for dev/test; callers should pass refresh=False in production
"""
from __future__ import annotations

import logging
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk

from app.ingestion.opensearch_client import (
    INDEX_NAME,
    delete_chunks_for_source,
    ensure_index,
    get_client,
)
from app.models.pydantic_models import Chunk

logger = logging.getLogger(__name__)


class SourceRow:
    """Minimal source record needed for indexing — avoids importing full SQLAlchemy models."""

    def __init__(
        self,
        source_id: int,
        ia_identifier: str,
        source_type: str,
        pub_date_raw: str | None,
        collection: str | None,
        language: str | None,
    ):
        self.source_id = source_id
        self.ia_identifier = ia_identifier
        self.source_type = source_type
        self.pub_date_raw = pub_date_raw
        self.collection = collection
        self.language = language

    def date_iso(self) -> str | None:
        """Return a clean date string for OpenSearch, or None."""
        if not self.pub_date_raw:
            return None
        # IA dates often come as ISO datetime strings like "1981-01-01T00:00:00Z"
        # Trim to date-only for cleaner indexing
        raw = self.pub_date_raw.strip()
        if "T" in raw:
            return raw.split("T")[0]
        return raw if len(raw) >= 4 else None


def index_bm25(
    chunks: list[Chunk],
    sources_by_id: dict[int, SourceRow],
    client: OpenSearch | None = None,
    index_name: str = INDEX_NAME,
    refresh: bool = True,
) -> int:
    """Bulk-index chunks into OpenSearch.

    Args:
        chunks: Chunk objects with populated id fields (Postgres PKs).
        sources_by_id: Map of source_id → SourceRow for metadata join.
        client: Optional pre-created OpenSearch client (created if None).
        index_name: Target index name.
        refresh: Whether to refresh the index after bulk (True for dev/test only).

    Returns:
        Number of documents successfully indexed.
    """
    if not chunks:
        return 0

    if client is None:
        client = get_client()

    ensure_index(client, index_name)

    # Delete stale chunks for each affected ia_identifier before re-indexing
    identifiers_seen: set[str] = set()
    for chunk in chunks:
        src = sources_by_id.get(chunk.source_id)
        if src and src.ia_identifier not in identifiers_seen:
            delete_chunks_for_source(client, src.ia_identifier, index_name)
            identifiers_seen.add(src.ia_identifier)

    # Build bulk actions
    actions: list[dict[str, Any]] = []
    skipped = 0

    for chunk in chunks:
        if chunk.id is None:
            logger.warning("Chunk has no id — skipping BM25 index (not yet persisted to DB)")
            skipped += 1
            continue

        src = sources_by_id.get(chunk.source_id)
        if src is None:
            logger.warning("No source found for source_id=%d — skipping chunk %d", chunk.source_id, chunk.id)
            skipped += 1
            continue

        doc: dict[str, Any] = {
            "_index": index_name,
            "_id": str(chunk.id),
            "chunk_id": chunk.id,
            "source_id": chunk.source_id,
            "ia_identifier": src.ia_identifier,
            "text": chunk.text,
            "date": src.date_iso(),
            "source_type": src.source_type,
            "collection": src.collection,
            "language": src.language,
            "page_or_section": chunk.page_or_section,
            "capture_timestamp": (
                chunk.capture_timestamp.isoformat() if chunk.capture_timestamp else None
            ),
        }
        actions.append(doc)

    if not actions:
        logger.warning("No indexable chunks (skipped=%d)", skipped)
        return 0

    success_count, errors = bulk(
        client,
        actions,
        refresh=refresh,
        raise_on_error=False,
    )

    if errors:
        logger.error("BM25 bulk index had %d errors: %s", len(errors), errors[:3])
    else:
        logger.info(
            "BM25 indexed %d chunks into '%s' (skipped=%d)",
            success_count, index_name, skipped,
        )

    return success_count
