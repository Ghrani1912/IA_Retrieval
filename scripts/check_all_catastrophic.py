"""Check if blended_03 rescues all 5 catastrophic queries (delta <= -2)."""
import sys, os, io, json, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import logging; logging.basicConfig(level=logging.WARNING)

from app.eval.configs import CONFIGS
from app.models.pydantic_models import StructuredQuery

TARGETS = ['q020', 'p001', 'p004', 'p006', 'p007']

with open('app/eval/queries.json') as f:
    data = json.load(f)
queries_by_id = {q['id']: q for q in data['queries']}


async def compare(qid):
    q = queries_by_id[qid]
    relevant = set(q.get('relevant_chunk_ids', []))
    dr = q.get('date_range') or {}
    sq = StructuredQuery(
        raw_query=q['query'],
        topic_keywords=q['query'].split()[:8],
        date_range_start=dr.get('from'), date_range_end=dr.get('to'),
        source_type_hint=None,
        is_temporal_comparison=(q['query_type'] == 'cross_decade_comparison'),
    )

    rrf_ranked = await CONFIGS['rrf'](sq)
    fp_ranked = await CONFIGS['full_pipeline'](sq)
    b03_ranked = await CONFIGS['blended_03'](sq)

    rrf_scores = {r.chunk.id: r.score for r in rrf_ranked}

    def src(r):
        return str(r.chunk.source_id) if hasattr(r.chunk, 'source_id') else '?'

    def recall(top):
        return sum(1 for r in top[:10] if r.chunk.id in relevant)

    rrf_r = recall(rrf_ranked)
    fp_r = recall(fp_ranked)
    b03_r = recall(b03_ranked)

    fp_delta = fp_r - rrf_r
    b03_delta = b03_r - rrf_r

    # What RRF had vs what each config kept/lost
    rrf_rel_ids = [r.chunk.id for r in rrf_ranked[:10] if r.chunk.id in relevant]
    fp_rel_ids = [r.chunk.id for r in fp_ranked[:10] if r.chunk.id in relevant]
    b03_rel_ids = [r.chunk.id for r in b03_ranked[:10] if r.chunk.id in relevant]

    rrf_lost_fp = set(rrf_rel_ids) - set(fp_rel_ids)
    rrf_lost_b03 = set(rrf_rel_ids) - set(b03_rel_ids)
    rrf_kept_fp = set(rrf_rel_ids) & set(fp_rel_ids)
    rrf_kept_b03 = set(rrf_rel_ids) & set(b03_rel_ids)

    def chunk_src_map(top10):
        m = {}
        for r in top10[:10]:
            m[r.chunk.id] = src(r)
        return m

    rrf_src = chunk_src_map(rrf_ranked)
    fp_src = chunk_src_map(fp_ranked)
    b03_src = chunk_src_map(b03_ranked)

    print(f"\n{'='*90}")
    print(f"QUERY {qid}: {q['query']}")
    print(f"Type: {q['query_type']}")
    print(f"{'='*90}")
    print(f"  RRF:           {rrf_r}/10 relevant  (baseline)")
    print(f"  full_pipeline: {fp_r}/10 relevant  (delta: {fp_delta:+d})")
    print(f"  blended_03:    {b03_r}/10 relevant  (delta: {b03_delta:+d})")

    if b03_delta >= fp_delta:
        print(f"\n  >>> blended_03 RESCUED or MATCHED full_pipeline ({b03_delta:+d} vs {fp_delta:+d})")
    else:
        print(f"\n  >>> blended_03 made it WORSE ({b03_delta:+d} vs {fp_delta:+d})")

    if rrf_lost_b03:
        print(f"\n  Blended_03 still lost these relevant chunks that RRF had:")
        for cid in sorted(rrf_lost_b03):
            r = next((x for x in rrf_ranked if x.chunk.id == cid), None)
            text = r.chunk.text[:100].replace('\n', ' ') if r else '?'
            print(f"    Chunk {cid} [src={rrf_src.get(cid, '?')}] RRF_score={rrf_scores.get(cid, 0):.4f}: {text}...")
    else:
        print(f"\n  Blended_03 kept ALL relevant chunks that RRF had!")

    if rrf_lost_fp and not rrf_lost_b03:
        print(f"  These were lost by full_pipeline but SAVED by blending.")

    # Show unique losses/gains
    only_lost_fp = set(fp_rel_ids) - set(b03_rel_ids)
    only_gained_b03 = set(b03_rel_ids) - set(fp_rel_ids)
    if only_lost_fp:
        print(f"\n  full_pipeline had but blended_03 dropped: {sorted(only_lost_fp)}")
    if only_gained_b03:
        print(f"\n  blended_03 gained but full_pipeline didn't have: {sorted(only_gained_b03)}")

    return {'qid': qid, 'rrf': rrf_r, 'fp': fp_r, 'b03': b03_r, 'fp_d': fp_delta, 'b03_d': b03_delta}


async def main():
    results = []
    for qid in TARGETS:
        r = await compare(qid)
        results.append(r)

    print(f"\n\n{'='*90}")
    print(f"SUMMARY ACROSS ALL 5 CATASTROPHIC QUERIES")
    print(f"{'='*90}")
    print(f"{'Query':>8s}  {'RRF':>3s}  {'FP':>3s}  {'B03':>3s}  {'FP_d':>5s}  {'B03_d':>5s}  Rescued?")
    print('-' * 55)
    total_rrf = total_fp = total_b03 = 0
    for r in results:
        rescued = 'YES' if r['b03_d'] > r['fp_d'] else ('TIED' if r['b03_d'] == r['fp_d'] else 'NO')
        print(f"{r['qid']:>8s}  {r['rrf']:3d}  {r['fp']:3d}  {r['b03']:3d}  {r['fp_d']:+5d}  {r['b03_d']:+5d}  {rescued}")
        total_rrf += r['rrf']
        total_fp += r['fp']
        total_b03 += r['b03']

    print('-' * 55)
    print(f"{'TOTAL':>8s}  {total_rrf:3d}  {total_fp:3d}  {total_b03:3d}")
    print(f"\nRRF total relevant in top-10 across 5 catastrophic queries: {total_rrf}")
    print(f"full_pipeline total:                                        {total_fp} (lost {total_rrf - total_fp})")
    print(f"blended_03 total:                                           {total_b03} (lost {total_rrf - total_b03})")
    print(f"\nBlending recovered {total_b03 - total_fp} of {total_rrf - total_fp} lost relevant chunks.")

asyncio.run(main())
