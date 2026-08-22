"""OpenSearch client and index management.

Creates the chunks index with explicit mapping from design.md section 3.3.
Never lets OpenSearch auto-infer types — date/keyword fields need exact-match
semantics, and text needs the english analyzer for BM25 quality.
"""
from __future__ import annotations

import logging

from opensearchpy import OpenSearch

from app.config import settings

logger = logging.getLogger(__name__)

INDEX_NAME = settings.opensearch_index  # "chunks"

INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "properties": {
            "chunk_id":          {"type": "integer"},
            "source_id":         {"type": "integer"},
            "ia_identifier":     {"type": "keyword"},
            "text":              {"type": "text", "analyzer": "english"},
            "date":              {"type": "date",    "ignore_malformed": True},
            "source_type":       {"type": "keyword"},
            "collection":        {"type": "keyword"},
            "language":          {"type": "keyword"},
            "capture_timestamp": {"type": "date",    "ignore_malformed": True},
            "page_or_section":   {"type": "keyword"},
        }
    },
}


def get_client() -> OpenSearch:
    """Return an OpenSearch client connected to the configured host."""
    return OpenSearch(
        hosts=[settings.opensearch_url],
        http_compress=True,
        use_ssl=False,
        verify_certs=False,
        ssl_assert_hostname=False,
        ssl_show_warn=False,
    )


def ensure_index(client: OpenSearch, index_name: str = INDEX_NAME) -> None:
    """Create the chunks index with explicit mapping if it doesn't already exist."""
    if client.indices.exists(index=index_name):
        logger.debug("Index '%s' already exists — skipping creation", index_name)
        return

    client.indices.create(index=index_name, body=INDEX_MAPPING)
    logger.info("Created OpenSearch index '%s' with explicit mapping", index_name)


def delete_chunks_for_source(
    client: OpenSearch, ia_identifier: str, index_name: str = INDEX_NAME
) -> int:
    """Delete all chunk documents for a given ia_identifier before re-ingestion.

    This handles the case where re-chunking produces fewer chunks — stale chunks
    would otherwise linger indefinitely (Property 13 idempotence requirement).

    Returns:
        Number of documents deleted.
    """
    result = client.delete_by_query(
        index=index_name,
        body={"query": {"term": {"ia_identifier": ia_identifier}}},
        refresh=True,
    )
    deleted = result.get("deleted", 0)
    if deleted:
        logger.info(
            "Deleted %d stale chunks for ia_identifier=%r before re-indexing",
            deleted,
            ia_identifier,
        )
    return deleted
