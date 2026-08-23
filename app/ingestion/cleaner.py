"""Text cleaning for raw IA OCR output.

Handles:
- Form-feed characters (\x0c) → page markers [[PAGE:N]]
- Line-break hyphenation rejoining
- Running header/footer detection and removal
- Preserves page anchor positions for downstream chunking

Constraint: cleaning is STRUCTURAL only — no word substitution or
paraphrasing. Every token that enters cleaning must exit unchanged
(just with structural artifacts removed around it).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class CleanedText:
    text: str
    # (char_position_in_cleaned_text, page_number) — 0-indexed
    page_markers: list[tuple[int, int]] = field(default_factory=list)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

_FORM_FEED = "\x0c"
_PAGE_MARKER_RE = re.compile(r"\[\[PAGE:(\d+)\]\]")


def _split_pages(raw: str) -> list[str]:
    """Split raw djvu text on form-feed characters into per-page strings."""
    return raw.split(_FORM_FEED)


def _detect_running_lines(pages: list[str], threshold: float = 0.5) -> set[str]:
    """Detect header/footer lines that appear on more than `threshold` fraction of pages.

    Returns a set of stripped line strings to remove.
    Only considers lines that appear on at least 3 pages (avoids removing
    content that happens to repeat once).
    """
    if len(pages) < 4:
        return set()

    # Count how many pages each stripped line appears on
    line_page_count: Counter[str] = Counter()
    for page_text in pages:
        # Look at first 3 and last 3 lines of each page (header/footer zone)
        lines = page_text.strip().splitlines()
        candidate_lines = set()
        for line in lines[:3] + lines[-3:]:
            stripped = line.strip()
            if stripped and len(stripped) > 3:   # skip very short lines
                candidate_lines.add(stripped)
        for line in candidate_lines:
            line_page_count[line] += 1

    min_pages = max(3, int(len(pages) * threshold))
    return {line for line, count in line_page_count.items() if count >= min_pages}


def _remove_running_lines(page_text: str, running_lines: set[str]) -> str:
    """Remove detected header/footer lines from a single page's text."""
    if not running_lines:
        return page_text
    result_lines = []
    for line in page_text.splitlines():
        if line.strip() not in running_lines:
            result_lines.append(line)
    return "\n".join(result_lines)


_HYPHEN_BREAK_RE = re.compile(
    r"([A-Za-z])-\n([a-z])",   # word- \n continuation (lowercase join = mid-word)
)


def _rejoin_hyphenated(text: str) -> str:
    """Rejoin words split across line breaks by OCR hyphenation.

    Only rejoins when the break is: letter-hyphen-newline-lowercase-letter
    (i.e. clearly a continuation, not a sentence-final hyphen or proper noun).
    """
    return _HYPHEN_BREAK_RE.sub(r"\1\2", text)


# -----------------------------------------------------------------------
# Junk page detection (TOC, index, front matter)
# -----------------------------------------------------------------------


def is_junk_page(text: str) -> bool:
    """Detect non-content pages: TOC, index, title pages, copyright, name lists.

    Returns True if the page is structural/metadata rather than real content.
    Used to filter chunks during ingestion and cleanup.
    """
    if not text or len(text.strip()) < 50:
        return True

    total_words = len(text.split())
    if total_words < 30:
        return True

    # Copyright / digitization page
    if re.search(
        r"Digitized by|Internet Archive|Library of Congress|archive\.org/",
        text,
        re.IGNORECASE,
    ):
        return True

    # Table of contents: lines ending with / <page_number>
    toc_lines = len(re.findall(r"\d+\.\s+.+/\s*\d+\b", text))
    if toc_lines >= 3:
        return True

    # Name list: many lines matching "First Last" or "First Last (Institution)"
    name_lines = len(re.findall(r"^[A-Z][a-z]+\s+[A-Z][a-z]+", text, re.MULTILINE))
    if name_lines >= 8:
        return True

    # Preface / acknowledgments
    if re.search(
        r"acknowledgment|acknowledgement|preface|foreword|"
        r"since the.*project began|we wish|we are grateful",
        text,
        re.IGNORECASE,
    ):
        return True

    # Title page: very few words relative to character count (lots of whitespace/OCR garble)
    whitespace_ratio = 1 - (total_words / max(len(text), 1))
    if total_words < 50 and whitespace_ratio > 0.4:
        return True

    return False


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def clean_text(raw: str) -> CleanedText:
    """Clean raw IA OCR text and embed page markers.

    Args:
        raw: Raw text from _djvu.txt or _hocr.html.

    Returns:
        CleanedText with cleaned text and page_markers list.
    """
    if not raw:
        return CleanedText(text="", page_markers=[])

    # 1. Split on form-feeds to get per-page content
    pages = _split_pages(raw)

    # 2. Detect running headers/footers across pages
    running_lines = _detect_running_lines(pages)

    # 3. Clean each page: remove running lines
    cleaned_pages: list[str] = []
    for page_text in pages:
        cleaned = _remove_running_lines(page_text, running_lines)
        cleaned_pages.append(cleaned)

    # 4. Reassemble with inline page markers and record marker positions
    output_parts: list[str] = []
    page_markers: list[tuple[int, int]] = []
    char_pos = 0

    for page_num, page_text in enumerate(cleaned_pages, start=1):
        # Record marker position before inserting it
        marker = f"[[PAGE:{page_num}]]"
        page_markers.append((char_pos, page_num))
        output_parts.append(marker)
        char_pos += len(marker)

        if page_text.strip():
            output_parts.append(page_text)
            char_pos += len(page_text)

    combined = "".join(output_parts)

    # 5. Rejoin hyphenated line breaks
    combined = _rejoin_hyphenated(combined)

    return CleanedText(text=combined, page_markers=page_markers)
