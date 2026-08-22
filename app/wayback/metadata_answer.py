"""Answer metadata questions about Wayback snapshots directly.

When a user asks "how many snapshots", "when was the first snapshot", etc.,
answer from the website_snapshots table instead of going through the LLM
retrieval pipeline. This is fast, deterministic, and accurate.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")

# ---------------------------------------------------------------------------
# Keyword patterns that indicate metadata questions (not content questions)
# ---------------------------------------------------------------------------

_SNAPSHOT_COUNT_RE = re.compile(
    r"(?:how\s+many|number\s+of|count\s+of|total)\s+"
    r"(?:wayback\s+)?(?:snapshots?|captures?|crawls?|archives?|waybacks?)",
    re.IGNORECASE,
)

_YEAR_DISTRIBUTION_RE = re.compile(
    r"(?:what|which)\s+(?:years?|time\s*periods?|dates?)\s+"
    r"(?:have|has|had|contain|contain|show|include|cover)",
    re.IGNORECASE,
)

_YEAR_DISTRIBUTION_RE2 = re.compile(
    r"(?:snapshots?|captures?|crawls?)\s+(?:by|per|in|during|from)\s+(?:year|time)",
    re.IGNORECASE,
)

_FIRST_LAST_RE = re.compile(
    r"(?:when|what(?:'s|\s+is|\s+was)|when\s+was)\s+"
    r"(?:the\s+)?(?:first|earliest|oldest|newest|latest|most\s+recent|last)\s+"
    r"(?:wayback\s+)?(?:snapshot|capture|crawl|archive|wayback)",
    re.IGNORECASE,
)

_FREQ_RE = re.compile(
    r"(?:capture|crawl|snapshot|archive)\s+(?:frequency|rate|pace|interval)",
    re.IGNORECASE,
)

_DATE_RANGE_RE = re.compile(
    r"(?:date|time)\s+range|span\s+of\s+time|how\s+(?:long|old)|since\s+when|from\s+when",
    re.IGNORECASE,
)

# Combined: return True if query looks like a metadata question about snapshots
ALL_PATTERNS = [
    _SNAPSHOT_COUNT_RE,
    _YEAR_DISTRIBUTION_RE,
    _YEAR_DISTRIBUTION_RE2,
    _FIRST_LAST_RE,
    _FREQ_RE,
    _DATE_RANGE_RE,
]


def is_snapshot_metadata_query(query: str) -> bool:
    """Return True if the query is asking about Wayback snapshot metadata
    rather than the website's content."""
    return any(p.search(query) for p in ALL_PATTERNS)


# ---------------------------------------------------------------------------
# Snapshot metadata aggregation
# ---------------------------------------------------------------------------

async def _fetch_snapshot_stats(domain: str) -> dict:
    """Aggregate snapshot metadata from the database."""
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM website_snapshots WHERE domain = $1", domain
        )
        if total == 0:
            return {"domain": domain, "total": 0}

        year_rows = await conn.fetch(
            """SELECT EXTRACT(YEAR FROM snapshot_timestamp)::int AS year,
                      COUNT(*) AS cnt
               FROM website_snapshots
               WHERE domain = $1
               GROUP BY year ORDER BY year""",
            domain,
        )

        earliest = await conn.fetchval(
            "SELECT MIN(snapshot_timestamp) FROM website_snapshots WHERE domain = $1",
            domain,
        )
        latest = await conn.fetchval(
            "SELECT MAX(snapshot_timestamp) FROM website_snapshots WHERE domain = $1",
            domain,
        )

        status_rows = await conn.fetch(
            """SELECT status_code, COUNT(*) AS cnt
               FROM website_snapshots
               WHERE domain = $1
               GROUP BY status_code ORDER BY cnt DESC""",
            domain,
        )

        return {
            "domain": domain,
            "total": total,
            "earliest": earliest,
            "latest": latest,
            "years": [(r["year"], r["cnt"]) for r in year_rows],
            "status_codes": [(r["status_code"], r["cnt"]) for r in status_rows],
        }
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

def _generate_answer(query: str, stats: dict) -> str | None:
    """Generate a natural-language answer based on snapshot stats.
    Returns None if we can't determine what the user is asking."""
    if stats["total"] == 0:
        return None

    domain = stats["domain"]
    total = stats["total"]
    earliest = stats["earliest"]
    latest = stats["latest"]
    years = stats["years"]

    # "How many snapshots" — check if year-specific
    if _SNAPSHOT_COUNT_RE.search(query):
        year_match = re.search(r"\b(19|20)\d{2}\b", query)
        if year_match:
            target_year = int(year_match.group())
            count = sum(c for y, c in years if y == target_year)
            if count > 0:
                return (
                    f"The Wayback Machine has {count} snapshot{'s' if count != 1 else ''} "
                    f"of {domain} from {target_year}. "
                    f"The domain has {total} total snapshots spanning "
                    f"{earliest.year} to {latest.year}."
                )
            else:
                return (
                    f"There are no Wayback snapshots of {domain} from {target_year}. "
                    f"The domain has {total} total snapshots spanning "
                    f"{earliest.year} to {latest.year}."
                )
        else:
            return (
                f"The Wayback Machine has {total} snapshot{'s' if total != 1 else ''} "
                f"of {domain}, spanning from {earliest.strftime('%B %d, %Y')} "
                f"to {latest.strftime('%B %d, %Y')}."
            )

    # "When was the first/last snapshot"
    if _FIRST_LAST_RE.search(query):
        if "first" in query.lower() or "earliest" in query.lower() or "oldest" in query.lower():
            return (
                f"The earliest Wayback snapshot of {domain} was taken on "
                f"{earliest.strftime('%B %d, %Y')}. "
                f"The domain has {total} total snapshots."
            )
        else:
            return (
                f"The most recent Wayback snapshot of {domain} was taken on "
                f"{latest.strftime('%B %d, %Y')}. "
                f"The domain has {total} total snapshots spanning {earliest.year} to {latest.year}."
            )

    # "What years" or "snapshot frequency" — give year distribution
    if _YEAR_DISTRIBUTION_RE.search(query) or _YEAR_DISTRIBUTION_RE2.search(query) or _FREQ_RE.search(query):
        year_lines = [f"  {y}: {c} snapshot{'s' if c != 1 else ''}" for y, c in years]
        year_text = "\n".join(year_lines)
        peak_year, peak_count = max(years, key=lambda x: x[1])
        return (
            f"{domain} has {total} Wayback snapshots across "
            f"{len(years)} years ({earliest.year} to {latest.year}):\n\n"
            f"{year_text}\n\n"
            f"Peak capture year: {peak_year} with {peak_count} snapshots."
        )

    # "Date range" / "how long" / general temporal questions
    if _DATE_RANGE_RE.search(query):
        span_days = (latest - earliest).days
        return (
            f"{domain} has been captured by the Wayback Machine for approximately "
            f"{span_days // 365} years ({span_days} days), from "
            f"{earliest.strftime('%B %d, %Y')} to {latest.strftime('%B %d, %Y')}, "
            f"with {total} total snapshots."
        )

    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def try_answer_metadata_query(
    query: str,
    domain: str,
) -> str | None:
    """If the query is about Wayback snapshot metadata, answer directly.

    Returns a formatted answer string, or None if this isn't a metadata question.
    """
    if not is_snapshot_metadata_query(query):
        return None

    stats = await _fetch_snapshot_stats(domain)
    return _generate_answer(query, stats)
