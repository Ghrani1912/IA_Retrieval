"""Retrieval evaluation metrics — pure functions.

Implements Recall@K, Precision@K, MRR, and nDCG@K exactly as specified
in design.md section 9.4.  All functions are deterministic and side-effect
free — suitable for unit testing and PBT.

Formulas:
  recall_k    = |relevant ∩ retrieved[:K]| / |relevant|
  precision_k = |relevant ∩ retrieved[:K]| / K
  mrr         = 1 / rank_of_first_relevant   (0 if none in top-K)
  dcg_k       = Σ rel_i / log2(i + 1)  for i in 1..K  (rel_i ∈ {0, 1})
  ndcg_k      = dcg_k / ideal_dcg_k
"""
from __future__ import annotations

import math
from typing import Sequence

from app.models.pydantic_models import RetrievalMetrics


def _dedup(retrieved: Sequence[int]) -> list[int]:
    """Deduplicate retrieved list preserving rank order."""
    seen: set[int] = set()
    result = []
    for cid in retrieved:
        if cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result


def recall_at_k(
    retrieved: Sequence[int],
    relevant: Sequence[int],
    k: int = 10,
) -> float:
    """Fraction of relevant chunks that appear in the top-K retrieved.

    Returns 0.0 if relevant is empty (undefined recall → safe default).
    Deduplicates retrieved to avoid inflated counts from duplicate IDs.
    """
    if not relevant:
        return 0.0
    rel_set = set(relevant)
    hits = sum(1 for cid in _dedup(retrieved)[:k] if cid in rel_set)
    return hits / len(rel_set)


def precision_at_k(
    retrieved: Sequence[int],
    relevant: Sequence[int],
    k: int = 10,
) -> float:
    """Fraction of top-K retrieved chunks that are relevant."""
    if k == 0:
        return 0.0
    rel_set = set(relevant)
    hits = sum(1 for cid in _dedup(retrieved)[:k] if cid in rel_set)
    return hits / k


def mean_reciprocal_rank(
    retrieved: Sequence[int],
    relevant: Sequence[int],
    k: int = 10,
) -> float:
    """Reciprocal rank of the first relevant result in top-K.

    Returns 0.0 if no relevant result appears in the first K positions.
    """
    rel_set = set(relevant)
    for rank, cid in enumerate(_dedup(retrieved)[:k], start=1):
        if cid in rel_set:
            return 1.0 / rank
    return 0.0


def dcg_at_k(
    retrieved: Sequence[int],
    relevant: Sequence[int],
    k: int = 10,
) -> float:
    """Discounted Cumulative Gain at K (binary relevance)."""
    rel_set = set(relevant)
    return sum(
        1.0 / math.log2(rank + 1)
        for rank, cid in enumerate(_dedup(retrieved)[:k], start=1)
        if cid in rel_set
    )


def ndcg_at_k(
    retrieved: Sequence[int],
    relevant: Sequence[int],
    k: int = 10,
) -> float:
    """Normalised Discounted Cumulative Gain at K.

    Normalises by the ideal DCG (all relevant docs in top positions).
    Returns 0.0 if relevant is empty.
    """
    if not relevant:
        return 0.0
    actual_dcg = dcg_at_k(_dedup(retrieved), relevant, k)
    # Ideal: min(|relevant|, k) relevant items at ranks 1, 2, ...
    ideal_hits = min(len(relevant), k)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    if ideal_dcg == 0.0:
        return 0.0
    return actual_dcg / ideal_dcg


def compute_metrics(
    results: list[dict],
    ground_truth: list[dict],
    k: int = 10,
) -> RetrievalMetrics:
    """Aggregate metrics across a labeled query set.

    Args:
        results: list of {"query_id": str, "retrieved_chunk_ids": list[int]}
        ground_truth: list of {"query_id": str, "relevant_chunk_ids": list[int]}
        k: cutoff position (default 10)

    Returns:
        RetrievalMetrics with macro-averaged scores.
    """
    gt_map: dict[str, list[int]] = {
        g["query_id"]: g["relevant_chunk_ids"] for g in ground_truth
    }

    recalls, precisions, mrrs, ndcgs = [], [], [], []

    for res in results:
        qid = res["query_id"]
        retrieved = res["retrieved_chunk_ids"]
        relevant = gt_map.get(qid, [])

        if not relevant:
            # Skip queries with no ground truth (e.g. website_history)
            continue

        recalls.append(recall_at_k(retrieved, relevant, k))
        precisions.append(precision_at_k(retrieved, relevant, k))
        mrrs.append(mean_reciprocal_rank(retrieved, relevant, k))
        ndcgs.append(ndcg_at_k(retrieved, relevant, k))

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    return RetrievalMetrics(
        recall_10=round(_mean(recalls), 4),
        precision_10=round(_mean(precisions), 4),
        mrr=round(_mean(mrrs), 4),
        ndcg_10=round(_mean(ndcgs), 4),
    )
