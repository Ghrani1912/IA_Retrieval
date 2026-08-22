"""Paragraph-aware chunker for cleaned IA OCR text.

Produces chunks of ~400-600 tokens with 15% overlap.
Every chunk records: source_id, page_or_section, char_range_start, char_range_end.
Page number is derived from the nearest preceding [[PAGE:N]] marker.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.cleaner import CleanedText
from app.models.pydantic_models import Chunk

# Use a simple whitespace tokeniser for token counting (no heavy deps for MVP).
# tiktoken can replace this later without changing the interface.
_WORD_RE = re.compile(r"\S+")

TARGET_TOKENS = 500         # centre of 400-600 range
MIN_TOKENS = 400
MAX_TOKENS = 600
OVERLAP_RATIO = 0.15        # 15%

_PAGE_MARKER_RE = re.compile(r"\[\[PAGE:(\d+)\]\]")
_PARAGRAPH_BREAK_RE = re.compile(r"\n\s*\n")   # double newline = paragraph boundary


def _token_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _page_at(char_pos: int, page_markers: list[tuple[int, int]]) -> str:
    """Return the page number string for a given character position."""
    current_page = "1"
    for marker_pos, page_num in page_markers:
        if marker_pos <= char_pos:
            current_page = str(page_num)
        else:
            break
    return current_page


def chunk_text(cleaned: CleanedText, source_id: int) -> list[Chunk]:
    """Split cleaned text into overlapping chunks.

    Args:
        cleaned: CleanedText from cleaner.clean_text().
        source_id: DB id of the parent source row.

    Returns:
        List of Chunk objects (id=None, embedding_id=None — not yet persisted).
    """
    text = cleaned.text
    if not text.strip():
        return []

    # Split into paragraphs, keeping positions
    paragraphs: list[tuple[int, int, str]] = []   # (start, end, text)
    last_end = 0
    for m in _PARAGRAPH_BREAK_RE.finditer(text):
        para_text = text[last_end:m.start()]
        if para_text.strip():
            paragraphs.append((last_end, m.start(), para_text))
        last_end = m.end()
    if last_end < len(text) and text[last_end:].strip():
        paragraphs.append((last_end, len(text), text[last_end:]))

    if not paragraphs:
        # Fallback: treat whole text as one paragraph
        paragraphs = [(0, len(text), text)]

    # Greedily merge paragraphs into chunks
    chunks: list[Chunk] = []
    overlap_tokens = int(TARGET_TOKENS * OVERLAP_RATIO)

    i = 0
    while i < len(paragraphs):
        chunk_parts: list[tuple[int, int, str]] = []
        token_count = 0
        j = i

        # Accumulate paragraphs until we reach TARGET_TOKENS
        while j < len(paragraphs):
            para_start, para_end, para_text = paragraphs[j]
            para_tokens = _token_count(para_text)

            if token_count + para_tokens > MAX_TOKENS and chunk_parts:
                break   # adding this would exceed max; flush current chunk

            chunk_parts.append((para_start, para_end, para_text))
            token_count += para_tokens
            j += 1

            if token_count >= TARGET_TOKENS:
                break   # hit target; flush

        if not chunk_parts:
            # Single paragraph exceeds MAX_TOKENS — include it anyway
            chunk_parts = [paragraphs[j]]
            j += 1

        chunk_start = chunk_parts[0][0]
        chunk_end = chunk_parts[-1][1]
        chunk_text_str = text[chunk_start:chunk_end]

        page = _page_at(chunk_start, cleaned.page_markers)

        chunks.append(Chunk(
            id=None,
            source_id=source_id,
            text=chunk_text_str,
            page_or_section=page,
            embedding_id=None,
            capture_timestamp=None,
            char_range_start=chunk_start,
            char_range_end=chunk_end,
            token_count=token_count,
        ))

        # Advance with overlap: step back by overlap_tokens worth of paragraphs
        if j < len(paragraphs):
            overlap_count = 0
            step_back = j - 1
            while step_back > i and overlap_count < overlap_tokens:
                overlap_count += _token_count(paragraphs[step_back][2])
                step_back -= 1
            i = max(i + 1, step_back + 1)
        else:
            break

    return chunks
