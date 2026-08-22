"""Run all 7 retrieval configs and print comparison table."""
import sys, os, time, json, asyncio, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg
from app.config import settings
from app.eval.configs import CONFIGS
from app.eval.metrics import compute_metrics
from app.models.pydantic_models import StructuredQuery
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")

CONFIG_ORDER = ["vector_only", "bm25_only", "simple_merge", "rrf", "blended_03", "blended_05", "full_pipeline"]

async def run():
    with open("app/eval/queries.json") as f:
        data = json.load(f)

    labeled, gt = [], []
    for q in data["queries"]:
        labeled.append({"query_id": q["id"], "query": q["query"],
                        "query_type": q["query_type"], "date_range": q.get("date_range")})
        if q.get("relevant_chunk_ids"):
            gt.append({"query_id": q["id"], "relevant_chunk_ids": q["relevant_chunk_ids"]})

    eval_q = [l for l in labeled if any(g["query_id"] == l["query_id"] for g in gt)]
    logger.info("Eval: %d queries", len(eval_q))

    conn = await asyncpg.connect(DB_URL, ssl=False)
    results = {}

    for cname in CONFIG_ORDER:
        fn = CONFIGS[cname]
        t0 = time.time()
        config_results = []
        for i, lq in enumerate(eval_q, 1):
            dr = lq.get("date_range") or {}
            sq = StructuredQuery(
                raw_query=lq["query"], topic_keywords=lq["query"].split()[:8],
                date_range_start=dr.get("from"), date_range_end=dr.get("to"),
                source_type_hint=None,
                is_temporal_comparison=(lq["query_type"] == "cross_decade_comparison"))
            try:
                ranked = await fn(sq)
                cids = [r.chunk.id for r in ranked if r.chunk.id]
            except Exception as e:
                logger.warning("FAILED %s: %s", lq["query_id"], e)
                cids = []
            config_results.append({"query_id": lq["query_id"], "retrieved_chunk_ids": cids})

        elapsed = time.time() - t0
        m = compute_metrics(config_results, gt, k=10)
        results[cname] = {"R@10": m.recall_10, "MRR": m.mrr, "nDCG": m.ndcg_10, "time": elapsed}
        logger.info("  %15s  R@10=%.4f  MRR=%.4f  nDCG=%.4f  (%.0fs)", cname, m.recall_10, m.mrr, m.ndcg_10, elapsed)

        await conn.execute("""INSERT INTO eval_runs
            (config_name, recall_10, precision_10, mrr, ndcg_10, citation_correctness, query_count, run_at)
            VALUES ($1,$2,$3,$4,$5,NULL,$6,$7)""",
            cname, m.recall_10, m.precision_10, m.mrr, m.ndcg_10, len(eval_q), datetime.now(timezone.utc))

    await conn.close()

    # Print comparison table
    print("\n" + "="*72)
    print(f"{'Config':15s} {'R@10':>8s} {'MRR':>8s} {'nDCG':>8s} {'Time':>8s}")
    print("-"*72)
    for cname in CONFIG_ORDER:
        r = results[cname]
        print(f"{cname:15s} {r['R@10']:8.4f} {r['MRR']:8.4f} {r['nDCG']:8.4f} {r['time']:7.0f}s")
    print("="*72)

    # Property 17 check
    fp = results["full_pipeline"]["R@10"]
    for cname in ["vector_only", "bm25_only"]:
        v = results[cname]["R@10"]
        status = "HOLDS" if fp > v else "VIOLATED"
        print(f"  full_pipeline R@10 ({fp:.4f}) vs {cname} ({v:.4f}): {status}")

if __name__ == "__main__":
    asyncio.run(run())
