"""Unit tests for app/ingestion/cleaner.py"""
import pytest
from app.ingestion.cleaner import clean_text, CleanedText


def test_dehyphenation():
    raw = "artifi-\ncial intelligence"
    result = clean_text(raw)
    assert "artificial" in result.text
    assert "artifi-\n" not in result.text


def test_page_markers_preserved():
    raw = "page one content\x0cpage two content\x0cpage three"
    result = clean_text(raw)
    assert "[[PAGE:1]]" in result.text
    assert "[[PAGE:2]]" in result.text
    assert "[[PAGE:3]]" in result.text
    assert len(result.page_markers) == 3


def test_page_marker_positions_match():
    raw = "hello\x0cworld"
    result = clean_text(raw)
    for char_pos, page_num in result.page_markers:
        marker = f"[[PAGE:{page_num}]]"
        assert result.text[char_pos:char_pos + len(marker)] == marker


def test_empty_input():
    result = clean_text("")
    assert result.text == ""
    assert result.page_markers == []


def test_no_formfeeds():
    raw = "just some text without page breaks"
    result = clean_text(raw)
    assert "[[PAGE:1]]" in result.text
    assert "just some text" in result.text


def test_no_word_token_alteration():
    """Cleaning must not alter actual word tokens — structural only."""
    raw = "The quick brown fox\x0cjumped over the lazy dog"
    result = clean_text(raw)
    # All original words must still be present
    for word in ["The", "quick", "brown", "fox", "jumped", "over", "the", "lazy", "dog"]:
        assert word in result.text


def test_running_header_removed():
    """A line appearing on >50% of pages should be stripped."""
    header = "RUNNING HEADER TEXT"
    pages = [f"{header}\nPage {i} content here with lots of text\n{header}" for i in range(8)]
    raw = "\x0c".join(pages)
    result = clean_text(raw)
    # Header should appear far less often after cleaning (may appear 0-1 times due to detection)
    count = result.text.count(header)
    assert count < 4  # significantly reduced from 8


def test_already_clean_text_unchanged():
    """A page with no OCR artifacts should pass through with minimal changes."""
    raw = "Normal paragraph one.\n\nNormal paragraph two.\n\nNormal paragraph three."
    result = clean_text(raw)
    assert "Normal paragraph one." in result.text
    assert "Normal paragraph two." in result.text
    assert "Normal paragraph three." in result.text
