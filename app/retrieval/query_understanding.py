"""Query understanding via LLM call.

Extracts: topic_keywords, date_range, source_type_hint, is_temporal_comparison.
Falls back gracefully to raw query if LLM fails or times out.
"""
from __future__ import annotations

import json
import logging
import os

import httpx

from app.config import settings
from app.models.pydantic_models import StructuredQuery

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a search query analyst. Extract structured information from a research query.

Return ONLY valid JSON with this exact schema:
{
  "topic_keywords": ["keyword1", "keyword2"],
  "date_range_start": null or integer year,
  "date_range_end": null or integer year,
  "source_type_hint": null or one of "book", "paper", "website",
  "is_temporal_comparison": true or false
}

Rules:
- topic_keywords: 2-5 most relevant search terms
- date_range: extract explicit years mentioned; null if not specified
- source_type_hint: only set if clearly implied by the query
- is_temporal_comparison: true if query compares two time periods
"""


async def understand_query(raw_query: str) -> StructuredQuery:
    """Extract structured query parameters from a raw user query.

    Args:
        raw_query: The user's natural language query.

    Returns:
        StructuredQuery with extracted parameters.
        Falls back to raw query with no filters on any failure.
    """
    if not settings.llm_api_key:
        logger.warning("No LLM API key configured — using raw query fallback")
        return _fallback(raw_query)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": raw_query},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 200,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
            data = json.loads(content)

            return StructuredQuery(
                raw_query=raw_query,
                topic_keywords=data.get("topic_keywords", [raw_query]),
                date_range_start=data.get("date_range_start"),
                date_range_end=data.get("date_range_end"),
                source_type_hint=data.get("source_type_hint"),
                is_temporal_comparison=data.get("is_temporal_comparison", False),
            )

    except Exception as exc:
        logger.warning("Query understanding failed (%s) — using raw query fallback", exc)
        return _fallback(raw_query)


def _fallback(raw_query: str) -> StructuredQuery:
    """Fallback: use raw query as topic keywords with no extracted filters."""
    return StructuredQuery(
        raw_query=raw_query,
        topic_keywords=[raw_query],
        date_range_start=None,
        date_range_end=None,
        source_type_hint=None,
        is_temporal_comparison=False,
    )
