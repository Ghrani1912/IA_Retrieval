"""Reciprocal Rank Fusion (RRF) score fusion.

Merges BM25 and vector candidate ranked lists into a single ranked list.
Formula: score(chunk) = sum(1 / (k + rank_i)) for each list chunk appears in.
k=60 is the standard default from Cormack et al. (2009).

This module is purely deterministic — no external calls, no randomness.
Properties 5 (RRF formula correctness) and 3 (coverage) apply here.
"""
from __future__ import annotations

from app.models.pydantic_models import Chunk, RankedChunk

K = 60      # Standard RRF parameter
TOP_N = 30  # Number of candidates to return after fusion
MAX_PER_COLLECTION = 5  # Diversity cap: no more than N results from any one collection


def fuse_rrf(
    bm25_results: list[RankedChunk],
    vector_results: list[RankedChunk],
    k: int = K,
    top_n: int = TOP_N,
) -> list[RankedChunk]:
    """Fuse two ranked lists using Reciprocal Rank Fusion.

    Args:
        bm25_results: BM25 candidates, ordered by rank (rank=1 is best).
        vector_results: Vector candidates, ordered by rank.
        k: RRF smoothing parameter (default 60).
        top_n: Number of results to return (default 30).

    Returns:
        Fused list of RankedChunk, sorted by descending RRF score, top_n items.
    """
    scores: dict[int, float] = {}           # chunk_id → RRF score
    chunks_by_id: dict[int, Chunk] = {}     # chunk_id → Chunk object
    source_metadata: dict[int, object] = {} # chunk_id → source metadata

    def _process_list(ranked_list: list[RankedChunk]) -> None:
        for item in ranked_list:
            chunk_id = item.chunk.id
            if chunk_id is None:
                continue
            rank = item.rank
            contribution = 1.0 / (k + rank)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + contribution
            chunks_by_id[chunk_id] = item.chunk
            if item.source_metadata:
                source_metadata[chunk_id] = item.source_metadata

    _process_list(bm25_results)
    _process_list(vector_results)

    # Sort by descending RRF score
    sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)

    result: list[RankedChunk] = []
    for new_rank, chunk_id in enumerate(sorted_ids[:top_n], start=1):
        result.append(RankedChunk(
            chunk=chunks_by_id[chunk_id],
            rank=new_rank,
            score=scores[chunk_id],
            source_metadata=source_metadata.get(chunk_id),
        ))

    return result
