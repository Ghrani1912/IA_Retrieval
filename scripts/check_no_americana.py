"""Test: what happens if we exclude Americana from retrieval entirely?"""
import asyncio
import json
import sys

sys.path.insert(0, ".")

from app.retrieval.retrieve import retrieve_bm25, retrieve_vector, hydrate_chunks
from app.retrieval.rrf import fuse_rrf
from app.retrieval.reranker import rerank_blended
from app.models.pydantic_models import StructuredQuery


async def check_with_filter(q: dict, exclude_collection: str | None = None):
    sq = StructuredQuery(raw_query=q["query"], topic_keywords=[], date_range=None)

    bm25, vec = await asyncio.gather(retrieve_bm25(sq), retrieve_vector(sq))
    fused = fuse_rrf(bm25, vec)
    fused = await hydrate_chunks(fused)

    # Filter after hydration (collection is populated then)
    if exclude_collection:
        fused = [r for r in fused if r.chunk.collection != exclude_collection]

    ranked = rerank_blended(sq.raw_query, fused, top_k=10, alpha=0.3)

    gt_ids = set(q.get("relevant_chunk_ids", []))
    retrieved_ids = [r.chunk.id for r in ranked]
    hits = gt_ids.intersection(set(retrieved_ids))

    colls = {}
    for r in ranked:
        c = r.chunk.collection
        colls[c] = colls.get(c, 0) + 1

    return {
        "hits": len(hits),
        "gt_count": len(gt_ids),
        "collections": colls,
    }


async def main():
    with open("app/eval/queries.json") as f:
        data = json.load(f)

    qlist = data["queries"]
    test_queries = [q for q in qlist if q.get("relevant_chunk_ids")][:10]

    for mode in ["baseline", "no_americana"]:
        total_hits = 0
        total_gt = 0
        all_colls = {}

        for q in test_queries:
            if mode == "no_americana":
                r = await check_with_filter(q, exclude_collection="americana")
            else:
                r = await check_with_filter(q)

            total_hits += r["hits"]
            total_gt += r["gt_count"]
            for c, n in r["collections"].items():
                all_colls[c] = all_colls.get(c, 0) + n

        print(f"{mode:20s}: GT_recall={total_hits}/{total_gt} ({total_hits/total_gt*100:.1f}%), collections={all_colls}")


if __name__ == "__main__":
    asyncio.run(main())
