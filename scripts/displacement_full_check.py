"""Broad manual check: pull top-10 chunk text for 6 queries."""
import asyncio
import sys

sys.path.insert(0, ".")

from app.retrieval.retrieve import retrieve_bm25, retrieve_vector, hydrate_chunks
from app.retrieval.rrf import fuse_rrf
from app.retrieval.reranker import rerank_blended
from app.models.pydantic_models import StructuredQuery


QUERIES_TO_CHECK = [
    "q001", "q002", "q004", "q007", "q009", "p006",
]


async def check_one(query_id: str, text: str, gt_ids: list[int]):
    sq = StructuredQuery(raw_query=text, topic_keywords=[], date_range=None)
    bm25, vec = await asyncio.gather(retrieve_bm25(sq), retrieve_vector(sq))
    fused = fuse_rrf(bm25, vec)
    fused = await hydrate_chunks(fused)
    ranked = rerank_blended(sq.raw_query, fused, top_k=10, alpha=0.3)

    gt_set = set(gt_ids)
    hits = gt_set.intersection({r.chunk.id for r in ranked})

    print(f"\n{'='*70}")
    print(f"{query_id}: {text[:80]}")
    print(f"GT chunks ({len(gt_ids)}): {gt_ids[:5]}...")
    print(f"GT in top-10: {len(hits)}/{len(gt_ids)}")
    print(f"{'='*70}")

    for r in ranked:
        c = r.chunk
        coll = c.collection or "?"
        is_gt = " [GT]" if c.id in gt_set else ""
        is_am = " [AMERICANA]" if coll == "americana" else ""
        marker = is_gt or is_am
        title = getattr(c, "source_title", None) or f"source_id={c.source_id}"
        print(f"\n  rank={r.rank:2d} score={r.score:.3f} coll={coll}{marker}  chunk={c.id}")
        # Show first 300 chars of actual text
        snippet = c.text[:300].replace("\n", " ").strip()
        print(f"  text: {snippet}")

    return {"hits": len(hits), "gt_count": len(gt_ids)}


async def main():
    with open("app/eval/queries.json") as f:
        import json
        data = json.load(f)

    qlist = {q["id"]: q for q in data["queries"]}

    for qid in QUERIES_TO_CHECK:
        q = qlist.get(qid)
        if q and q.get("relevant_chunk_ids"):
            await check_one(qid, q["query"], q["relevant_chunk_ids"])


if __name__ == "__main__":
    asyncio.run(main())
