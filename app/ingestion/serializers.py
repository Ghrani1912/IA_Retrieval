"""Serializers for Chunk and AnswerResponse objects.

Provides round-trip safe serialize/deserialize for both types.
Raises typed exceptions on malformed input rather than generic errors.
"""
from __future__ import annotations

import datetime
import json

from app.exceptions import AnswerParseError, ChunkDeserializationError
from app.models.pydantic_models import AnswerResponse, AnswerSegment, Chunk


# -----------------------------------------------------------------------
# Chunk serializer
# -----------------------------------------------------------------------

def serialize_chunk(chunk: Chunk) -> dict:
    """Convert a Chunk to a JSON-serializable dict."""
    return {
        "id": chunk.id,
        "source_id": chunk.source_id,
        "text": chunk.text,
        "page_or_section": chunk.page_or_section,
        "embedding_id": chunk.embedding_id,
        "capture_timestamp": chunk.capture_timestamp.isoformat() if chunk.capture_timestamp else None,
        "char_range_start": chunk.char_range_start,
        "char_range_end": chunk.char_range_end,
        "token_count": chunk.token_count,
    }


def deserialize_chunk(data: dict) -> Chunk:
    """Reconstruct a Chunk from a serialized dict.

    Raises:
        ChunkDeserializationError: if a required field is missing or malformed.
    """
    required_int_fields = ("source_id", "char_range_start", "char_range_end")
    for field in required_int_fields:
        if field not in data:
            raise ChunkDeserializationError(field, f"required field '{field}' is missing")
        if not isinstance(data[field], (int, type(None))):
            try:
                data[field] = int(data[field])
            except (TypeError, ValueError):
                raise ChunkDeserializationError(
                    field, f"expected int, got {type(data[field]).__name__!r}"
                )

    if "text" not in data:
        raise ChunkDeserializationError("text", "required field 'text' is missing")
    if not isinstance(data.get("text"), str):
        raise ChunkDeserializationError(
            "text", f"expected str, got {type(data.get('text')).__name__!r}"
        )

    capture_ts = None
    raw_ts = data.get("capture_timestamp")
    if raw_ts is not None:
        try:
            capture_ts = datetime.datetime.fromisoformat(raw_ts)
        except (ValueError, TypeError):
            raise ChunkDeserializationError(
                "capture_timestamp",
                f"cannot parse ISO datetime from {raw_ts!r}",
            )

    return Chunk(
        id=data.get("id"),
        source_id=data["source_id"],
        text=data["text"],
        page_or_section=data.get("page_or_section"),
        embedding_id=data.get("embedding_id"),
        capture_timestamp=capture_ts,
        char_range_start=data["char_range_start"],
        char_range_end=data["char_range_end"],
        token_count=data.get("token_count"),
    )


# -----------------------------------------------------------------------
# AnswerResponse serializer
# -----------------------------------------------------------------------

_VALID_CITATION_TYPES = {"DIRECTLY_VERIFIED", "INFERRED", "UNKNOWN"}


def _salvage_truncated_json(text: str) -> dict | None:
    """Try to salvage an AnswerResponse from truncated JSON.

    Finds all complete answer_segment objects and returns them.
    Returns None if no complete segments can be found.
    """
    import re
    # Find all complete segment objects: {"text": "...", "citation_type": "...", ...}
    # Look for text up to the last complete segment closing brace
    segments = []
    # Try progressively shorter truncations to find valid JSON
    for end in range(len(text), max(len(text) - 500, 0), -1):
        candidate = text[:end]
        # Try appending closing brackets to complete the JSON
        for suffix in [']}', '}\n]}', '}]}\n```', '}]}']:
            try:
                data = json.loads(candidate + suffix)
                if isinstance(data, dict) and "answer_segments" in data:
                    return data
            except (json.JSONDecodeError, ValueError):
                pass
    return None


def format_answer(answer: AnswerResponse) -> str:
    """Serialize an AnswerResponse to a JSON string."""
    payload = {
        "answer_id": answer.answer_id,
        "query": answer.query,
        "answer_segments": [
            {
                "text": seg.text,
                "citation_type": seg.citation_type,
                "source_ids": seg.source_ids,
                "chunk_ids": seg.chunk_ids,
            }
            for seg in answer.answer_segments
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_answer(raw: str) -> AnswerResponse:
    """Parse a JSON string into an AnswerResponse.

    Handles markdown code fences that some LLMs (e.g. Gemini) wrap JSON in:
        ```json { ... } ```  or  ``` { ... } ```

    Raises:
        AnswerParseError: if the JSON is malformed or the schema is invalid.
    """
    # Strip markdown code fences before parsing
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # Remove opening fence (```json or ```)
        lines = lines[1:] if lines[0].startswith("```") else lines
        # Remove closing fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        # Gemini may truncate mid-JSON if max_tokens is hit.
        # Try to salvage completed answer_segments by finding the last complete object.
        salvaged = _salvage_truncated_json(stripped)
        if salvaged is not None:
            data = salvaged
        else:
            raise AnswerParseError(f"invalid JSON: {exc}", raw=raw)

    if not isinstance(data, dict):
        raise AnswerParseError("expected a JSON object at top level", raw=raw)

    answer_id = data.get("answer_id", "")
    query = data.get("query", "")

    raw_segments = data.get("answer_segments", [])
    if not isinstance(raw_segments, list):
        raise AnswerParseError("'answer_segments' must be a list", raw=raw)

    segments: list[AnswerSegment] = []
    for i, seg in enumerate(raw_segments):
        if not isinstance(seg, dict):
            raise AnswerParseError(f"answer_segments[{i}] must be an object", raw=raw)

        citation_type = seg.get("citation_type", "")
        if citation_type not in _VALID_CITATION_TYPES:
            raise AnswerParseError(
                f"answer_segments[{i}].citation_type={citation_type!r} is not one of "
                f"{sorted(_VALID_CITATION_TYPES)}",
                raw=raw,
            )

        segments.append(AnswerSegment(
            text=seg.get("text", ""),
            citation_type=citation_type,
            source_ids=seg.get("source_ids", []),
            chunk_ids=seg.get("chunk_ids", []),
            launched_warning=bool(seg.get("launched_warning", False)),
        ))

    return AnswerResponse(
        answer_id=answer_id,
        query=query,
        answer_segments=segments,
        retrieved_chunks=[],
    )
