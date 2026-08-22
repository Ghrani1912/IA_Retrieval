"""Confirm citation correctness (fixed 120s timeout) and measure query latency."""
import sys, os, io, json, asyncio, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import logging; logging.basicConfig(level=logging.INFO)

from app.eval.configs import CONFIGS
from app.eval.judge import judge_faithfulness, compute_citation_correctness
from app.models.pydantic_models import StructuredQuery
from app.synthesis.synthesizer import synthesize_answer

logger = logging.getLogger(__name__)

with open('app/eval/queries.json') as f:
    data = json.load(f)

# Pick 5 representative queries (mix of types)
TARGET_IDS = ['q001', 'q005', 'q020', 'p001', 'p006']
queries_by_id = {q['id']: q for q in data['queries']}


async def main():
    fn = CONFIGS['blended_03']

    print("=" * 80)
    print("CITATION CORRECTNESS + QUERY LATENCY")
    print("=" * 80)

    # --- Part 1: Query latency ---
    print("\n--- QUERY LATENCY (blended_03, 5 queries) ---\n")
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

        t0 = time.time()
        ranked = await fn(sq)
        t_retrieval = time.time() - t0

        t1 = time.time()
        answer = await synthesize_answer(sq.raw_query, ranked[:8])
        t_synth = time.time() - t1

        total = t_retrieval + t_synth
        latencies.append(total)

        print(f"  {qid}: retrieval={t_retrieval:.2f}s  synthesis={t_synth:.2f}s  total={total:.2f}s")
        print(f"       query: {q['query'][:70]}...")
        ans_text = ' '.join(s.text for s in (answer.answer_segments or []))[:100]
        print(f"       answer preview: {ans_text}...")
        print()

    avg_lat = sum(latencies) / len(latencies)
    print(f"  Average total latency: {avg_lat:.2f}s")
    print(f"  Min: {min(latencies):.2f}s  Max: {max(latencies):.2f}s")

    # --- Part 2: Citation correctness ---
    print(f"\n--- CITATION CORRECTNESS (5 queries, 120s timeout) ---\n")
    all_verdicts = []

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

        try:
            ranked = await fn(sq)
            answer = await synthesize_answer(sq.raw_query, ranked[:8])

            if not answer.answer_segments:
                print(f"  {qid}: No answer text generated, skipping judge")
                continue

            chunks_by_id = {r.chunk.id: r.chunk for r in ranked if r.chunk.id}
            verdicts = await judge_faithfulness(answer, chunks_by_id)
            all_verdicts.extend(verdicts)

            supported = sum(1 for v in verdicts if v.verdict == "supported")
            total_v = len(verdicts)
            print(f"  {qid}: {supported}/{total_v} claims supported ({supported/total_v*100:.0f}%)")
            for v in verdicts[:3]:
                print(f"    [{v.verdict:15s}] {v.claim_text[:80]}...")

        except Exception as exc:
            print(f"  {qid}: Judge failed — {exc}")

    if all_verdicts:
        cc = compute_citation_correctness(all_verdicts)
        total_supported = sum(1 for v in all_verdicts if v.verdict == "supported")
        print(f"\n  OVERALL: {total_supported}/{len(all_verdicts)} claims supported")
        print(f"  Citation correctness: {cc:.4f} ({cc*100:.1f}%)")
    else:
        print(f"\n  No verdicts collected — check LLM_API_KEY")

asyncio.run(main())
