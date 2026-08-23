"""Check whether ground-truth chunks are still retrieved in top-10."""
import asyncio
import json
import sys

# Add project root to path
sys.path.insert(0, ".")

from app.retrieval.retrieve import retrieve_bm25, retrieve_vector, hydrate_chunks
from app.retrieval.rrf import fuse_rrf
from app.retrieval.reranker import rerank_blended
from app.models.pydantic_models import StructuredQuery


async def check_query(q: dict, k: int = 10):
    """Run query and check if ground-truth chunks appear in top-k."""
    sq = StructuredQuery(
        raw_query=q["query"],
        topic_keywords=[],
        date_range=None,
    )

    bm25, vec = await asyncio.gather(retrieve_bm25(sq), retrieve_vector(sq))
    fused = fuse_rrf(bm25, vec)
    fused = await hydrate_chunks(fused)
    ranked = rerank_blended(sq.raw_query, fused, top_k=k, alpha=0.3)

    retrieved_ids = [r.chunk.id for r in ranked]
    gt_ids = set(q.get("relevant_chunk_ids", []))

    hits = gt_ids.intersection(set(retrieved_ids))
    missed = gt_ids - set(retrieved_ids)

    # For missed chunks, find what rank they got (if at all)
    all_ids_in_extended = {r.chunk.id: i+1 for i, r in enumerate(
        rerank_blended(sq.raw_query, fused, top_k=50, alpha=0.3)
    )}

    missed_ranks = {cid: all_ids_in_extended.get(cid, ">50") for cid in missed}

    return {
        "id": q["id"],
        "query": q["query"][:60],
        "gt_count": len(gt_ids),
        "hits_in_top10": len(hits),
        "missed": len(missed),
        "missed_ranks": missed_ranks,
        "retrieved_ids_top10": retrieved_ids,
        "top10_collections": [r.chunk.collection for r in ranked],
    }


async def main():
    with open("app/eval/queries.json") as f:
        data = json.load(f)

    qlist = data["queries"]

    # Pick 10 queries with ground truth
    test_queries = [q for q in qlist if q.get("relevant_chunk_ids")][:10]

    print(f"Checking {len(test_queries)} queries against 10,671-chunk corpus...\n")

    results = []
    for q in test_queries:
        r = await check_query(q)
        results.append(r)
        status = "OK" if r["hits_in_top10"] == r["gt_count"] else f"MISSED {r['missed']}/{r['gt_count']}"
        print(f"  {r['id']}: {r['hits_in_top10']}/{r['gt_count']} hits — {status}")
        if r["missed"] > 0:
            for cid, rank in r["missed_ranks"].items():
                print(f"    chunk {cid} → rank {rank}")
        # Show top-10 collection distribution
        colls = {}
        for c in r["top10_collections"]:
            colls[c] = colls.get(c, 0) + 1
        print(f"    top-10 composition: {colls}")

    # Summary
    total_gt = sum(r["gt_count"] for r in results)
    total_hits = sum(r["hits_in_top10"] for r in results)
    total_missed = sum(r["missed"] for r in results)

    print(f"\n{'='*60}")
    print(f"SUMMARY: {total_hits}/{total_gt} ground-truth chunks in top-10 ({total_hits/total_gt*100:.1f}%)")
    print(f"Displaced: {total_missed}/{total_gt} chunks ({total_missed/total_gt*100:.1f}%)")

    # What collections are displacing?
    all_colls = {}
    for r in results:
        for c in r["top10_collections"]:
            all_colls[c] = all_colls.get(c, 0) + 1
    print(f"Top-10 collection distribution across all queries: {all_colls}")


if __name__ == "__main__":
    asyncio.run(main())
