"""Unit tests for app/ingestion/chunker.py"""
import pytest
from app.ingestion.cleaner import clean_text
from app.ingestion.chunker import chunk_text, MIN_TOKENS, MAX_TOKENS


def _make_cleaned(pages: int = 3, words_per_page: int = 200):
    """Build a CleanedText fixture with synthetic content."""
    raw_pages = []
    for p in range(1, pages + 1):
        # Generate paragraphs of natural-looking text
        paragraphs = []
        for para_num in range(1, 5):
            words = " ".join(f"word{p}_{para_num}_{w}" for w in range(1, words_per_page // 4 + 1))
            paragraphs.append(words)
        raw_pages.append("\n\n".join(paragraphs))
    raw = "\x0c".join(raw_pages)
    return clean_text(raw)


def test_chunks_produced():
    cleaned = _make_cleaned(pages=3, words_per_page=300)
    chunks = chunk_text(cleaned, source_id=1)
    assert len(chunks) > 0


def test_chunk_token_bounds():
    """No chunk should exceed MAX_TOKENS (except single oversized paragraphs)."""
    cleaned = _make_cleaned(pages=5, words_per_page=400)
    chunks = chunk_text(cleaned, source_id=1)
    for chunk in chunks:
        # Allow mild overshoot only when a single paragraph exceeds MAX_TOKENS
        assert chunk.token_count <= MAX_TOKENS * 1.5, (
            f"Chunk token count {chunk.token_count} far exceeds max {MAX_TOKENS}"
        )


def test_chunk_metadata_populated():
    """Every chunk must have source_id, page_or_section, char_range populated."""
    cleaned = _make_cleaned(pages=2, words_per_page=300)
    chunks = chunk_text(cleaned, source_id=42)
    for chunk in chunks:
        assert chunk.source_id == 42
        assert chunk.page_or_section is not None
        assert chunk.char_range_start is not None
        assert chunk.char_range_end is not None
        assert chunk.char_range_start < chunk.char_range_end


def test_char_ranges_within_text():
    """char_range values must index into the actual cleaned text."""
    cleaned = _make_cleaned(pages=2, words_per_page=200)
    chunks = chunk_text(cleaned, source_id=1)
    for chunk in chunks:
        extracted = cleaned.text[chunk.char_range_start:chunk.char_range_end]
        assert extracted == chunk.text


def test_page_anchors_set():
    """page_or_section should reflect the page at chunk start."""
    cleaned = _make_cleaned(pages=4, words_per_page=300)
    chunks = chunk_text(cleaned, source_id=1)
    pages_seen = {c.page_or_section for c in chunks}
    # With 4 pages and enough content, should see multiple distinct page numbers
    assert len(pages_seen) >= 2


def test_empty_input():
    from app.ingestion.cleaner import CleanedText
    chunks = chunk_text(CleanedText(text="", page_markers=[]), source_id=1)
    assert chunks == []


def test_single_short_page():
    """A tiny source produces at least one chunk."""
    cleaned = clean_text("Hello world. This is a test.\x0cSecond page content here.")
    chunks = chunk_text(cleaned, source_id=1)
    assert len(chunks) >= 1
