"""Standalone eval runner — separate process, fresh model loads."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import logging
from datetime import datetime, timezone

import asyncpg
from app.config import settings
from app.eval.configs import CONFIGS
from app.eval.metrics import compute_metrics
from app.models.pydantic_models import StructuredQuery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


def _load_queries(path):
    with open(path) as f:
        data = json.load(f)
    labeled, ground_truth = [], []
    for q in data["queries"]:
        labeled.append({
            "query_id": q["id"], "query": q["query"],
            "query_type": q["query_type"], "date_range": q.get("date_range"),
        })
        if q.get("relevant_chunk_ids"):
            ground_truth.append({
                "query_id": q["id"],
                "relevant_chunk_ids": q["relevant_chunk_ids"],
            })
    return labeled, ground_truth


def _make_sq(lq):
    dr = lq.get("date_range") or {}
    return StructuredQuery(
        raw_query=lq["query"],
        topic_keywords=lq["query"].split()[:8],
        date_range_start=dr.get("from"), date_range_end=dr.get("to"),
        source_type_hint=None,
        is_temporal_comparison=(lq["query_type"] == "cross_decade_comparison"),
    )


async def run():
    labeled, gt = _load_queries("app/eval/queries.json")
    eval_q = [l for l in labeled if any(g["query_id"] == l["query_id"] for g in gt)]
    logger.info("Loaded %d eval queries", len(eval_q))

    conn = await asyncpg.connect(DB_URL, ssl=False)
    results = {}

    for config_name in ["rrf", "full_pipeline"]:
        fn = CONFIGS[config_name]
        logger.info("=== %s ===", config_name)
        config_results = []
        for i, lq in enumerate(eval_q, 1):
            logger.info("[%d/%d] %s", i, len(eval_q), lq["query"][:60])
            sq = _make_sq(lq)
            try:
                ranked = await fn(sq)
                cids = [r.chunk.id for r in ranked if r.chunk.id]
            except Exception as e:
                logger.warning("FAILED %s: %s", lq["query_id"], e)
                cids = []
            config_results.append({"query_id": lq["query_id"], "retrieved_chunk_ids": cids})

        metrics = compute_metrics(config_results, gt, k=10)
        logger.info("%s — R@10=%.4f MRR=%.4f nDCG=%.4f",
                     config_name, metrics.recall_10, metrics.mrr, metrics.ndcg_10)
        await conn.execute("""
            INSERT INTO eval_runs (config_name, recall_10, precision_10, mrr, ndcg_10,
                                   citation_correctness, query_count, run_at)
            VALUES ($1,$2,$3,$4,$5,NULL,$6,$7)
        """, config_name, metrics.recall_10, metrics.precision_10, metrics.mrr,
             metrics.ndcg_10, len(eval_q), datetime.now(timezone.utc))
        results[config_name] = {"R@10": metrics.recall_10, "MRR": metrics.mrr, "nDCG": metrics.ndcg_10}

    await conn.close()
    logger.info("=== RESULTS ===")
    for name, r in results.items():
        logger.info("  %s: R@10=%.4f MRR=%.4f nDCG=%.4f", name, r["R@10"], r["MRR"], r["nDCG"])

    # Property 17 check
    if "full_pipeline" in results and "rrf" in results:
        fp, rrf = results["full_pipeline"]["R@10"], results["rrf"]["R@10"]
        if fp > rrf:
            logger.info("PROPERTY 17 HOLDS: full_pipeline R@10 (%.4f) > rrf (%.4f)", fp, rrf)
        else:
            logger.warning("PROPERTY 17: full_pipeline R@10 (%.4f) <= rrf (%.4f)", fp, rrf)


if __name__ == "__main__":
    asyncio.run(run())
