"""Five retrieval configuration definitions for the evaluation harness.

Each config is a thin composition of Phase 3 modules — no new logic here.
Configs differ only in which retrieval path(s) they use and whether they
apply RRF fusion and cross-encoder reranking.

| Config        | BM25 | Vector | Fusion | Rerank |
|---------------|------|--------|--------|--------|
| vector_only   |  no  |  yes   |   no   |   no   |
| bm25_only     |  yes |  no    |   no   |   no   |
| simple_merge  |  yes |  yes   |  score |   no   |
| rrf           |  yes |  yes   |  RRF   |   no   |
| full_pipeline |  yes |  yes   |  RRF   |  yes   |

Property 17 (final): blended_03 is the production config, chosen for
robustness on edge queries despite blended_05 showing a small MRR edge.
full_pipeline == blended_03 (alpha=0.3). Both outperform rrf on all metrics
corrected multi-label GT. See run_eval.py for the full evidence chain.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from app.models.pydantic_models import RankedChunk, StructuredQuery
from app.retrieval.retrieve import retrieve_bm25, retrieve_vector, hydrate_chunks
from app.retrieval.rrf import fuse_rrf
from app.retrieval.reranker import rerank_blended as rerank_blended_fn


async def _blended_03_no_americana(query: StructuredQuery) -> list[RankedChunk]:
    """RRF top-30 -> blended reranker (alpha=0.3) -> top-10, excluding Americana."""
    bm25, vec = await asyncio.gather(retrieve_bm25(query), retrieve_vector(query))
    fused = fuse_rrf(bm25, vec)
    fused = await hydrate_chunks(fused)
    fused = [r for r in fused if r.chunk.collection != "americana"]
    return rerank_blended_fn(query.raw_query, fused, top_k=TOP_K, alpha=0.3)

logger = logging.getLogger(__name__)

TOP_K = 10          # Final result list size for all configs
CANDIDATE_K = 50    # Candidate pool drawn from each index before fusion


def _interleave(
    bm25: list[RankedChunk],
    vector: list[RankedChunk],
    top_k: int = TOP_K,
) -> list[RankedChunk]:
    """Simple score-based merge: interleave BM25 and vector results by raw score.

    Normalise each list's scores to [0, 1] relative to their own max, then
    merge and take top_k by descending normalised score.  Ties broken by
    preferring BM25 (it's the higher-precision signal on exact-match queries).
    """
    def _norm(items: list[RankedChunk], offset: float) -> list[tuple[float, str, RankedChunk]]:
        if not items:
            return []
        max_s = max(i.score for i in items) or 1.0
        return [((i.score / max_s) + offset, "bm25" if offset else "vec", i)
                for i in items]

    # BM25 gets a tiny tie-break boost (1e-9)
    merged = _norm(bm25, 1e-9) + _norm(vector, 0.0)
    merged.sort(key=lambda x: x[0], reverse=True)

    seen: set[int | None] = set()
    result: list[RankedChunk] = []
    for _, _, item in merged:
        cid = item.chunk.id
        if cid not in seen:
            seen.add(cid)
            item.rank = len(result) + 1
            result.append(item)
        if len(result) >= top_k:
            break
    return result


# ---------------------------------------------------------------------------
# Config runner type
# ---------------------------------------------------------------------------

RetrieveFn = Callable[[StructuredQuery], Awaitable[list[RankedChunk]]]


async def _vector_only(query: StructuredQuery) -> list[RankedChunk]:
    results = await retrieve_vector(query)
    results = results[:TOP_K]
    return await hydrate_chunks(results)


async def _bm25_only(query: StructuredQuery) -> list[RankedChunk]:
    results = await retrieve_bm25(query)
    results = results[:TOP_K]
    return await hydrate_chunks(results)


async def _simple_merge(query: StructuredQuery) -> list[RankedChunk]:
    bm25, vec = await asyncio.gather(retrieve_bm25(query), retrieve_vector(query))
    merged = _interleave(bm25, vec, top_k=TOP_K)
    return await hydrate_chunks(merged)


async def _rrf(query: StructuredQuery) -> list[RankedChunk]:
    bm25, vec = await asyncio.gather(retrieve_bm25(query), retrieve_vector(query))
    fused = fuse_rrf(bm25, vec)[:TOP_K]
    return await hydrate_chunks(fused)


async def _full_pipeline(query: StructuredQuery) -> list[RankedChunk]:
    """RRF top-30 → blended reranker (alpha=0.3, production default) → top-10."""
    bm25, vec = await asyncio.gather(retrieve_bm25(query), retrieve_vector(query))
    fused = fuse_rrf(bm25, vec)
    fused = await hydrate_chunks(fused)
    return rerank_blended_fn(query.raw_query, fused, top_k=TOP_K, alpha=0.3)


async def _blended_05(query: StructuredQuery) -> list[RankedChunk]:
    """RRF top-30 → blended reranker (alpha=0.5, equal blend) → top-10."""
    bm25, vec = await asyncio.gather(retrieve_bm25(query), retrieve_vector(query))
    fused = fuse_rrf(bm25, vec)
    fused = await hydrate_chunks(fused)
    return rerank_blended_fn(query.raw_query, fused, top_k=TOP_K, alpha=0.5)


async def _blended_03(query: StructuredQuery) -> list[RankedChunk]:
    """RRF top-30 → blended reranker (alpha=0.3, RRF-heavy) → top-10."""
    bm25, vec = await asyncio.gather(retrieve_bm25(query), retrieve_vector(query))
    fused = fuse_rrf(bm25, vec)
    fused = await hydrate_chunks(fused)
    return rerank_blended_fn(query.raw_query, fused, top_k=TOP_K, alpha=0.3)


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

CONFIGS: dict[str, RetrieveFn] = {
    "vector_only":   _vector_only,
    "bm25_only":     _bm25_only,
    "simple_merge":  _simple_merge,
    "rrf":           _rrf,
    "blended_05":    _blended_05,
    "blended_03":    _blended_03,
    "blended_03_no_am": _blended_03_no_americana,
    "full_pipeline": _full_pipeline,
}
