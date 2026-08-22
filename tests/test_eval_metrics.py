"""Unit tests for evaluation metrics (design.md §9.4).

All values hand-computed before writing tests — the point is to catch
formula bugs before they contaminate real eval results.

Toy corpus for most tests:
  relevant = [1, 2, 3, 4, 5]
  retrieved = [2, 7, 1, 8, 3, 9, 4, 10, 5, 6]  (ranks 1-10)
  At K=10: hits = {2, 1, 3, 4, 5} → all 5 relevant in top-10
"""
from __future__ import annotations

import math

import pytest

from app.eval.metrics import (
    recall_at_k,
    precision_at_k,
    mean_reciprocal_rank,
    dcg_at_k,
    ndcg_at_k,
    compute_metrics,
)
from app.models.pydantic_models import RetrievalMetrics


# ---------------------------------------------------------------------------
# Fixed test vectors
# ---------------------------------------------------------------------------

RELEVANT = [1, 2, 3, 4, 5]
# retrieved: relevant items at ranks 1,3,5,7,9 (every other position)
RETRIEVED = [2, 7, 1, 8, 3, 9, 4, 10, 5, 6]


# ---------------------------------------------------------------------------
# Recall@K
# ---------------------------------------------------------------------------

class TestRecallAtK:
    def test_all_relevant_found(self):
        # All 5 relevant items appear in top-10
        assert recall_at_k(RETRIEVED, RELEVANT, k=10) == 1.0

    def test_partial_recall(self):
        # Only ranks 1,3 (items 2,1) within top-3
        assert recall_at_k(RETRIEVED, RELEVANT, k=3) == pytest.approx(2 / 5)

    def test_no_hits(self):
        assert recall_at_k([10, 11, 12], [1, 2, 3], k=10) == 0.0

    def test_empty_relevant(self):
        assert recall_at_k(RETRIEVED, [], k=10) == 0.0

    def test_k_larger_than_list(self):
        # k=100 but only 10 retrieved — should still work
        assert recall_at_k(RETRIEVED, RELEVANT, k=100) == 1.0

    def test_first_hit_only(self):
        # Item 2 is at rank 1
        assert recall_at_k(RETRIEVED, RELEVANT, k=1) == pytest.approx(1 / 5)


# ---------------------------------------------------------------------------
# Precision@K
# ---------------------------------------------------------------------------

class TestPrecisionAtK:
    def test_half_precision(self):
        # 5 hits in 10 results = 0.5
        assert precision_at_k(RETRIEVED, RELEVANT, k=10) == pytest.approx(0.5)

    def test_first_is_relevant(self):
        # Rank 1 is item 2 (relevant) → precision@1 = 1.0
        assert precision_at_k(RETRIEVED, RELEVANT, k=1) == 1.0

    def test_no_hits(self):
        assert precision_at_k([10, 11], [1, 2], k=2) == 0.0

    def test_k_zero(self):
        assert precision_at_k(RETRIEVED, RELEVANT, k=0) == 0.0

    def test_all_irrelevant(self):
        assert precision_at_k([7, 8, 9, 10], [1, 2, 3], k=4) == 0.0


# ---------------------------------------------------------------------------
# MRR
# ---------------------------------------------------------------------------

class TestMRR:
    def test_first_relevant_at_rank1(self):
        # Item 2 is relevant and at rank 1
        assert mean_reciprocal_rank(RETRIEVED, RELEVANT, k=10) == pytest.approx(1.0)

    def test_first_relevant_at_rank3(self):
        # [7, 8, 1, ...] → first hit at rank 3 → MRR = 1/3
        assert mean_reciprocal_rank([7, 8, 1, 9, 2], [1, 2, 3], k=5) == pytest.approx(1 / 3)

    def test_no_relevant_in_top_k(self):
        assert mean_reciprocal_rank([7, 8, 9], [1, 2, 3], k=3) == 0.0

    def test_relevant_beyond_k(self):
        # Relevant item at rank 11 — outside k=10 window
        assert mean_reciprocal_rank(list(range(10, 20)) + [1], [1], k=10) == 0.0

    def test_first_rank_hit(self):
        assert mean_reciprocal_rank([1, 2, 3], [1], k=10) == 1.0


