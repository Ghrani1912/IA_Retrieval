"""BGE cross-encoder reranker.

Re-scores the top-30 RRF-fused candidates against the original query.
Returns top 8-12 chunks sorted by reranker score.
Falls back to RRF order if reranker is unavailable or errors.

Truncation note: BGE-reranker-v2-m3 max_length is 512 tokens (~2000 chars).
Chunks from this corpus are 2354-4324 chars. The model silently truncates
to the first 512 tokens — so we pass up to MAX_RERANK_CHARS (2000) to give
it full capacity. We also strip obvious OCR page headers/noise lines so
those chars don't waste the model's limited context window.
"""
from __future__ import annotations

import logging
import re

from app.config import settings
from app.models.pydantic_models import RankedChunk

logger = logging.getLogger(__name__)

_reranker = None
TOP_K = 10  # default final top-K after reranking

# BGE-reranker-v2-m3 max_length=512 tokens ≈ 2000 characters.
# All chunks in this corpus are 2354-4324 chars, so we cap at 2000 to give
# the model its full 512-token context window rather than wasting it on
# content past what it would ever see.
MAX_RERANK_CHARS = 2000

# Pattern matching OCR cover-page / header noise lines:
# "[[PAGE:1]]", "AD-A022 584", all-caps short lines, date patterns
_HEADER_NOISE_RE = re.compile(
    r"(\[\[PAGE:\d+\]\]"            # page markers
    r"|AD[-\s]?[A-Z0-9]{6,}"        # DTIC report numbers
    r"|ERIC_ED\d+"                  # ERIC identifiers
    r"|^\s*[A-Z0-9\s\-]{2,40}\s*$"  # all-caps short lines
    r")",
    re.MULTILINE,
)


def _extract_reranker_window(text: str, max_chars: int = MAX_RERANK_CHARS) -> str:
    """Extract text for cross-encoder scoring.

    Strips OCR noise (page markers, DTIC/ERIC report headers, all-caps
    banner lines) and collapses double-spaces, then takes the first
    max_chars characters. The BGE-reranker-v2-m3 internally truncates to
    512 tokens (~2000 chars), so the first ~500 tokens of this window are
    what the model actually sees.

    Old heuristic (find first "content line") was counterproductive:
    it could skip to a title/reference line, wasting the budget on
    a small portion of the chunk instead of giving the model broad
    context to score relevance.
    """
    if not text:
        return ""

    cleaned = _HEADER_NOISE_RE.sub(" ", text)
    cleaned = re.sub(r"  +", " ", cleaned).strip()

    return cleaned[:max_chars]


def get_reranker():
    """Load BGE reranker once (module-level singleton)."""
    global _reranker
    if _reranker is None:
        try:
            from FlagEmbedding import FlagReranker
            _reranker = FlagReranker(settings.reranker_model, use_fp16=True)
            logger.info("BGE reranker loaded: %s", settings.reranker_model)
        except Exception:
            logger.warning("Could not load reranker — will use RRF fallback", exc_info=True)
            _reranker = None
    return _reranker


def _assign_rrf_fallback(candidates: list[RankedChunk], top_k: int) -> list[RankedChunk]:
    """Return top_k candidates in existing RRF order, with rank reassigned.

    NOTE: mutates `.rank` on the RankedChunk objects in place (they are
    shared with the caller's original `candidates` list).
    """
    top = candidates[:top_k]
    for i, c in enumerate(top, start=1):
        c.rank = i
    return top


def _score_with_reranker(
    reranker,
    query: str,
    candidates: list[RankedChunk],
) -> list[float] | None:
    """Compute cross-encoder scores for each candidate. Returns None on failure."""
    try:
        pairs = [[query, _extract_reranker_window(c.chunk.text)] for c in candidates]
        scores = reranker.compute_score(pairs, normalize=True)
        # compute_score returns a bare numpy.float64 for 1 pair — normalize to list
        if isinstance(scores, (float, int)):
            scores = [scores]
        return scores
    except Exception:
        logger.warning("Reranker scoring failed — falling back to RRF order", exc_info=True)
        return None


def rerank(
    query: str,
    candidates: list[RankedChunk],
    top_k: int = TOP_K,
) -> list[RankedChunk]:
    """Re-score candidates with BGE cross-encoder and return top_k.

    Args:
        query: Original user query string.
        candidates: RRF-fused candidates (up to 30).
        top_k: Number of final results to return (8-12 recommended).

    Returns:
        Top top_k RankedChunk sorted by descending reranker score.
        Falls back to top_k from RRF order if reranker is unavailable
        or scoring fails.
    """
    if not candidates:
        return []

    reranker = get_reranker()
    if reranker is None:
        return _assign_rrf_fallback(candidates, top_k)

    scores = _score_with_reranker(reranker, query, candidates)
    if scores is None:
        return _assign_rrf_fallback(candidates, top_k)

    scored = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)

    result = []
    for new_rank, (score, item) in enumerate(scored[:top_k], start=1):
        item.rank = new_rank
        item.score = float(score)
        result.append(item)

    logger.debug("Reranked %d candidates → top %d", len(candidates), len(result))
    return result


def rerank_blended(
    query: str,
    candidates: list[RankedChunk],
    top_k: int = TOP_K,
    alpha: float = 0.3,
) -> list[RankedChunk]:
    """Blend RRF fusion scores with cross-encoder reranker scores.

    alpha=0.3 = RRF-heavy blend (DEFAULT — reranker needs strong signal
                to override RRF; prevents catastrophic failures on
                the worst queries while improving MRR on easier ones)
    alpha=1.0 = pure reranker (use explicit rerank() function instead)
    alpha=0.0 = pure RRF order (reranker has no effect)
    alpha=0.5 = equal blend
    """
    if not candidates:
        return []

    reranker = get_reranker()
    if reranker is None:
        return _assign_rrf_fallback(candidates, top_k)

    rerank_scores = _score_with_reranker(reranker, query, candidates)
    if rerank_scores is None:
        return _assign_rrf_fallback(candidates, top_k)

    rrf_scores = [c.score for c in candidates]
    max_rrf = max(rrf_scores) if rrf_scores else 1.0
    norm_rrf = [s / max_rrf for s in rrf_scores]

    blended = [
        (alpha * rerank_scores[i] + (1 - alpha) * norm_rrf[i], c)
        for i, c in enumerate(candidates)
    ]
    blended.sort(key=lambda x: x[0], reverse=True)

    result = []
    for new_rank, (score, item) in enumerate(blended[:top_k], start=1):
        item.rank = new_rank
        item.score = float(score)
        result.append(item)

    logger.debug(
        "Blended rerank (alpha=%.2f) %d candidates → top %d", alpha, len(candidates), len(result)
    )
    return result