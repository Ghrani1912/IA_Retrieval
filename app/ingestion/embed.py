"""BGE-M3 embedding generation.

Loads the model once (module-level singleton) — not per-call.
BGE-M3 is ~2GB; reloading it per chunk would make ingestion unusably slow.

MVP: dense_vecs only (1024-dim).
Phase 2 upgrade: add sparse + ColBERT multi-vector for hybrid sparse retrieval.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from app.config import settings
from app.models.pydantic_models import Chunk, ChunkWithEmbedding

if TYPE_CHECKING:
    from FlagEmbedding import BGEM3FlagModel as _ModelType

logger = logging.getLogger(__name__)

_model: "_ModelType | None" = None


def get_model() -> "_ModelType":
    """Load BGE-M3 on first call, reuse thereafter (module-level singleton)."""
    global _model
    if _model is None:
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError:
            raise ImportError(
                "FlagEmbedding is not installed. Run: pip install FlagEmbedding"
            )
        logger.info(
            "Loading BGE-M3 model %r — this takes ~30–60s on first load",
            settings.embedding_model,
        )
        _model = BGEM3FlagModel(
            settings.embedding_model,
            use_fp16=False,     # fp16 causes dtype error with transformers 4.44.x on CPU
        )
        logger.info("BGE-M3 model loaded")
    return _model


def embed_chunks(
    chunks: list[Chunk],
    batch_size: int = 32,
) -> list[ChunkWithEmbedding]:
    """Generate BGE-M3 dense embeddings for a list of chunks.

    Args:
        chunks: Chunk objects to embed.
        batch_size: Texts per forward pass (32 is safe for 8GB RAM with fp16).

    Returns:
        ChunkWithEmbedding list, one per input chunk.
    """
    if not chunks:
        return []

    model = get_model()
    texts = [c.text for c in chunks]

    logger.info("Embedding %d chunks (batch_size=%d)...", len(texts), batch_size)

    output = model.encode(
        texts,
        batch_size=batch_size,
        max_length=512,         # BGE-M3 supports up to 8192 but 512 is fast + sufficient
        return_dense=True,
        return_sparse=False,    # MVP: dense only
        return_colbert_vecs=False,
    )

    dense_vecs: np.ndarray = output["dense_vecs"]

    result: list[ChunkWithEmbedding] = []
    for chunk, vec in zip(chunks, dense_vecs):
        result.append(
            ChunkWithEmbedding(
                **chunk.model_dump(),
                embedding=vec.tolist(),
            )
        )

    logger.info("Embedding complete — %d vectors, dim=%d", len(result), len(dense_vecs[0]))
    return result
