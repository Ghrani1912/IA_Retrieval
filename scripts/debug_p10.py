"""Debug P@10 for blended_03."""
import sys, os, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import logging; logging.basicConfig(level=logging.WARNING)

from app.eval.metrics import precision_at_k, recall_at_k

with open('app/eval/queries.json') as f:
    data = json.load(f)

gt_map = {}
for q in data['queries']:
    if q.get('relevant_chunk_ids'):
        gt_map[q['id']] = q['relevant_chunk_ids']

# Load the blended_03 results we just saved
# Re-run only metrics computation on cached results if available
# For now, re-derive from the per-query catastrophic check we already did

# Actually, let me just compute P@10 from R@10 manually:
# If R@10 = hits / |relevant| = 0.3053
# And P@10 = hits / 10
# Then P@10 = R@10 * |relevant| / 10

# Let me check avg relevant per query
total_rel = 0
n_queries = 0
for qid, rel in gt_map.items():
    total_rel += len(rel)
    n_queries += 1

avg_rel = total_rel / n_queries
print(f"Total relevant chunks: {total_rel}")
print(f"Queries with ground truth: {n_queries}")
print(f"Average relevant per query: {avg_rel:.2f}")

# If R@10=0.3053, average hits = 0.3053 * avg_rel
avg_hits = 0.3053 * avg_rel
print(f"Average hits per query (from R@10): {avg_hits:.4f}")
print(f"Expected P@10 = hits / 10 = {avg_hits/10:.4f}")

# So P@10 should be ~0.03, not 0.2222
# The bug must be in the eval script, not the metrics code

# Let me check if the results_list format was correct
# The script passed results_list with 'retrieved_chunk_ids' key
# and ground_truth_list with 'relevant_chunk_ids' key
# That matches compute_metrics expectations

# The issue might be that blended_03 returns more than 10 results per query
# or that the retrieved_chunk_ids list is different format

# Let me check what P@10 would be if we had duplicate chunk IDs
# If a query returns [1, 1, 1, 1, 1, 1, 1, 1, 1, 1] and 1 is relevant
# Then P@10 = 10/10 = 1.0 (but _dedup would make it 1/10 = 0.1)

# Actually the _dedup function in metrics.py handles this correctly
# So the bug must be elsewhere

# Let me check: did the eval script pass the right format?
print(f"\n--- Checking eval script data format ---")
print(f"Ground truth keys: {list(gt_map.items())[:3]}")

# The issue is likely in how results_list was constructed
# Let me check if 'retrieved_chunk_ids' was used vs 'top_chunk_ids'
print(f"\nLooking at the eval script...")
print(f"The script had: results_list.append({{'query_id': q['id'], 'retrieved_chunk_ids': top_ids}})")
print(f"Compute metrics expects: 'retrieved_chunk_ids' key -- MATCHES")

# Wait -- let me check if the issue is that we passed 45 queries but
# the metrics function skips queries with empty relevant_chunk_ids
# No, we filtered to only queries with ground truth

# Let me look at the actual numbers more carefully
# R@10=0.3053, P@10=0.2222
# If P@10 = hits/10 and R@10 = hits/|relevant|
# Then hits = P@10 * 10 = 2.222
# And |relevant| = hits / R@10 = 2.222 / 0.3053 = 7.28
# But avg relevant per query is ~4.5

# So P@10=0.2222 implies 2.22 hits per query, which at avg_rel=4.5
# means R@10 = 2.22/4.5 = 0.493, not 0.3053
# These two numbers are INCONSISTENT

# Unless... the P@10 is computed on a DIFFERENT set of queries
# Or the retrieved list has different length

# AH WAIT -- let me check if the blended_03 eval script passed
# results_list correctly. The P@10 value of 0.2222 is suspicious.
# Let me recompute manually

# Actually, let me just recompute from scratch
# I'll simulate the per-query data we collected in check_all_catastrophic

# From the catastrophic check:
# p005: RRF=1, FP=5, B03=5 -> B03 has 5/10 hits -> P@10=0.5
# p010: RRF=5, FP=7, B03=7 -> B03 has 7/10 hits -> P@10=0.7

# Hmm, wait. The catastrophic queries have high recall.
# But P@10 = hits / 10, not hits / |relevant|
# So if p005 has 5 hits in top-10, P@10 = 0.5
# If p010 has 7 hits, P@10 = 0.7

# These would drag up the average significantly
# Let me check: how many queries have high recall?

# Actually, I think I found it. Let me check the recall numbers
# from the full eval. If many queries have 5+ relevant chunks in top-10,
# that would give high P@10.

# But R@10=0.3053 with avg_rel=4.5 gives avg_hits=1.37
# P@10 should be 0.137, not 0.2222

# The ONLY explanation: the P@10 was computed differently
# Let me check if there's a different compute_metrics call

# OH WAIT. I bet the issue is simpler. Let me check if the eval script
# used a different metric function or if there was a copy-paste error

print(f"\n--- Theory: P@10 in eval_blended_full.py is computed correctly ---")
print(f"--- but the print statement shows a hardcoded value ---")

# Let me check the actual eval script
with open('scripts/eval_blended_full.py') as f:
    content = f.read()

# Look for P@10 value in the print
for i, line in enumerate(content.split('\n'), 1):
    if 'P@10' in line or 'precision' in line.lower():
        print(f"  Line {i}: {line.strip()}")
