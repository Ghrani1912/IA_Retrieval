"""Eval config: blended_03 with Americana excluded from retrieval."""
import asyncio
from app.retrieval.retrieve import retrieve_bm25, retrieve_vector, hydrate_chunks
from app.retrieval.rrf import fuse_rrf
from app.retrieval.reranker import rerank_blended
from app.models.pydantic_models import StructuredQuery, RankedChunk

TOP_K = 10


async def _blended_03_no_americana(query: StructuredQuery) -> list[RankedChunk]:
    """RRF top-30 -> blended reranker (alpha=0.3) -> top-10, excluding Americana."""
    bm25, vec = await asyncio.gather(retrieve_bm25(query), retrieve_vector(query))
    fused = fuse_rrf(bm25, vec)
    fused = await hydrate_chunks(fused)
    # Exclude Americana — its broad reference text drowns out specific technical content
    fused = [r for r in fused if r.chunk.collection != "americana"]
    return rerank_blended(query.raw_query, fused, top_k=TOP_K, alpha=0.3)
