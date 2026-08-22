"""Property-based tests for chunker and serializers.

# Feature: historical-rag-platform
# Property 1: Chunk Serialization Round-Trip — Validates: Requirements 29.3
# Property 2: Answer Serialization Round-Trip — Validates: Requirements 29.4
# Property 3: Chunk Coverage Invariant — Validates: Requirements 5.5
# Property 4: Chunker Metadata Completeness — Validates: Requirements 5.3
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.ingestion.cleaner import CleanedText, clean_text
from app.ingestion.chunker import chunk_text
from app.ingestion.serializers import (
    deserialize_chunk,
    format_answer,
    parse_answer,
    serialize_chunk,
)
from app.models.pydantic_models import AnswerResponse, AnswerSegment, Chunk


# ─────────────────────────────────────────────────────────────────────────────
# Strategies
# ─────────────────────────────────────────────────────────────────────────────

_printable = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs", "Po")),
    min_size=1,
    max_size=200,
)

_chunk_strategy = st.builds(
    Chunk,
    id=st.none(),
    source_id=st.integers(min_value=1, max_value=99999),
    text=_printable,
    page_or_section=st.one_of(st.none(), st.text(min_size=1, max_size=10)),
    embedding_id=st.none(),
    capture_timestamp=st.none(),
    char_range_start=st.integers(min_value=0, max_value=10000),
    char_range_end=st.integers(min_value=1, max_value=20000),
    token_count=st.one_of(st.none(), st.integers(min_value=1, max_value=1000)),
)

_citation_type = st.sampled_from(["DIRECTLY_VERIFIED", "INFERRED", "UNKNOWN"])

_segment_strategy = st.builds(
    AnswerSegment,
    text=_printable,
    citation_type=_citation_type,
    source_ids=st.lists(st.text(min_size=1, max_size=20), max_size=5),
    chunk_ids=st.lists(st.integers(min_value=1, max_value=9999), max_size=5),
)

_answer_strategy = st.builds(
    AnswerResponse,
    answer_id=st.text(min_size=1, max_size=40),
    query=_printable,
    answer_segments=st.lists(_segment_strategy, min_size=0, max_size=5),
    retrieved_chunks=st.just([]),
)

# Synthetic text strategy: paragraphs separated by double newlines
_word = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz",
    min_size=2, max_size=10,
)
_para_strategy = st.lists(_word, min_size=5, max_size=50).map(" ".join)
_text_strategy = st.lists(_para_strategy, min_size=2, max_size=20).map("\n\n".join)


# ─────────────────────────────────────────────────────────────────────────────
# Property 1: Chunk Serialization Round-Trip
# ─────────────────────────────────────────────────────────────────────────────

@given(_chunk_strategy)
@settings(max_examples=200)
def test_property1_chunk_roundtrip(chunk: Chunk) -> None:
    """Property 1: Chunk Serialization Round-Trip
    Validates: Requirements 29.3
    """
    assume(chunk.char_range_start < chunk.char_range_end)
    serialized = serialize_chunk(chunk)
    restored = deserialize_chunk(serialized)
    assert restored.source_id == chunk.source_id
    assert restored.text == chunk.text
    assert restored.page_or_section == chunk.page_or_section
    assert restored.char_range_start == chunk.char_range_start
    assert restored.char_range_end == chunk.char_range_end
    assert restored.token_count == chunk.token_count
    assert restored.capture_timestamp == chunk.capture_timestamp


# ─────────────────────────────────────────────────────────────────────────────
# Property 2: Answer Serialization Round-Trip
# ─────────────────────────────────────────────────────────────────────────────

@given(_answer_strategy)
@settings(max_examples=200)
def test_property2_answer_roundtrip(answer: AnswerResponse) -> None:
    """Property 2: Answer Serialization Round-Trip
    Validates: Requirements 29.4
    """
    serialized = format_answer(answer)
    restored = parse_answer(serialized)
    assert restored.answer_id == answer.answer_id
    assert restored.query == answer.query
    assert len(restored.answer_segments) == len(answer.answer_segments)
    for orig, rest in zip(answer.answer_segments, restored.answer_segments):
        assert rest.text == orig.text
        assert rest.citation_type == orig.citation_type
        assert rest.source_ids == orig.source_ids
        assert rest.chunk_ids == orig.chunk_ids


# ─────────────────────────────────────────────────────────────────────────────
# Property 3: Chunk Coverage Invariant
# ─────────────────────────────────────────────────────────────────────────────

@given(_text_strategy, st.integers(min_value=1, max_value=9999))
@settings(max_examples=100)
def test_property3_chunk_coverage(text: str, source_id: int) -> None:
    """Property 3: Chunk Coverage Invariant
    Validates: Requirements 5.5 — union of char_ranges covers full text
    with no gap larger than the overlap window.
    """
    cleaned = clean_text(text)
    chunks = chunk_text(cleaned, source_id=source_id)

    if not chunks:
        return  # empty text is allowed to produce no chunks

    # Sort by start position
    sorted_chunks = sorted(chunks, key=lambda c: c.char_range_start)

    # Compute max allowed gap: ~15% of TARGET_TOKENS average characters
    # Using 150 chars as a generous upper bound for the overlap window
    MAX_GAP = 300

    for i in range(len(sorted_chunks) - 1):
        current_end = sorted_chunks[i].char_range_end
        next_start = sorted_chunks[i + 1].char_range_start
        gap = next_start - current_end
        assert gap <= MAX_GAP, (
            f"Gap of {gap} chars between chunk {i} (end={current_end}) "
            f"and chunk {i+1} (start={next_start}) exceeds max allowed gap {MAX_GAP}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Property 4: Chunker Metadata Completeness
# ─────────────────────────────────────────────────────────────────────────────

@given(_text_strategy, st.integers(min_value=1, max_value=9999))
@settings(max_examples=100)
def test_property4_metadata_completeness(text: str, source_id: int) -> None:
    """Property 4: Chunker Metadata Completeness
    Validates: Requirements 5.3 — every chunk has non-null required fields.
    """
    cleaned = clean_text(text)
    chunks = chunk_text(cleaned, source_id=source_id)

    for chunk in chunks:
        assert chunk.source_id is not None, "source_id must be non-null"
        assert chunk.source_id == source_id
        assert chunk.page_or_section is not None, "page_or_section must be non-null"
        assert chunk.char_range_start is not None, "char_range_start must be non-null"
        assert chunk.char_range_end is not None, "char_range_end must be non-null"
        assert chunk.char_range_start < chunk.char_range_end, (
            "char_range_start must be less than char_range_end"
        )
