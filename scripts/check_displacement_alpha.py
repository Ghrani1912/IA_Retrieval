"""Check displacement at alpha=0.3 vs alpha=0.5 vs alpha=0.7."""
import asyncio
import json
import sys

sys.path.insert(0, ".")

from app.retrieval.retrieve import retrieve_bm25, retrieve_vector, hydrate_chunks
from app.retrieval.rrf import fuse_rrf
from app.retrieval.reranker import rerank_blended
from app.models.pydantic_models import StructuredQuery


async def check_at_alpha(q: dict, alpha: float):
    sq = StructuredQuery(raw_query=q["query"], topic_keywords=[], date_range=None)
    bm25, vec = await asyncio.gather(retrieve_bm25(sq), retrieve_vector(sq))
    fused = fuse_rrf(bm25, vec)
    fused = await hydrate_chunks(fused)
    ranked = rerank_blended(sq.raw_query, fused, top_k=10, alpha=alpha)

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
        "americana_in_top10": colls.get("americana", 0),
        "dtic_in_top10": colls.get("dticarchive", 0),
        "eric_in_top10": colls.get("ericarchive", 0),
        "collections": colls,
    }


async def main():
    with open("app/eval/queries.json") as f:
        data = json.load(f)

    qlist = data["queries"]
    test_queries = [q for q in qlist if q.get("relevant_chunk_ids")][:10]

    for alpha in [0.3, 0.5, 0.7, 0.9]:
        total_hits = 0
        total_gt = 0
        total_americana = 0

        for q in test_queries:
            r = await check_at_alpha(q, alpha)
            total_hits += r["hits"]
            total_gt += r["gt_count"]
            total_americana += r["americana_in_top10"]

        print(f"alpha={alpha}: GT_recall={total_hits}/{total_gt} ({total_hits/total_gt*100:.1f}%), "
              f"americana_slots={total_americana}/100")


if __name__ == "__main__":
    asyncio.run(main())
