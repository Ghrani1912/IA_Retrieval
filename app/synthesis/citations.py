"""Citation persistence.

Writes evidence_citations rows to Postgres after answer synthesis.
Validates confidence_label against allowed values before insert.
Ensures at least one citation exists for every non-UNKNOWN segment.
"""
from __future__ import annotations

import logging

import asyncpg

from app.config import settings
from app.models.pydantic_models import AnswerResponse

logger = logging.getLogger(__name__)

VALID_LABELS = {"directly_verified", "inferred", "unknown"}

DB_URL_SYNC = settings.database_url.replace("postgresql+asyncpg", "postgresql")


async def persist_citations(answer: AnswerResponse) -> None:
    """Insert evidence_citations rows for every answer segment.

    Args:
        answer: Completed AnswerResponse with segments and chunk_ids.

    Raises:
        ValueError: if a confidence_label value is not in VALID_LABELS.
    """
    conn = await asyncpg.connect(DB_URL_SYNC, ssl=False)
    try:
        for seg in answer.answer_segments:
            label = seg.citation_type.lower()
            if label not in VALID_LABELS:
                raise ValueError(
                    f"Invalid confidence_label {seg.citation_type!r} — "
                    f"must be one of {sorted(VALID_LABELS)}"
                )

            # Non-UNKNOWN segments must have at least one chunk_id
            if label != "unknown" and not seg.chunk_ids:
                logger.warning(
                    "Non-UNKNOWN segment has no chunk_ids for answer %s — skipping citation row",
                    answer.answer_id,
                )
                continue

            for chunk_id in seg.chunk_ids:
                await conn.execute(
                    """
                    INSERT INTO evidence_citations (answer_id, chunk_id, confidence_label)
                    VALUES ($1, $2, $3)
                    ON CONFLICT DO NOTHING
                    """,
                    answer.answer_id,
                    chunk_id,
                    label,
                )

        logger.info(
            "Persisted citations for answer %s (%d segments)",
            answer.answer_id,
            len(answer.answer_segments),
        )
    finally:
        await conn.close()
