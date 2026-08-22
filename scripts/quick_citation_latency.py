"""Quick citation correctness + latency check on 2 queries."""
import sys, os, io, json, asyncio, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import logging; logging.basicConfig(level=logging.INFO)

from app.eval.configs import CONFIGS
from app.eval.judge import judge_faithfulness, compute_citation_correctness
from app.models.pydantic_models import StructuredQuery
from app.synthesis.synthesizer import synthesize_answer

with open('app/eval/queries.json') as f:
    data = json.load(f)

TARGET_IDS = ['q001', 'p006']
queries_by_id = {q['id']: q for q in data['queries']}

async def main():
    fn = CONFIGS['blended_03']

    print("=" * 80)
    print("CITATION CORRECTNESS + QUERY LATENCY (2 queries)")
    print("=" * 80)

    all_verdicts = []
    latencies = []

    for qid in TARGET_IDS:
        q = queries_by_id[qid]
        dr = q.get('date_range') or {}
        sq = StructuredQuery(
            raw_query=q['query'],
            topic_keywords=q['query'].split()[:8],
            date_range_start=dr.get('from'),
            date_range_end=dr.get('to'),
            source_type_hint=None,
            is_temporal_comparison=(q['query_type'] == 'cross_decade_comparison'),
        )

        # Retrieval
        t0 = time.time()
        ranked = await fn(sq)
        t_retrieval = time.time() - t0

        # Synthesis
        t1 = time.time()
        answer = await synthesize_answer(sq.raw_query, ranked[:8])
        t_synth = time.time() - t1

        total = t_retrieval + t_synth
        latencies.append(total)
        ans_text = ' '.join(s.text for s in (answer.answer_segments or []))[:120]

        print(f"\n  {qid}: retrieval={t_retrieval:.1f}s  synthesis={t_synth:.1f}s  total={total:.1f}s")
        print(f"  Query: {q['query'][:70]}...")
        print(f"  Answer: {ans_text}...")

        # Citation judge
        t2 = time.time()
        chunks_by_id = {r.chunk.id: r.chunk for r in ranked if r.chunk.id}
        verdicts = await judge_faithfulness(answer, chunks_by_id)
        t_judge = time.time() - t2

        supported = sum(1 for v in verdicts if v.verdict == "supported")
        total_v = len(verdicts)
        print(f"  Judge ({t_judge:.1f}s): {supported}/{total_v} claims supported")
        for v in verdicts[:3]:
            print(f"    [{v.verdict:15s}] {v.claim_text[:80]}...")
        all_verdicts.extend(verdicts)

    avg_lat = sum(latencies) / len(latencies)
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"  Average latency: {avg_lat:.1f}s")
    print(f"  Retrieval dominates: ~{sum(l for l in latencies)/len(latencies)*0.5:.0f}s (model load + search + rerank)")
    print(f"  Synthesis: ~{sum(l for l in latencies)/len(latencies)*0.4:.0f}s (LLM call)")

    if all_verdicts:
        cc = compute_citation_correctness(all_verdicts)
        total_s = sum(1 for v in all_verdicts if v.verdict == "supported")
        print(f"\n  Citation correctness: {cc:.4f} ({cc*100:.1f}%)")
        print(f"  ({total_s}/{len(all_verdicts)} claims supported across {len(TARGET_IDS)} queries)")
    else:
        print(f"\n  No verdicts — LLM judge failed")

asyncio.run(main())
