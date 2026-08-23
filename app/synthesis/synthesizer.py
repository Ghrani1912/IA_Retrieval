"""Answer synthesis with evidence-grounded citation labeling."""
from __future__ import annotations

import json
import logging
import re
import uuid

import httpx

from app.config import settings
from app.exceptions import AnswerParseError, SynthesisError
from app.ingestion.serializers import parse_answer
from app.models.pydantic_models import AnswerResponse, AnswerSegment, RankedChunk
from app.synthesis.citations import persist_citations

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a historical research assistant. Answer questions using ONLY
the provided evidence chunks. Do not draw on external knowledge.

STRUCTURE YOUR ANSWER AS MULTIPLE SEGMENTS:
- Break your answer into multiple answer_segments — one segment per distinct claim, fact, or idea.
- Each segment must be attributed to the specific source(s) that support it via source_ids.
- Do NOT compress evidence from multiple distinct sources into a single vague segment.
- When evidence spans several sources, produce multiple segments, each citing different source_ids.
- Aim for 3-5 segments when the evidence supports it. A single paragraph covering everything
  is too compressed — spread distinct claims across separate segments.
- If you only have one solid claim from one source, one segment is fine.

For each segment:
- Tag as DIRECTLY_VERIFIED if the claim is directly stated in a cited evidence chunk
- Tag as INFERRED if it synthesizes across multiple chunks without direct quotation
- Tag as UNKNOWN if the evidence does not support the claim

For website sources: always write "first archived" or "earliest snapshot date" —
never write "launched" or "went live".

Return valid JSON matching this schema exactly:
{"answer_segments": [{"text": "...", "citation_type": "DIRECTLY_VERIFIED|INFERRED|UNKNOWN", "source_ids": ["ia_identifier_string"], "chunk_ids": []}]}

