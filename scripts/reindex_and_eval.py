"""Re-index OpenSearch from Postgres, then run full eval with GPU reranker."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
from datetime import datetime, timezone

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from app.config import settings
from app.ingestion.opensearch_client import get_client, ensure_index, INDEX_NAME

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


# ─────────────────────────────────────────────────────────────────────
# Step 1: Re-index OpenSearch
# ─────────────────────────────────────────────────────────────────────

async def reindex_opensearch():
    """Pull all chunks+sources from Postgres, bulk-index into OpenSearch."""
    logger.info("=== STEP 1: Re-indexing OpenSearch ===")
    conn = await asyncpg.connect(DB_URL, ssl=False)
    client = get_client()
    ensure_index(client)

    # Count existing docs
    try:
        existing = client.count(index=INDEX_NAME)["count"]
        logger.info("Existing docs in OpenSearch: %d", existing)
    except Exception:
        existing = 0

    if existing >= 6000:
        logger.info("OpenSearch already has %d docs — skipping re-index", existing)
        await conn.close()
        return

    # Pull all chunks with source metadata
    rows = await conn.fetch("""
        SELECT c.id, c.source_id, c.text, c.page_or_section, c.capture_timestamp,
               c.char_range_start, c.char_range_end, c.token_count,
               s.ia_identifier, s.source_type, s.pub_date_raw, s.collection, s.language
        FROM chunks c
        JOIN sources s ON s.id = c.source_id
        ORDER BY c.id
    """)
    logger.info("Pulled %d chunks from Postgres", len(rows))

    # Build bulk actions
    from opensearchpy.helpers import bulk

    def _date_iso(raw):
        if not raw:
            return None
        raw = raw.strip()
        if "T" in raw:
            return raw.split("T")[0]
        return raw if len(raw) >= 4 else None

    actions = []
    for r in rows:
        actions.append({
            "_index": INDEX_NAME,
            "_id": str(r["id"]),
            "chunk_id": r["id"],
            "source_id": r["source_id"],
            "ia_identifier": r["ia_identifier"],
            "text": r["text"],
            "date": _date_iso(r["pub_date_raw"]),
            "source_type": r["source_type"],
            "collection": r["collection"],
            "language": r["language"],
            "page_or_section": r["page_or_section"],
            "capture_timestamp": r["capture_timestamp"].isoformat() if r["capture_timestamp"] else None,
        })

    # Bulk index in batches of 500
    t0 = time.time()
    for i in range(0, len(actions), 500):
        batch = actions[i:i+500]
        success, errors = bulk(client, batch, refresh=True, raise_on_error=False)
        if errors:
            logger.error("Batch %d-%d had errors: %s", i, i+len(batch), errors[:2])
        logger.info("  Indexed %d-%d/%d", i, min(i+500, len(actions)), len(actions))

    elapsed = time.time() - t0
    final_count = client.count(index=INDEX_NAME)["count"]
    logger.info("Re-index complete: %d docs in %.1fs", final_count, elapsed)
    await conn.close()


# ─────────────────────────────────────────────────────────────────────
# Step 2: Run eval
# ─────────────────────────────────────────────────────────────────────

async def run_eval():
    """Run rrf + full_pipeline eval with GPU reranker."""
    logger.info("=== STEP 2: Running eval ===")

    import json
    from app.eval.configs import CONFIGS
    from app.eval.metrics import compute_metrics
    from app.models.pydantic_models import StructuredQuery

    with open("app/eval/queries.json") as f:
        data = json.load(f)

    labeled, gt = [], []
    for q in data["queries"]:
        labeled.append({
            "query_id": q["id"], "query": q["query"],
            "query_type": q["query_type"], "date_range": q.get("date_range"),
        })
        if q.get("relevant_chunk_ids"):
            gt.append({"query_id": q["id"], "relevant_chunk_ids": q["relevant_chunk_ids"]})

    eval_q = [l for l in labeled if any(g["query_id"] == l["query_id"] for g in gt)]
    logger.info("Eval queries: %d (from %d total, %d skipped)", len(eval_q), len(labeled), len(labeled)-len(eval_q))

    conn = await asyncpg.connect(DB_URL, ssl=False)
    results = {}

    for config_name in ["rrf", "full_pipeline"]:
        fn = CONFIGS[config_name]
        logger.info("--- %s ---", config_name)
        t0 = time.time()
        config_results = []

        for i, lq in enumerate(eval_q, 1):
            dr = lq.get("date_range") or {}
            sq = StructuredQuery(
                raw_query=lq["query"],
                topic_keywords=lq["query"].split()[:8],
                date_range_start=dr.get("from"), date_range_end=dr.get("to"),
                source_type_hint=None,
                is_temporal_comparison=(lq["query_type"] == "cross_decade_comparison"),
            )
            try:
                ranked = await fn(sq)
                cids = [r.chunk.id for r in ranked if r.chunk.id]
            except Exception as e:
                logger.warning("  [%d/%d] FAILED %s: %s", i, len(eval_q), lq["query_id"], e)
                cids = []
            config_results.append({"query_id": lq["query_id"], "retrieved_chunk_ids": cids})

            if i % 10 == 0:
                logger.info("  [%d/%d] done", i, len(eval_q))

        elapsed = time.time() - t0
        metrics = compute_metrics(config_results, gt, k=10)
        logger.info("%s — R@10=%.4f MRR=%.4f nDCG=%.4f (%.1fs)", config_name, metrics.recall_10, metrics.mrr, metrics.ndcg_10, elapsed)

        await conn.execute("""
            INSERT INTO eval_runs (config_name, recall_10, precision_10, mrr, ndcg_10,
                                   citation_correctness, query_count, run_at)
            VALUES ($1,$2,$3,$4,$5,NULL,$6,$7)
        """, config_name, metrics.recall_10, metrics.precision_10, metrics.mrr,
             metrics.ndcg_10, len(eval_q), datetime.now(timezone.utc))

        results[config_name] = {"R@10": metrics.recall_10, "MRR": metrics.mrr, "nDCG": metrics.ndcg_10}

    await conn.close()

    # Summary
    logger.info("=== RESULTS ===")
    for name, r in results.items():
        logger.info("  %s: R@10=%.4f MRR=%.4f nDCG=%.4f", name, r["R@10"], r["MRR"], r["nDCG"])

    if "full_pipeline" in results and "rrf" in results:
        fp, rrf = results["full_pipeline"]["R@10"], results["rrf"]["R@10"]
        if fp > rrf:
            logger.info("PROPERTY 17 HOLDS: full_pipeline R@10 (%.4f) > rrf (%.4f)", fp, rrf)
        else:
            logger.warning("PROPERTY 17: full_pipeline R@10 (%.4f) <= rrf (%.4f)", fp, rrf)


if __name__ == "__main__":
    asyncio.run(reindex_opensearch())
    asyncio.run(run_eval())
