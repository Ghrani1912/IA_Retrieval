"""Pre-fusion metadata and temporal filter builders.

Applied BEFORE RRF fusion to both BM25 and vector candidate queries.
This keeps the top-K budget focused on in-scope results (design decision 2).

Key constraint: metadata_only sources are ALWAYS excluded (design.md S.2, Req 10.3).
"""
from __future__ import annotations

from app.models.pydantic_models import StructuredQuery


def build_opensearch_filter(query: StructuredQuery) -> dict:
    """Build OpenSearch bool filter for the given structured query.

    Always excludes metadata_only sources.
    Adds date range, source_type, and collection filters when present.

    Returns:
        OpenSearch bool filter dict (empty must[] = no restriction beyond metadata_only).
    """
    must_not = [{"term": {"source_type": "metadata_only"}}]
    must = []

    if query.date_range_start or query.date_range_end:
        date_range: dict = {}
        if query.date_range_start:
            date_range["gte"] = f"{query.date_range_start}-01-01"
        if query.date_range_end:
            date_range["lte"] = f"{query.date_range_end}-12-31"
        must.append({"range": {"date": date_range}})

    if query.source_type_hint:
        must.append({"term": {"source_type": query.source_type_hint}})

    return {"bool": {"must": must, "must_not": must_not}}


def build_qdrant_filter(query: StructuredQuery) -> dict | None:
    """Build Qdrant filter for the given structured query.

    Returns a Qdrant filter dict or None if only the metadata_only exclusion applies
    (handled separately at query time via must_not).

    The caller is responsible for always adding the metadata_only exclusion.
    """
    conditions = []

    if query.date_range_start or query.date_range_end:
        if query.date_range_start:
            conditions.append({
                "key": "date",
                "range": {"gte": f"{query.date_range_start}-01-01"},
            })
        if query.date_range_end:
            conditions.append({
                "key": "date",
                "range": {"lte": f"{query.date_range_end}-12-31"},
            })

    if query.source_type_hint:
        conditions.append({
            "key": "source_type",
            "match": {"value": query.source_type_hint},
        })

    if not conditions:
        return None

    return {"must": conditions}


def metadata_only_exclusion_opensearch() -> dict:
    """Return an OpenSearch filter that excludes metadata_only sources.
    
    Always applied regardless of other filters.
    """
    return {"bool": {"must_not": [{"term": {"source_type": "metadata_only"}}]}}


def metadata_only_exclusion_qdrant() -> dict:
    """Return a Qdrant filter that excludes metadata_only sources."""
    return {
        "must_not": [
            {"key": "source_type", "match": {"value": "metadata_only"}}
        ]
    }