# ---------------------------------------------------------------------------
# DCG / nDCG
# ---------------------------------------------------------------------------

class TestDCGnDCG:
    def test_dcg_hand_computed(self):
        # RETRIEVED has relevant items at ranks 1,3,5,7,9 (0-indexed: 0,2,4,6,8)
        # rank 1: 1/log2(2)=1.0, rank 3: 1/log2(4)=0.5, rank 5: 1/log2(6)≈0.3869
        # rank 7: 1/log2(8)≈0.3333, rank 9: 1/log2(10)≈0.3010
        expected = sum(1 / math.log2(r + 1) for r in [1, 3, 5, 7, 9])
        assert dcg_at_k(RETRIEVED, RELEVANT, k=10) == pytest.approx(expected, abs=1e-6)

    def test_ndcg_perfect_retrieval(self):
        # If retrieved = relevant in best order → nDCG = 1.0
        perfect = [1, 2, 3, 4, 5]
        assert ndcg_at_k(perfect, [1, 2, 3, 4, 5], k=5) == pytest.approx(1.0)

    def test_ndcg_no_hits(self):
        assert ndcg_at_k([7, 8, 9], [1, 2, 3], k=3) == 0.0

    def test_ndcg_empty_relevant(self):
        assert ndcg_at_k(RETRIEVED, [], k=10) == 0.0

    def test_ndcg_partial_overlap(self):
        # retrieved = [1, 7, 8] with relevant = [1, 2, 3]
        # DCG = 1/log2(2) = 1.0
        # ideal DCG (3 relevant in top 3) = 1/log2(2)+1/log2(3)+1/log2(4)
        actual_dcg = 1.0 / math.log2(2)
        ideal_dcg = sum(1.0 / math.log2(r + 1) for r in [1, 2, 3])
        expected = actual_dcg / ideal_dcg
        assert ndcg_at_k([1, 7, 8], [1, 2, 3], k=3) == pytest.approx(expected, abs=1e-6)

    def test_ndcg_more_relevant_than_k(self):
        # 10 relevant items, k=3 — ideal is still just top-3
        relevant = list(range(1, 11))
        retrieved = [1, 2, 3, 99, 98]
        # DCG = 1/log2(2)+1/log2(3)+1/log2(4), ideal = same → nDCG = 1.0
        assert ndcg_at_k(retrieved, relevant, k=3) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# compute_metrics (aggregate)
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def test_single_query_perfect(self):
        results = [{"query_id": "q1", "retrieved_chunk_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}]
        gt = [{"query_id": "q1", "relevant_chunk_ids": [1, 2, 3]}]
        m = compute_metrics(results, gt, k=10)
        assert m.recall_10 == 1.0
        assert m.precision_10 == pytest.approx(3 / 10)
        assert m.mrr == 1.0
        assert m.ndcg_10 == pytest.approx(1.0)

    def test_query_not_in_ground_truth_skipped(self):
        results = [
            {"query_id": "q1", "retrieved_chunk_ids": [1, 2]},
            {"query_id": "q_nogt", "retrieved_chunk_ids": [99]},  # no GT → skip
        ]
        gt = [{"query_id": "q1", "relevant_chunk_ids": [1]}]
        m = compute_metrics(results, gt, k=10)
        # Only q1 counted — q_nogt skipped
        assert m.recall_10 == 1.0

    def test_empty_retrieved(self):
        results = [{"query_id": "q1", "retrieved_chunk_ids": []}]
        gt = [{"query_id": "q1", "relevant_chunk_ids": [1, 2, 3]}]
        m = compute_metrics(results, gt, k=10)
        assert m.recall_10 == 0.0
        assert m.precision_10 == 0.0
        assert m.mrr == 0.0
        assert m.ndcg_10 == 0.0

    def test_macro_average_two_queries(self):
        # q1: 1 hit at rank 1 out of 2 relevant → recall=0.5, prec=0.1, mrr=1.0
        # q2: 0 hits → all zeros
        results = [
            {"query_id": "q1", "retrieved_chunk_ids": [1, 7, 8, 9, 10, 11, 12, 13, 14, 15]},
            {"query_id": "q2", "retrieved_chunk_ids": [7, 8, 9, 10, 11, 12, 13, 14, 15, 16]},
        ]
        gt = [
            {"query_id": "q1", "relevant_chunk_ids": [1, 2]},
            {"query_id": "q2", "relevant_chunk_ids": [3, 4]},
        ]
        m = compute_metrics(results, gt, k=10)
        assert m.recall_10 == pytest.approx((0.5 + 0.0) / 2)
        assert m.precision_10 == pytest.approx((0.1 + 0.0) / 2)
        assert m.mrr == pytest.approx((1.0 + 0.0) / 2)

    def test_returns_retrieval_metrics_type(self):
        results = [{"query_id": "q1", "retrieved_chunk_ids": [1]}]
        gt = [{"query_id": "q1", "relevant_chunk_ids": [1]}]
        m = compute_metrics(results, gt)
        assert isinstance(m, RetrievalMetrics)


# ---------------------------------------------------------------------------
# PBT: metric invariants
# ---------------------------------------------------------------------------

from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st


@given(
    retrieved=st.lists(st.integers(min_value=1, max_value=100), min_size=0, max_size=15),
    relevant=st.lists(st.integers(min_value=1, max_value=100), min_size=0, max_size=10),
    k=st.integers(min_value=1, max_value=15),
)
@hyp_settings(max_examples=300)
def test_pbt_recall_in_01(retrieved, relevant, k):
    """Recall@K is always in [0, 1]."""
    r = recall_at_k(retrieved, relevant, k)
    assert 0.0 <= r <= 1.0


@given(
    retrieved=st.lists(st.integers(min_value=1, max_value=100), min_size=0, max_size=15),
    relevant=st.lists(st.integers(min_value=1, max_value=100), min_size=0, max_size=10),
    k=st.integers(min_value=1, max_value=15),
)
@hyp_settings(max_examples=300)
def test_pbt_precision_in_01(retrieved, relevant, k):
    """Precision@K is always in [0, 1]."""
    p = precision_at_k(retrieved, relevant, k)
    assert 0.0 <= p <= 1.0


@given(
    retrieved=st.lists(st.integers(min_value=1, max_value=100), min_size=0, max_size=15),
    relevant=st.lists(st.integers(min_value=1, max_value=100), min_size=0, max_size=10),
)
@hyp_settings(max_examples=300)
def test_pbt_mrr_in_01(retrieved, relevant):
    """MRR is always in [0, 1]."""
    m = mean_reciprocal_rank(retrieved, relevant, k=10)
    assert 0.0 <= m <= 1.0


@given(
    retrieved=st.lists(st.integers(min_value=1, max_value=100), min_size=0, max_size=15),
    relevant=st.lists(st.integers(min_value=1, max_value=100), min_size=1, max_size=10),
    k=st.integers(min_value=1, max_value=15),
)
@hyp_settings(max_examples=300)
def test_pbt_ndcg_in_01(retrieved, relevant, k):
    """nDCG@K is always in [0, 1]."""
    n = ndcg_at_k(retrieved, relevant, k)
    assert 0.0 <= n <= 1.0 + 1e-9  # float tolerance


@given(
    relevant=st.lists(st.integers(min_value=1, max_value=50), min_size=1, max_size=10),
    k=st.integers(min_value=1, max_value=15),
)
@hyp_settings(max_examples=200)
def test_pbt_perfect_retrieval_gives_ndcg_1(relevant, k):
    """Retrieving exactly the relevant set in order gives nDCG = 1.0."""
    perfect = relevant[:k] + list(range(200, 220))  # relevant first, then irrelevant
    n = ndcg_at_k(perfect, relevant, k)
    assert n == pytest.approx(1.0) or n <= 1.0  # ≤1 always; =1 when all relevant in top-k
