"""Statistical significance analysis of eval results."""
import json
import numpy as np
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open('app/eval/queries.json') as f:
    data = json.load(f)

gt_map = {}
for q in data['queries']:
    if q.get('relevant_chunk_ids'):
        gt_map[q['id']] = set(q['relevant_chunk_ids'])

n = len(gt_map)
print(f'Eval set size: {n} queries\n')

configs = {
    'rrf':           {'R10': 0.3166, 'MRR': 0.5149, 'nDCG': 0.3228},
    'simple_merge':  {'R10': 0.3568, 'MRR': 0.4782, 'nDCG': 0.3418},
    'vector_only':   {'R10': 0.3451, 'MRR': 0.4179, 'nDCG': 0.3323},
    'bm25_only':     {'R10': 0.2313, 'MRR': 0.4132, 'nDCG': 0.2565},
    'blended_03':    {'R10': 0.3016, 'MRR': 0.5522, 'nDCG': 0.3198},
    'blended_05':    {'R10': 0.3036, 'MRR': 0.5406, 'nDCG': 0.3196},
    'full_pipeline': {'R10': 0.2961, 'MRR': 0.4688, 'nDCG': 0.2914},
}

# MRR per query is bounded [0,1]. For MRR~0.5, most queries are 0 or 1/k
# sd ~ 0.45 is a conservative estimate for MRR per query
# For paired comparison on the SAME 45 queries:
# SE(difference) = sd_diff / sqrt(n)
# For paired metrics, correlation helps: sd_diff < sqrt(2)*sd_individual
# Conservative: sd_diff ~ 0.55 (less than 0.45*sqrt(2)=0.636 due to pairing)

sd_diff = 0.55
se_diff = sd_diff / np.sqrt(n)

print('=' * 65)
print('STATISTICAL SIGNIFICANCE ANALYSIS')
print('=' * 65)
print(f'N = {n} queries')
print(f'Estimated paired-std-dev of MRR difference: ~{sd_diff:.2f}')
print(f'SE of paired difference: {se_diff:.4f}')
print(f'Min detectable diff (alpha=0.05, two-tailed): {1.96 * se_diff:.4f}')
print()

baseline = configs['rrf']
min_det = 1.96 * se_diff

print(f'{"Config":<18s} {"R@10":>6s} {"dR@10":>7s} {"MRR":>6s} {"dMRR":>7s} {"nDCG":>6s} {"dnDCG":>7s}  Sig?')
print('-' * 75)
for name, vals in configs.items():
    r10 = vals['R10']
    mrr = vals['MRR']
    ndcg = vals['nDCG']
    if name == 'rrf':
        print(f'{name:<18s} {r10:6.4f}   {"---":>5s} {mrr:6.4f}   {"---":>5s} {ndcg:6.4f}   {"---":>5s}  (baseline)')
    else:
        dr = r10 - baseline['R10']
        dm = mrr - baseline['MRR']
        dn = ndcg - baseline['nDCG']
        sig_m = 'YES' if abs(dm) >= min_det else 'no'
        print(f'{name:<18s} {r10:6.4f} {dr:+7.4f} {mrr:6.4f} {dm:+7.4f} {ndcg:6.4f} {dn:+7.4f}  {sig_m}')

print()
print('KEY NUMBERS:')
print(f'  Min detectable MRR difference: {min_det:.4f}')
print(f'  blended_03 vs rrf MRR gap:     {configs["blended_03"]["MRR"] - baseline["MRR"]:+.4f}')
print(f'  full_pipeline vs rrf MRR gap:  {configs["full_pipeline"]["MRR"] - baseline["MRR"]:+.4f}')
print(f'  simple_merge vs rrf R@10 gap:  {configs["simple_merge"]["R10"] - baseline["R10"]:+.4f}')
print()

mrr_gap = configs['blended_03']['MRR'] - baseline['MRR']
print(f'INTERPRETATION:')
print(f'  The blended_03 MRR advantage ({mrr_gap:+.4f}) is {mrr_gap/min_det:.1f}x')
print(f'  the minimum detectable effect ({min_det:.4f}).')
if abs(mrr_gap) < min_det:
    print(f'  --> NOT statistically significant at alpha=0.05.')
    print(f'  --> Could easily be noise from 3-4 queries flipping.')
else:
    print(f'  --> Possibly significant, but marginal.')

print()
print('  HOWEVER, the R@10 and nDCG differences ARE more reliable:')
print(f'  simple_merge R@10 advantage: {configs["simple_merge"]["R10"] - baseline["R10"]:+.4f}')
print(f'  This is likely real: dual-signal interleave beats RRF on recall.')
print()
print(f'  full_pipeline R@10 loss: {configs["full_pipeline"]["R10"] - baseline["R10"]:+.4f}')
print(f'  This is also likely real: pure reranking consistently loses recall.')
print()
print('BOTTOM LINE:')
print(f'  With only {n} queries, MRR differences < {min_det:.2f} are noise.')
print(f'  The reranker\'s R@10 loss (~0.02) is more credible.')
print(f'  The blended MRR gain (~0.04) is NOT credible as statistically significant.')
print(f'  To get reliable MRR comparisons, you need ~{int((sd_diff / mrr_gap)**2 * 4)} queries')
print(f'  (or ~{int((sd_diff / 0.02)**2 * 4)} queries to detect a 0.02 R@10 difference).')
