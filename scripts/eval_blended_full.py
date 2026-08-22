"""Full 45-query eval for blended_03 with all metrics."""
import sys, os, io, json, asyncio, time, math
from datetime import datetime, timezone
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import logging; logging.basicConfig(level=logging.WARNING)

from app.eval.configs import CONFIGS
from app.eval.metrics import compute_metrics
from app.models.pydantic_models import StructuredQuery

with open('app/eval/queries.json') as f:
    data = json.load(f)

gt_map = {}
labeled_queries = []
ground_truth_list = []
results_list = []
for q in data['queries']:
    if q.get('relevant_chunk_ids'):
        gt_map[q['id']] = set(q['relevant_chunk_ids'])
        labeled_queries.append(q)
        ground_truth_list.append({'query_id': q['id'], 'relevant_chunk_ids': q['relevant_chunk_ids']})

print(f"Running blended_03 eval on {len(labeled_queries)} queries...")

async def main():
    config_fn = CONFIGS['blended_03']
    all_results = {}
    t0 = time.time()

    for i, q in enumerate(labeled_queries, 1):
        dr = q.get('date_range') or {}
        sq = StructuredQuery(
            raw_query=q['query'],
            topic_keywords=q['query'].split()[:8],
            date_range_start=dr.get('from'),
            date_range_end=dr.get('to'),
            source_type_hint=None,
            is_temporal_comparison=(q['query_type'] == 'cross_decade_comparison'),
        )
        ranked = await config_fn(sq)
        top_ids = [r.chunk.id for r in ranked[:10]]
        all_results[q['id']] = {
            'query': q['query'],
            'query_type': q['query_type'],
            'top_chunk_ids': top_ids,
            'relevant_chunk_ids': list(gt_map[q['id']]),
        }
        results_list.append({'query_id': q['id'], 'retrieved_chunk_ids': top_ids})
        elapsed = time.time() - t0
        sys.stdout.write(f'\r  [{i}/{len(labeled_queries)}] {q["id"]}  ({elapsed:.0f}s)')
        sys.stdout.flush()

    total_time = time.time() - t0
    print(f'\n\nDone in {total_time:.1f}s')

    # Compute metrics
    metrics = compute_metrics(results_list, ground_truth_list)

    print(f"\n{'='*60}")
    print(f"BLENDED_03 (alpha=0.3) — FULL EVAL RESULTS")
    print(f"{'='*60}")
    print(f"  Queries:    {len(labeled_queries)}")
    print(f"  Recall@10:  {metrics.recall_10:.4f}")
    print(f"  Precision@10: {metrics.precision_10:.4f}")
    print(f"  MRR:        {metrics.mrr:.4f}")
    print(f"  nDCG@10:    {metrics.ndcg_10:.4f}")
    print(f"  Time:       {total_time:.1f}s")

    # Compare to known baselines
    baselines = {
        'rrf':           {'R@10': 0.3166, 'P@10': 0.0317, 'MRR': 0.5149, 'nDCG': 0.3228},
        'simple_merge':  {'R@10': 0.3568, 'P@10': 0.0357, 'MRR': 0.4782, 'nDCG': 0.3418},
        'full_pipeline': {'R@10': 0.2961, 'P@10': 0.0296, 'MRR': 0.4688, 'nDCG': 0.2914},
    }

    print(f"\n{'='*60}")
    print(f"COMPARISON")
    print(f"{'='*60}")
    print(f"{'Config':<18s} {'R@10':>7s} {'P@10':>7s} {'MRR':>7s} {'nDCG':>7s}")
    print('-' * 50)
    print(f"{'rrf':<18s} {baselines['rrf']['R@10']:7.4f} {baselines['rrf']['P@10']:7.4f} {baselines['rrf']['MRR']:7.4f} {baselines['rrf']['nDCG']:7.4f}")
    print(f"{'blended_03':<18s} {metrics.recall_10:7.4f} {metrics.precision_10:7.4f} {metrics.mrr:7.4f} {metrics.ndcg_10:7.4f}  <--")
    print(f"{'simple_merge':<18s} {baselines['simple_merge']['R@10']:7.4f} {baselines['simple_merge']['P@10']:7.4f} {baselines['simple_merge']['MRR']:7.4f} {baselines['simple_merge']['nDCG']:7.4f}")
    print(f"{'full_pipeline':<18s} {baselines['full_pipeline']['R@10']:7.4f} {baselines['full_pipeline']['P@10']:7.4f} {baselines['full_pipeline']['MRR']:7.4f} {baselines['full_pipeline']['nDCG']:7.4f}")

    # Save eval run
    import asyncpg
    async def save_eval_run():
        try:
            conn = await asyncpg.connect(os.environ.get('DATABASE_URL', 'postgresql://ia_user:ia_pass@localhost:5432/ia_db'))
            await conn.execute("""
                INSERT INTO eval_runs (config_name, eval_timestamp, total_queries, queries_with_ground_truth,
                    recall_at_10, mrr, ndcg_at_10, precision_at_10, recall_at_5, recall_at_20,
                    mean_ap, citation_correctness, reranker_used, embedding_model, reranker_model,
                    chunk_count, source_count, corpus_version, notes)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            """,
                'blended_03',
                datetime.now(timezone.utc),
                50, 45,
                metrics.recall_10,
                metrics.mrr,
                metrics.ndcg_10,
                metrics.precision_10,
                0,  # recall_at_5
                0,  # recall_at_20
                0,  # map
                None,  # citation_correctness
                True,
                'BAAI/bge-m3',
                'BAAI/bge-reranker-v2-m3',
                6588, 44,
                'dtic+eric+v2',
                'alpha=0.3 blend of RRF fusion + cross-encoder reranker scores'
            )
            await conn.close()
            print("\n  Saved to eval_runs table.")
        except Exception as e:
            print(f"\n  Could not save to eval_runs: {e}")

    await save_eval_run()

asyncio.run(main())