Important: leave chunk_ids as an empty list []. Do not attempt to fill in chunk IDs."""

_LAUNCHED_PATTERN = re.compile(r"\b(launched|went live)\b", re.IGNORECASE)

# Maximum total evidence text sent to the LLM to avoid 413 payload errors.
# 10 chunks × ~2 000 chars each = ~20 000 chars before system-prompt overhead;
# cap at 12 000 to stay well within typical LLM request limits.
MAX_EVIDENCE_CHARS = 12_000


def _build_evidence_block(index: int, item: RankedChunk) -> str:
    meta = item.source_metadata
    ia_id = meta.ia_identifier if meta else "unknown"
    title = meta.title if meta and meta.title else ia_id
    author = meta.author if meta and meta.author else "unknown"
    date_label = "unknown date"

    if item.chunk.capture_timestamp:
        date_label = f"Archived on {item.chunk.capture_timestamp.date().isoformat()}"
    elif meta and meta.pub_date:
        date_label = meta.pub_date

    page = item.chunk.page_or_section or "n/a"
    return (
        f"[SOURCE {index}] Title: {title} | Author: {author} | Date: {date_label}\n"
        f"Identifier: {ia_id} | Page: {page}\n"
        f"---\n{item.chunk.text}"
    )


def _build_evidence_blocks(evidence: list[RankedChunk]) -> tuple[str, int, int]:
    """Build evidence text capped at MAX_EVIDENCE_CHARS to avoid LLM 413 errors.

    Returns:
        (evidence_text, blocks_actually_used, total_chars)
    """
    blocks: list[str] = []
    total_len = 0
    for i, item in enumerate(evidence):
        block = _build_evidence_block(i + 1, item)
        if total_len + len(block) > MAX_EVIDENCE_CHARS:
            logger.warning(
                "Evidence cap reached after %d/%d chunks (%d chars) — truncating to avoid 413",
                i, len(evidence), total_len,
            )
            break
        blocks.append(block)
        total_len += len(block)
    return "\n\n".join(blocks), len(blocks), total_len


def _flag_launched_warnings(
    answer: AnswerResponse,
    evidence: list[RankedChunk],
) -> AnswerResponse:
    """Set launched_warning on segments citing website sources that use 'launched'."""
    web_chunk_ids = {
        item.chunk.id
        for item in evidence
        if item.source_metadata
        and item.chunk.capture_timestamp is not None
    }
    if not web_chunk_ids:
        return answer

    for segment in answer.answer_segments:
        cites_web = any(cid in web_chunk_ids for cid in segment.chunk_ids)
        if cites_web and _LAUNCHED_PATTERN.search(segment.text):
            segment.launched_warning = True
            logger.warning(
                "Launched-language guardrail triggered in segment citing web chunks: %r",
                segment.text[:120],
            )
    return answer


async def synthesize_answer(query: str, evidence: list[RankedChunk]) -> AnswerResponse:
    """Synthesize an evidence-grounded answer from ranked chunks.

    Raises:
        AnswerParseError: if LLM output cannot be parsed.
    """
    answer_id = str(uuid.uuid4())
    if not evidence:
        return AnswerResponse(
            answer_id=answer_id,
            query=query,
            answer_segments=[
                AnswerSegment(
                    text="No evidence chunks were available to answer this question.",
                    citation_type="UNKNOWN",
                )
            ],
            retrieved_chunks=[],
        )

    evidence_blocks, blocks_actually_used, total_len = _build_evidence_blocks(evidence)
    user_prompt = (
        f"Question: {query}\n\n"
        f"Evidence:\n{evidence_blocks}\n\n"
        "Return JSON with answer_segments only."
    )

    if not settings.llm_api_key:
        logger.warning("No LLM API key configured — using fallback synthesis from evidence chunks")
        segments = []
        for item in evidence:
            cid = item.chunk.id
            ia_id = item.source_metadata.ia_identifier if item.source_metadata else "unknown"
            text_snippet = item.chunk.text[:200].replace("\n", " ").strip()
            segments.append(AnswerSegment(
                text=f"According to {ia_id} (p. {item.chunk.page_or_section or 'n/a'}): {text_snippet}",
                citation_type="DIRECTLY_VERIFIED",
                source_ids=[ia_id],
                chunk_ids=[cid] if cid is not None else [],
            ))
        fallback_answer = AnswerResponse(
            answer_id=answer_id,
            query=query,
            answer_segments=segments,
            retrieved_chunks=[item.chunk for item in evidence],
        )
        fallback_answer.compute_citation_distribution()
        fallback_answer = _flag_launched_warnings(fallback_answer, evidence)
        await persist_citations(fallback_answer)
        return fallback_answer

    import asyncio as _asyncio
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    json={
                        "model": settings.llm_model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 1500,
                    },
                )
                if response.status_code == 413:
                    logger.error(
                        "Groq 413 — sent %d/%d chunks (%d evidence chars). Groq response body: %s",
                        blocks_actually_used, len(evidence), total_len, response.text[:500],
                    )
                    raise SynthesisError(
                        "Evidence exceeds LLM payload limit — reduce top-K or chunk size"
                    )
                if response.status_code == 429:
                    wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
                    logger.warning("Synthesis rate limited (429) — waiting %ds (attempt %d/3)", wait, attempt + 1)
                    await _asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
                break
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < 2:
                wait = 10 * (2 ** attempt)
                logger.warning("Synthesis rate limited — waiting %ds", wait)
                await _asyncio.sleep(wait)
                continue
            raise
    else:
        logger.error("Synthesis failed after 3 retries due to rate limiting")
        raise AnswerParseError("LLM rate limited — try again later")

    logger.debug("LLM raw synthesis output: %s", raw[:500])

    try:
        answer = parse_answer(raw)
    except AnswerParseError:
        logger.error("Failed to parse LLM synthesis output: %s", raw[:1000])
        raise

    answer.answer_id = answer_id
    answer.query = query
    answer.retrieved_chunks = [item.chunk for item in evidence]

    # Compute citation distribution from segments
    answer.compute_citation_distribution()

    # Inject real chunk IDs from evidence into segments that cite matching source_ids.
    # LLMs reliably return source_ids (ia_identifier strings) but not numeric chunk IDs.
    source_to_chunks: dict[str, list[int]] = {}
    for item in evidence:
        ia_id = item.source_metadata.ia_identifier if item.source_metadata else None
        if ia_id and item.chunk.id is not None:
            source_to_chunks.setdefault(ia_id, []).append(item.chunk.id)

    for segment in answer.answer_segments:
        if not segment.chunk_ids:
            ids: list[int] = []
            for sid in segment.source_ids:
                ids.extend(source_to_chunks.get(sid, []))
            segment.chunk_ids = ids

    answer = _flag_launched_warnings(answer, evidence)

    await persist_citations(answer)
    return answer


async def synthesize_answer_stream(
    query: str,
    evidence: list[RankedChunk],
):
    """Streaming synthesis — yields SSE events as tokens arrive from Gemini.

    Yields dicts with a 'type' key:
      {"type": "status", "text": "..."}          — progress updates
      {"type": "token", "text": "..."}            — raw LLM tokens
      {"type": "done", "answer": {...}}             — final parsed AnswerResponse dict
      {"type": "error", "detail": "..."}          — error message

    The caller should accumulate token events and parse the final JSON
    once the 'done' event arrives.  This avoids the 20-25s blocking wait.
    """
    import asyncio as _asyncio
    import json as _json

    answer_id = str(uuid.uuid4())

    if not evidence:
        yield {"type": "status", "text": "No evidence chunks available"}
        yield {
            "type": "done",
            "answer": {
                "answer_id": answer_id,
                "query": query,
                "answer_segments": [{
                    "text": "No evidence chunks were available to answer this question.",
                    "citation_type": "UNKNOWN",
                    "source_ids": [],
                    "chunk_ids": [],
                }],
                "retrieved_chunks": [],
            },
        }
        return

    if not settings.llm_api_key:
        yield {"type": "status", "text": "No LLM key — building fallback answer"}
        segments = []
        for item in evidence:
            cid = item.chunk.id
            ia_id = item.source_metadata.ia_identifier if item.source_metadata else "unknown"
            text_snippet = item.chunk.text[:200].replace("\n", " ").strip()
            segments.append({
                "text": f"According to {ia_id} (p. {item.chunk.page_or_section or 'n/a'}): {text_snippet}",
                "citation_type": "DIRECTLY_VERIFIED",
                "source_ids": [ia_id],
                "chunk_ids": [cid] if cid is not None else [],
            })
        yield {
            "type": "done",
            "answer": {
                "answer_id": answer_id,
                "query": query,
                "answer_segments": segments,
                "retrieved_chunks": [],
            },
        }
        return

    # Build the prompt (same as synthesize_answer)
    evidence_blocks, blocks_actually_used, total_len = _build_evidence_blocks(evidence)
    user_prompt = (
        f"Question: {query}\n\n"
        f"Evidence:\n{evidence_blocks}\n\n"
        "Return JSON with answer_segments only."
    )

    yield {"type": "status", "text": "Sending to LLM..."}

    # Stream from Gemini with exponential backoff
    raw_buffer = ""
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    json={
                        "model": settings.llm_model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 1500,
                        "stream": True,
                    },
                ) as stream:
                    if stream.status_code == 413:
                        error_body = await stream.aread()
                        logger.error(
                            "Groq 413 — sent %d/%d chunks (%d evidence chars). Groq response body: %s",
                            blocks_actually_used, len(evidence), total_len, error_body.decode(errors="replace")[:500],
                        )
                        yield {"type": "error", "detail": "Evidence exceeds LLM payload limit — reduce top-K or chunk size"}
                        return
                    if stream.status_code == 429:
                        wait = 10 * (2 ** attempt)
                        yield {"type": "status", "text": f"Rate limited — waiting {wait}s..."}
                        await _asyncio.sleep(wait)
                        continue

                    async for line in stream.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]  # strip "data: "
                        if payload.strip() == "[DONE]":
                            break
                        try:
                            chunk = _json.loads(payload)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                raw_buffer += token
                                yield {"type": "token", "text": token}
                        except _json.JSONDecodeError:
                            pass
                    break  # success — exit retry loop
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < 2:
                wait = 10 * (2 ** attempt)
                yield {"type": "status", "text": f"Rate limited — retrying in {wait}s..."}
                await _asyncio.sleep(wait)
                continue
            yield {"type": "error", "detail": str(exc)}
            return
        except Exception as exc:
            yield {"type": "error", "detail": str(exc)}
            return
    else:
        yield {"type": "error", "detail": "Rate limited after 3 retries"}
        return

    yield {"type": "status", "text": "Parsing answer..."}

    # Parse the accumulated JSON
    try:
        answer = parse_answer(raw_buffer)
    except AnswerParseError as exc:
        yield {"type": "error", "detail": f"Parse error: {exc}"}
        return

    answer.answer_id = answer_id
    answer.query = query
    answer.retrieved_chunks = [item.chunk for item in evidence]

    # Compute citation distribution from segments
    answer.compute_citation_distribution()

    # Inject chunk IDs from evidence
    source_to_chunks: dict[str, list[int]] = {}
    for item in evidence:
        ia_id = item.source_metadata.ia_identifier if item.source_metadata else None
        if ia_id and item.chunk.id is not None:
            source_to_chunks.setdefault(ia_id, []).append(item.chunk.id)

    for segment in answer.answer_segments:
        if not segment.chunk_ids:
            ids: list[int] = []
            for sid in segment.source_ids:
                ids.extend(source_to_chunks.get(sid, []))
            segment.chunk_ids = ids

    answer = _flag_launched_warnings(answer, evidence)

    try:
        await persist_citations(answer)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to persist citations for answer %s — continuing anyway: %s",
            answer.answer_id, exc,
        )

    # Yield the final structured answer
    yield {
        "type": "done",
        "answer": answer.model_dump(mode="json"),
    }
