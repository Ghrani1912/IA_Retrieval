"""Property-based tests for RRF fusion.

# Feature: historical-rag-platform
# Property 5: RRF Score Formula Correctness — Validates: Requirements 14.1-14.4
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.pydantic_models import Chunk, RankedChunk
from app.retrieval.rrf import K, TOP_N, fuse_rrf


def _make_ranked_chunk(chunk_id: int, rank: int, score: float = 1.0) -> RankedChunk:
    chunk = Chunk(
        id=chunk_id,
        source_id=1,
        text=f"text for chunk {chunk_id}",
        char_range_start=0,
        char_range_end=10,
    )
    return RankedChunk(chunk=chunk, rank=rank, score=score)


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests
# ─────────────────────────────────────────────────────────────────────────────

def test_rrf_chunk_in_both_lists_has_higher_score():
    """A chunk in both lists should score higher than one in only one list."""
    shared_id = 42
    only_bm25_id = 99

    bm25 = [_make_ranked_chunk(shared_id, 1), _make_ranked_chunk(only_bm25_id, 2)]
    vector = [_make_ranked_chunk(shared_id, 1), _make_ranked_chunk(999, 2)]

    result = fuse_rrf(bm25, vector)
    scores = {r.chunk.id: r.score for r in result}

    assert scores[shared_id] > scores.get(only_bm25_id, 0), (
        "Chunk in both lists should outscore chunk in one list"
    )


def test_rrf_formula_single_list():
    """Score for a chunk in only one list should be 1/(k + rank)."""
    bm25 = [_make_ranked_chunk(1, 1), _make_ranked_chunk(2, 2)]
    vector = [_make_ranked_chunk(3, 1)]

    result = fuse_rrf(bm25, vector, k=60)
    scores = {r.chunk.id: r.score for r in result}

    expected_1 = 1.0 / (60 + 1)
    expected_2 = 1.0 / (60 + 2)
    assert abs(scores[1] - expected_1) < 1e-9
    assert abs(scores[2] - expected_2) < 1e-9


def test_rrf_formula_both_lists():
    """Score for a chunk in both lists at rank 1 each should be 2/(k+1)."""
    shared = _make_ranked_chunk(42, 1)
    bm25 = [shared]
    vector = [_make_ranked_chunk(42, 1)]

    result = fuse_rrf(bm25, vector, k=60)
    expected = 2.0 / (60 + 1)
    assert abs(result[0].score - expected) < 1e-9


def test_rrf_result_sorted_descending():
    """Results must be sorted by descending RRF score."""
    bm25 = [_make_ranked_chunk(i, i) for i in range(1, 21)]
    vector = [_make_ranked_chunk(i + 10, i) for i in range(1, 21)]

    result = fuse_rrf(bm25, vector)
    for i in range(len(result) - 1):
        assert result[i].score >= result[i + 1].score


def test_rrf_top_n_limit():
    """Result should contain at most TOP_N items."""
    bm25 = [_make_ranked_chunk(i, i) for i in range(1, 51)]
    vector = [_make_ranked_chunk(i + 50, i) for i in range(1, 51)]

    result = fuse_rrf(bm25, vector, top_n=30)
    assert len(result) <= 30


def test_rrf_empty_inputs():
    result = fuse_rrf([], [])
    assert result == []


def test_rrf_one_empty_list():
    bm25 = [_make_ranked_chunk(1, 1), _make_ranked_chunk(2, 2)]
    result = fuse_rrf(bm25, [])
    assert len(result) == 2
    # Score should be 1/(k+rank) since only one list
    expected_top = 1.0 / (K + 1)
    assert abs(result[0].score - expected_top) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# Property 5: RRF Score Formula Correctness
# ─────────────────────────────────────────────────────────────────────────────

_chunk_id_strategy = st.integers(min_value=1, max_value=200)
_rank_strategy = st.integers(min_value=1, max_value=50)


@given(
    bm25_ids=st.lists(st.integers(1, 100), min_size=0, max_size=50, unique=True),
    vector_ids=st.lists(st.integers(1, 100), min_size=0, max_size=50, unique=True),
)
@settings(max_examples=200)
def test_property5_rrf_formula_correctness(
    bm25_ids: list[int],
    vector_ids: list[int],
) -> None:
    """Property 5: RRF Score Formula Correctness
    Validates: Requirements 14.1, 14.2, 14.3, 14.4
    """
    bm25 = [_make_ranked_chunk(cid, rank) for rank, cid in enumerate(bm25_ids, start=1)]
    vector = [_make_ranked_chunk(cid, rank) for rank, cid in enumerate(vector_ids, start=1)]

    result = fuse_rrf(bm25, vector)

    # Build expected scores manually
    expected_scores: dict[int, float] = {}
    for rank, cid in enumerate(bm25_ids, start=1):
        expected_scores[cid] = expected_scores.get(cid, 0.0) + 1.0 / (K + rank)
    for rank, cid in enumerate(vector_ids, start=1):
        expected_scores[cid] = expected_scores.get(cid, 0.0) + 1.0 / (K + rank)

    # Verify scores match formula
    for item in result:
        cid = item.chunk.id
        assert cid in expected_scores, f"Unexpected chunk_id {cid} in result"
        assert abs(item.score - expected_scores[cid]) < 1e-9, (
            f"Score mismatch for chunk {cid}: "
            f"got {item.score}, expected {expected_scores[cid]}"
        )

    # Verify sorted descending
    for i in range(len(result) - 1):
        assert result[i].score >= result[i + 1].score, "Results not sorted descending"

    # Verify top_n limit
    assert len(result) <= TOP_N
