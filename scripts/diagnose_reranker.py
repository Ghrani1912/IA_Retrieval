"""Diagnose reranker behavior: side-by-side RRF vs reranker for real queries.

For each query:
1. Run BM25 + vector retrieval
2. Show RRF top-10 (with scores and first 120 chars of text)
3. Run reranker on RRF top-30
4. Show reranker top-10 (with scores and first 120 chars)
5. Flag any chunks that were demoted (RRF rank <= 10, reranker rank > 10 or missing)
6. Flag any chunks that were promoted (RRF rank > 10, reranker rank <= 10)
"""
from __future__ import annotations
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.pydantic_models import StructuredQuery
from app.retrieval.retrieve import retrieve_bm25, retrieve_vector, hydrate_chunks
from app.retrieval.rrf import fuse_rrf
from app.retrieval.reranker import rerank, _extract_reranker_window, get_reranker

QUERIES = [
    "knowledge representation frames semantic networks",
    "machine learning inductive inference training data",
    "expert systems MYCIN rule-based reasoning",
    "natural language parsing speech understanding",
    "What planning systems use goal reduction and heuristic search?",
]


def truncate(text: str, n: int = 120) -> str:
    t = text.replace("\n", " ").strip()
    return t[:n] + "..." if len(t) > n else t


async def diagnose_one(query: str) -> None:
    print("\n" + "=" * 80)
    print(f"QUERY: {query}")
    print("=" * 80)

    sq = StructuredQuery(
        raw_query=query,
        topic_keywords=query.split()[:8],
        date_range_start=None,
        date_range_end=None,
        source_type_hint=None,
        is_temporal_comparison=False,
    )

    # Step 1: retrieve
    bm25_results, vector_results = await asyncio.gather(
        retrieve_bm25(sq), retrieve_vector(sq)
    )
    print(f"\nBM25 results: {len(bm25_results)}, Vector results: {len(vector_results)}")

    # Step 2: RRF fusion
    fused = fuse_rrf(bm25_results, vector_results)
    rrf_top10 = fused[:10]

    # Step 3: hydrate RRF top-10 for display
    hydrated_rrf = await hydrate_chunks(list(rrf_top10))

    print("\n--- RRF TOP-10 (before reranker) ---")
    rrf_map = {}
    for item in hydrated_rrf:
        rrf_map[item.chunk.id] = item
        text_preview = truncate(item.chunk.text, 120) if item.chunk.text else "(no text)"
        print(
            f"  RRF#{item.rank:2d}  score={item.score:.4f}  chunk_id={item.chunk.id}  "
            f"src={item.chunk.source_id}  {text_preview}"
        )

    # Step 4: Reranker on RRF top-30
    hydrated_f30 = await hydrate_chunks(list(fused[:30]))
    reranked = rerank(query, hydrated_f30, top_k=10)

    print("\n--- RERANKER TOP-10 (after cross-encoder) ---")
    rerank_map = {}
    for item in reranked:
        rerank_map[item.chunk.id] = item
        text_preview = truncate(item.chunk.text, 120) if item.chunk.text else "(no text)"
        print(
            f"  RR#{item.rank:2d}   score={item.score:.4f}  chunk_id={item.chunk.id}  "
            f"src={item.chunk.source_id}  {text_preview}"
        )

    # Step 5: Compare — demoted/promoted
    rrf_ids_top10 = {item.chunk.id for item in hydrated_rrf}
    rerank_ids_top10 = {item.chunk.id for item in reranked}

    demoted = rrf_ids_top10 - rerank_ids_top10
    promoted = rerank_ids_top10 - rrf_ids_top10

    if demoted:
        print("\n  DEMOTED (in RRF top-10, dropped by reranker):")
        for cid in demoted:
            item = rrf_map[cid]
            print(
                f"    chunk_id={cid}  RRF_rank={item.rank}  RRF_score={item.score:.4f}  "
                f"text={truncate(item.chunk.text, 100)}"
            )
    if promoted:
        print("\n  PROMOTED (not in RRF top-10, added by reranker):")
        for cid in promoted:
            item = rerank_map[cid]
            print(
                f"    chunk_id={cid}  rerank_score={item.score:.4f}  "
                f"text={truncate(item.chunk.text, 100)}"
            )
    if not demoted and not promoted:
        print("\n  NO CHANGE — reranker preserved exact same set as RRF top-10")


async def main():
    # Check reranker is loaded
    r = get_reranker()
    print(f"Reranker loaded: {r is not None}")
    if r is None:
        print("ERROR: reranker not available — cannot diagnose")
        return

    for q in QUERIES:
        await diagnose_one(q)


if __name__ == "__main__":
    asyncio.run(main())
