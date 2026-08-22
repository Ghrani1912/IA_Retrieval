"""Check whether reranker losses are concentrated or spread across queries."""
import sys, os, asyncio, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.WARNING)

from app.eval.configs import CONFIGS
from app.models.pydantic_models import StructuredQuery

QUERIES_PATH = "app/eval/queries.json"

async def main():
    with open(QUERIES_PATH) as f:
        data = json.load(f)

    labeled, gt_map = [], {}
    for q in data["queries"]:
        labeled.append({
            "query_id": q["id"], "query": q["query"],
            "query_type": q["query_type"], "date_range": q.get("date_range"),
        })
        if q.get("relevant_chunk_ids"):
            gt_map[q["id"]] = set(q["relevant_chunk_ids"])

    eval_q = [l for l in labeled if l["query_id"] in gt_map]

    rrf_fn = CONFIGS["rrf"]
    fp_fn = CONFIGS["full_pipeline"]

    deltas = []
    for i, lq in enumerate(eval_q, 1):
        dr = lq.get("date_range") or {}
        sq = StructuredQuery(
            raw_query=lq["query"],
            topic_keywords=lq["query"].split()[:8],
            date_range_start=dr.get("from"),
            date_range_end=dr.get("to"),
            source_type_hint=None,
            is_temporal_comparison=(lq["query_type"] == "cross_decade_comparison"),
        )
        relevant = gt_map[lq["query_id"]]

        try:
            rrf_ranked = await rrf_fn(sq)
            fp_ranked = await fp_fn(sq)
        except Exception:
            continue

        rrf_top10 = set(r.chunk.id for r in rrf_ranked[:10] if r.chunk.id)
        fp_top10 = set(r.chunk.id for r in fp_ranked[:10] if r.chunk.id)

        rrf_r = len(rrf_top10 & relevant)
        fp_r = len(fp_top10 & relevant)
        delta = fp_r - rrf_r

        deltas.append({
            "id": lq["query_id"],
            "query": lq["query"][:60],
            "type": lq["query_type"],
            "rrf_recall": rrf_r,
            "fp_recall": fp_r,
            "delta": delta,
            "rrf_set": rrf_top10,
            "fp_set": fp_top10,
            "relevant": relevant,
        })

    # Sort by delta (worst first)
    deltas.sort(key=lambda x: x["delta"])

    print("\nPER-QUERY RECALL DELTAS (rrf -> full_pipeline)")
    print("=" * 90)
    print(f"{'ID':8s} {'Type':22s} {'RRF':>4s} {'FP':>4s} {'Delta':>6s}  Query")
    print("-" * 90)
    for d in deltas:
        marker = " ***" if d["delta"] <= -2 else (" *" if d["delta"] == -1 else "")
        print(f"{d['id']:8s} {d['type']:22s} {d['rrf_recall']:4d} {d['fp_recall']:4d} {d['delta']:+6d}  {d['query']}{marker}")

    # Distribution analysis
    print("\n" + "=" * 90)
    print("DISTRIBUTION ANALYSIS")
    print("=" * 90)

    negative = [d for d in deltas if d["delta"] < 0]
    catastrophic = [d for d in negative if d["delta"] <= -2]
    mild = [d for d in negative if d["delta"] == -1]
    positive = [d for d in deltas if d["delta"] > 0]
    unchanged = [d for d in deltas if d["delta"] == 0]

    print(f"\nTotal queries: {len(deltas)}")
    print(f"  Unchanged:   {len(unchanged)} ({len(unchanged)/len(deltas)*100:.0f}%)")
    print(f"  Improved:    {len(positive)} ({len(positive)/len(deltas)*100:.0f}%)")
    print(f"  Hurt (-1):   {len(mild)} ({len(mild)/len(deltas)*100:.0f}%)")
    print(f"  Hurt (<=-2): {len(catastrophic)} ({len(catastraphic)/len(deltas)*100:.0f}%)")

    if catastrophic:
        print(f"\nCATASTROPHIC FAILURES (recall drops 2+):")
        for d in catastrophic:
            lost_chunks = d["rrf_set"] - d["fp_set"]
            gained_chunks = d["fp_set"] - d["rrf_set"]
            relevant_lost = lost_chunks & d["relevant"]
            print(f"  {d['id']} ({d['type']}): recall {d['rrf_recall']}->{d['fp_recall']} (delta={d['delta']})")
            print(f"    Lost {len(lost_chunks)} chunks, {len(relevant_lost)} were relevant")
            print(f"    Query: {d['query']}")

    # Breakdown by query type
    print(f"\nBY QUERY TYPE:")
    type_stats = {}
    for d in deltas:
        t = d["type"]
        if t not in type_stats:
            type_stats[t] = {"count": 0, "deltas": []}
        type_stats[t]["count"] += 1
        type_stats[t]["deltas"].append(d["delta"])

    for t, s in sorted(type_stats.items()):
        avg = sum(s["deltas"]) / len(s["deltas"])
        neg = sum(1 for d in s["deltas"] if d < 0)
        print(f"  {t:25s} n={s['count']:2d}  avg_delta={avg:+.2f}  hurt={neg}/{s['count']}")

    # Top-10 overlap analysis
    print(f"\nRRF vs FULL_PIPELINE TOP-10 OVERLAP:")
    overlaps = []
    for d in deltas:
        overlap = len(d["rrf_set"] & d["fp_set"])
        overlaps.append(overlap)
    print(f"  Average overlap: {sum(overlaps)/len(overlaps):.1f}/10")
    print(f"  Min overlap: {min(overlaps)}")
    print(f"  Max overlap: {max(overlaps)}")
    print(f"  Queries with overlap <=3: {sum(1 for o in overlaps if o <= 3)}")

if __name__ == "__main__":
    asyncio.run(main())
