"""LLM-as-judge faithfulness evaluation (design.md section 9.5).

For each (answer_segment, cited_chunk) pair, asks the LLM whether the
chunk actually supports the claim.  Aggregates to a citation_correctness_rate.

Falls back gracefully when no LLM API key is configured — returns None
for faithfulness verdicts and logs a warning.
"""
from __future__ import annotations

import logging
import re

import httpx

from app.config import settings
from app.models.pydantic_models import AnswerResponse, Chunk, FaithfulnessVerdict

logger = logging.getLogger(__name__)

JUDGE_PROMPT_TEMPLATE = """Does the following chunk support the claim?

Claim: {claim}

Chunk: {chunk_text}

Answer with exactly one word: supported   OR   not_supported"""

_SUPPORTED_RE = re.compile(r"\bsupported\b", re.IGNORECASE)
_NOT_SUPPORTED_RE = re.compile(r"\bnot_supported\b", re.IGNORECASE)


async def _call_llm(prompt: str) -> str | None:
    """Single LLM call for judge verdict; retries with exponential backoff on 429."""
    if not settings.llm_api_key:
        return None
    import asyncio as _asyncio
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    json={
                        "model": settings.llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                        "max_tokens": 1000,
                    },
                )
                if resp.status_code == 429:
                    wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
                    logger.warning("Judge rate limited (429) — waiting %ds (attempt %d/3)", wait, attempt + 1)
                    await _asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"].get("content", "")
                return content.strip() if content else None
        except Exception as exc:
            logger.warning("LLM judge call failed (attempt %d): %s", attempt + 1, exc)
            if attempt < 2:
                await _asyncio.sleep(5)
    return None


def _parse_verdict(raw: str | None) -> str | None:
    """Parse LLM response to 'supported' | 'not_supported' | None."""
    if raw is None:
        return None
    if _NOT_SUPPORTED_RE.search(raw):
        return "not_supported"
    if _SUPPORTED_RE.search(raw):
        return "supported"
    return None


async def judge_faithfulness(
    answer: AnswerResponse,
    chunks_by_id: dict[int, Chunk],
) -> list[FaithfulnessVerdict]:
    """Evaluate every (answer_segment, chunk) citation pair.

    Args:
        answer: The synthesized AnswerResponse to evaluate.
        chunks_by_id: dict mapping chunk.id → Chunk (with full text).

    Returns:
        List of FaithfulnessVerdict, one per (segment, chunk_id) pair.
        Skips pairs where the chunk text is unavailable.
    """
    verdicts: list[FaithfulnessVerdict] = []

    for segment in answer.answer_segments:
        for chunk_id in segment.chunk_ids:
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None or not chunk.text:
                logger.debug("Skipping judge for chunk_id=%d (no text)", chunk_id)
                continue

            prompt = JUDGE_PROMPT_TEMPLATE.format(
                claim=segment.text[:500],
                chunk_text=chunk.text[:1000],
            )
            raw = await _call_llm(prompt)
            verdict_str = _parse_verdict(raw)

            if verdict_str is None:
                logger.warning(
                    "Could not parse judge verdict for chunk_id=%d, raw=%r",
                    chunk_id, raw,
                )
                verdict_str = "not_supported"  # conservative default

            verdicts.append(FaithfulnessVerdict(
                answer_id=answer.answer_id,
                claim_text=segment.text[:200],
                chunk_id=chunk_id,
                verdict=verdict_str,  # type: ignore[arg-type]
            ))

            # Rate limiting: Gemini free tier ~15 RPM — add small delay between calls
            import asyncio as _asyncio
            await _asyncio.sleep(4)

    return verdicts


def compute_citation_correctness(verdicts: list[FaithfulnessVerdict]) -> float:
    """Fraction of (claim, chunk) pairs the LLM judged as 'supported'.

    Returns 0.0 for empty input (no verdicts to evaluate).
    Emits a warning if rate < 0.8 (design.md threshold).
    """
    if not verdicts:
        return 0.0
    supported = sum(1 for v in verdicts if v.verdict == "supported")
    rate = supported / len(verdicts)
    if rate < 0.8:
        logger.warning(
            "Citation correctness rate %.2f is below 0.8 threshold "
            "(%d/%d supported) — manual spot-check recommended",
            rate, supported, len(verdicts),
        )
    return round(rate, 4)
