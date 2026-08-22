"""Check if blended_03 rescues q020 and p001 vs rrf baseline."""
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

    # Run all three configs
    rrf_ranked = await CONFIGS['rrf'](sq)
    fp_ranked = await CONFIGS['full_pipeline'](sq)
    b03_ranked = await CONFIGS['blended_03'](sq)

    # Save RRF scores before they get overwritten
    rrf_scores = {r.chunk.id: r.score for r in rrf_ranked}
    fp_scores = {r.chunk.id: r.score for r in fp_ranked}
    b03_scores = {r.chunk.id: r.score for r in b03_ranked}

    def src(r):
        return str(r.chunk.source_id) if hasattr(r.chunk, 'source_id') else '?'

    rrf_top10_ids = [r.chunk.id for r in rrf_ranked[:10]]
    fp_top10_ids = [r.chunk.id for r in fp_ranked[:10]]
    b03_top10_ids = [r.chunk.id for r in b03_ranked[:10]]

    rrf_set = set(rrf_top10_ids)
    fp_set = set(fp_top10_ids)
    b03_set = set(b03_top10_ids)

    def recall(top_ids):
        return sum(1 for cid in top_ids if cid in relevant)

    print(f"\n{'='*100}")
    print(f"QUERY {qid}: {q['query']}")
    print(f"{'='*100}")

    print(f"\n  RRF recall@10:          {recall(rrf_top10_ids)}/10")
    print(f"  full_pipeline recall@10: {recall(fp_top10_ids)}/10  (delta: {recall(fp_top10_ids) - recall(rrf_top10_ids):+d})")
    print(f"  blended_03 recall@10:    {recall(b03_top10_ids)}/10  (delta: {recall(b03_top10_ids) - recall(rrf_top10_ids):+d})")

    # Show the side-by-side for top-10
    all_chunks_in_play = set(rrf_top10_ids) | set(fp_top10_ids) | set(b03_top10_ids)

    def label(cid):
        if cid in rrf_set and cid in fp_set and cid in b03_set:
            return "ALL"
        if cid in rrf_set and cid not in fp_set and cid not in b03_set:
            return "rrf only"
        if cid not in rrf_set and cid in fp_set and cid not in b03_set:
            return "fp only"
        if cid not in rrf_set and cid not in fp_set and cid in b03_set:
            return "b03 only"
        if cid in rrf_set and cid not in fp_set and cid in b03_set:
            return "rrf+b03"
        if cid not in rrf_set and cid in fp_set and cid in b03_set:
            return "fp+b03"
        return "?"

    # Build comparison table
    print(f"\n  {'ID':>6s}  {'Rel':>3s}  {'In RRF':>7s}  {'In FP':>5s}  {'In B03':>6s}  {'Status':>10s}  {'Src':>8s}  Text preview")
    print(f"  {'-'*96}")

    for cid in sorted(all_chunks_in_play):
        r = rrf_scores.get(cid, 0)
        f = fp_scores.get(cid, 0)
        b = b03_scores.get(cid, 0)
        rel = "***" if cid in relevant else "   "
        lbl = label(cid)

        # Get source from any ranked version that has it
        rrf_r = next((x for x in rrf_ranked if x.chunk.id == cid), None)
        fp_r = next((x for x in fp_ranked if x.chunk.id == cid), None)
        b03_r = next((x for x in b03_ranked if x.chunk.id == cid), None)
        ref = rrf_r or fp_r or b03_r
        s = src(ref) if ref else '?'
        text = ref.chunk.text[:100].replace('\n', ' ') if ref else '?'

        # Show which rank it appeared in for each config
        rrf_pos = rrf_top10_ids.index(cid) + 1 if cid in rrf_top10_ids else '-'
        fp_pos = fp_top10_ids.index(cid) + 1 if cid in fp_top10_ids else '-'
        b03_pos = b03_top10_ids.index(cid) + 1 if cid in b03_top10_ids else '-'

        print(f"  {str(cid):>6s}  {rel}  R:{str(rrf_pos):>4s}   F:{str(fp_pos):>4s}   B:{str(b03_pos):>4s}  {lbl:>10s}  [{s:>8s}]  {text}...")

    # Key question: did blended_03 keep the source 722 (q020) or source 165 (p001) chunks?
    print(f"\n  --- KEY QUESTION: Did blended_03 keep the correct source doc chunks? ---")
    if qid == 'q020':
        target_src = '722'  # the dialogue systems paper
        print(f"  Looking for source {target_src} (dialogue systems paper) chunks:")
        src722_in_rrf = [cid for cid in rrf_top10_ids if src(next((x for x in rrf_ranked if x.chunk.id == cid), None)) == target_src]
        src722_in_fp = [cid for cid in fp_top10_ids if src(next((x for x in fp_ranked if x.chunk.id == cid), None)) == target_src]
        src722_in_b03 = [cid for cid in b03_top10_ids if src(next((x for x in b03_ranked if x.chunk.id == cid), None)) == target_src]
        print(f"    RRF:          {src722_in_rrf} ({len(src722_in_rrf)} chunks)")
        print(f"    full_pipeline: {src722_in_fp} ({len(src722_in_fp)} chunks)")
        print(f"    blended_03:   {src722_in_b03} ({len(src722_in_b03)} chunks)")
        if src722_in_rrf and not src722_in_b03:
            print(f"    VERDICT: blended_03 STILL lost all source {target_src} chunks. Blending did NOT rescue this query.")
        elif src722_in_b03:
            print(f"    VERDICT: blended_03 KEPT some source {target_src} chunks! Blending rescued this query.")
    elif qid == 'p001':
        for target_src in ['165', '4739']:
            print(f"  Looking for source {target_src} chunks:")
            src_in_rrf = [cid for cid in rrf_top10_ids if src(next((x for x in rrf_ranked if x.chunk.id == cid), None)) == target_src]
            src_in_fp = [cid for cid in fp_top10_ids if src(next((x for x in fp_ranked if x.chunk.id == cid), None)) == target_src]
            src_in_b03 = [cid for cid in b03_top10_ids if src(next((x for x in b03_ranked if x.chunk.id == cid), None)) == target_src]
            print(f"    RRF:          {src_in_rrf} ({len(src_in_rrf)} chunks)")
            print(f"    full_pipeline: {src_in_fp} ({len(src_in_fp)} chunks)")
            print(f"    blended_03:   {src_in_b03} ({len(src_in_b03)} chunks)")

        # Check relevant chunks specifically
        rrf_rel = [cid for cid in rrf_top10_ids if cid in relevant]
        fp_rel = [cid for cid in fp_top10_ids if cid in relevant]
        b03_rel = [cid for cid in b03_top10_ids if cid in relevant]
        print(f"\n  Relevant chunks in each top-10:")
        print(f"    RRF:          {rrf_rel} ({len(rrf_rel)}/9)")
        print(f"    full_pipeline: {fp_rel} ({len(fp_rel)}/9)")
        print(f"    blended_03:   {b03_rel} ({len(b03_rel)}/9)")
        if len(b03_rel) <= len(fp_rel):
            print(f"    VERDICT: blended_03 did NOT rescue this query over full_pipeline.")
        else:
            print(f"    VERDICT: blended_03 improved over full_pipeline on this query.")

    print()

async def main():
    for qid in TARGETS:
        await compare(qid)

asyncio.run(main())
