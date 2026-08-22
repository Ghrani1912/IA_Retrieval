"""Root-cause q020 and p001: RRF vs reranked top-10, same-doc cannibalization check."""
import sys, os, io, json, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import logging; logging.basicConfig(level=logging.WARNING)

from app.eval.configs import CONFIGS
from app.models.pydantic_models import StructuredQuery

TARGETS = ['q020', 'p001']

with open('app/eval/queries.json') as f:
    data = json.load(f)

queries_by_id = {q['id']: q for q in data['queries']}


async def analyze(qid):
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

    # Step 1: get RRF-only results (save scores before reranking)
    rrf_fn = CONFIGS['rrf']
    rrf_ranked = await rrf_fn(sq)

    # Save RRF scores before reranker overwrites .score
    rrf_scores_before = {}
    for r in rrf_ranked:
        rrf_scores_before[r.chunk.id] = r.score

    # Step 2: get full_pipeline results (reranker overwrites .score)
    fp_fn = CONFIGS['full_pipeline']
    fp_ranked = await fp_fn(sq)

    # Build lookup maps
    rrf_top10 = [r for r in rrf_ranked[:10]]
    fp_top10 = [r for r in fp_ranked[:10]]

    rrf_top10_ids = [r.chunk.id for r in rrf_top10]
    fp_top10_ids = [r.chunk.id for r in fp_top10]

    rrf_set = set(rrf_top10_ids)
    fp_set = set(fp_top10_ids)

    lost = rrf_set - fp_set  # demoted out of top-10
    gained = fp_set - rrf_set  # promoted into top-10
    kept = rrf_set & fp_set

    rrf_map = {r.chunk.id: r for r in rrf_ranked[:30]}
    fp_map = {r.chunk.id: r for r in fp_ranked[:30]}

    print(f"\n{'='*110}")
    print(f"QUERY {qid}: {q['query']}")
    print(f"Type: {q['query_type']}  |  Relevant chunks: {len(relevant)}")
    rrf_r = sum(1 for r in rrf_top10 if r.chunk.id in relevant)
    fp_r = sum(1 for r in fp_top10 if r.chunk.id in relevant)
    print(f"RRF recall@10: {rrf_r}/10  |  FP recall@10: {fp_r}/10  |  Delta: {fp_r - rrf_r:+d}")
    print(f"{'='*110}")

    def chunk_text_short(r, n=120):
        return r.chunk.text[:n].replace('\n', ' ').replace('\r', '')

    def src(r):
        v = r.chunk.source_id if hasattr(r.chunk, 'source_id') else '?'
        return str(v)

    print(f"\n--- RRF TOP-10 (before reranking) ---")
    print(f"{'#':>3s}  {'ID':>6s}  {'RRF_sc':>7s}  {'Rel':>3s}  Source  Text preview")
    print("-" * 110)
    for i, r in enumerate(rrf_top10, 1):
        rid = r.chunk.id
        rel = "***" if rid in relevant else "   "
        s = src(r)
        print(f"{i:3d}  {str(rid):>6s}  {rrf_scores_before[rid]:7.4f}  {rel}  [{s:>8s}]  {chunk_text_short(r)}...")

    print(f"\n--- FULL_PIPELINE TOP-10 (after reranking) ---")
    print(f"{'#':>3s}  {'ID':>6s}  {'FP_sc':>7s}  {'RRF_sc':>7s}  {'Rel':>3s}  Source  Text preview")
    print("-" * 110)
    for i, r in enumerate(fp_top10, 1):
        rid = r.chunk.id
        rel = "***" if rid in relevant else "   "
        s = src(r)
        rrf_sc = rrf_scores_before.get(rid, 0.0)
        print(f"{i:3d}  {str(rid):>6s}  {r.score:7.4f}  {rrf_sc:7.4f}  {rel}  [{s:>8s}]  {chunk_text_short(r)}...")

    # CANNIBALIZATION ANALYSIS
    print(f"\n--- CANNIBALIZATION ANALYSIS ---")
    print(f"Lost from top-10:  {sorted(lost)}")
    print(f"Gained into top-10: {sorted(gained)}")
    print(f"Kept in both:       {sorted(kept)}")

    # Source doc analysis
    lost_by_src = {}
    gained_by_src = {}
    kept_by_src = {}
    for lid in lost:
        s = src(rrf_map[lid])
        lost_by_src.setdefault(s, []).append(lid)
    for gid in gained:
        s = src(fp_map[gid])
        gained_by_src.setdefault(s, []).append(gid)
    for kid in kept:
        s = src(rrf_map[kid])
        kept_by_src.setdefault(s, []).append(kid)

    print(f"\nLost chunks by source:")
    for s, ids in sorted(lost_by_src.items()):
        rel_n = sum(1 for i in ids if i in relevant)
        print(f"  {s}: {len(ids)} chunks ({rel_n} relevant) -> {ids}")

    print(f"\nGained chunks by source:")
    for s, ids in sorted(gained_by_src.items()):
        rel_n = sum(1 for i in ids if i in relevant)
        print(f"  {s}: {len(ids)} chunks ({rel_n} relevant) -> {ids}")

    overlap = set(lost_by_src.keys()) & set(gained_by_src.keys())
    if overlap:
        print(f"\n** SAME-DOCUMENT CANNIBALIZATION DETECTED **")
        print(f"   Sources where reranker replaced a chunk with another from the same doc: {overlap}")
        for s in overlap:
            print(f"   [{s}]: lost {lost_by_src[s]}, gained {gained_by_src[s]}")
    else:
        print(f"\n** CROSS-DOCUMENT TOPIC-HOPPING **")
        print(f"   Lost chunks from: {set(lost_by_src.keys())}")
        print(f"   Gained chunks from: {set(gained_by_src.keys())}")
        print(f"   The reranker is pulling in content from DIFFERENT documents, not cannibalizing within the same doc.")

    # Show full text of lost relevant chunks and gained irrelevant chunks
    print(f"\n--- DETAILED: LOST RELEVANT CHUNKS ---")
    for lid in lost:
        if lid in relevant:
            r = rrf_map[lid]
            print(f"\n  Chunk {lid} [src={src(r)}] (RRF score: {rrf_scores_before[lid]:.4f})")
            print(f"  Text: {r.chunk.text[:500].replace(chr(10), ' ')}")

    print(f"\n--- DETAILED: GAINED IRRELEVANT CHUNKS ---")
    for gid in gained:
        if gid not in relevant:
            r = fp_map[gid]
            print(f"\n  Chunk {gid} [src={src(r)}] (FP score: {r.score:.4f}, was RRF: {rrf_scores_before.get(gid, 0):.4f})")
            print(f"  Text: {r.chunk.text[:500].replace(chr(10), ' ')}")

    print(f"\n--- DETAILED: GAINED RELEVANT CHUNKS ---")
    for gid in gained:
        if gid in relevant:
            r = fp_map[gid]
            print(f"\n  Chunk {gid} [src={src(r)}] (FP score: {r.score:.4f}) -- GOOD PROMOTION")

    print(f"\n{'='*110}\n")


async def main():
    for qid in TARGETS:
        if qid not in queries_by_id:
            print(f"Query {qid} not found!")
            continue
        await analyze(qid)

asyncio.run(main())
