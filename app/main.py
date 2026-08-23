"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import corpus, health, ingest, query, snapshots, sources

logging.basicConfig(
    level=logging.INFO,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "msg": "%(message)s"}',
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Historical Intelligence & RAG Platform",
    description=(
        "AI-powered historical information retrieval on Internet Archive. "
        "Indexes public-domain books, research papers, and government documents "
        "for hybrid BM25 + vector search with LLM-synthesized answers."
    ),
    version="0.1.0",
)

# CORS — allow the frontend dev server to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # fallback / Next.js
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(query.router, tags=["Query"])
app.include_router(sources.router, tags=["Sources"])
app.include_router(ingest.router, tags=["Ingestion"])
app.include_router(snapshots.router, tags=["Wayback"])
app.include_router(health.router, tags=["Health"])
app.include_router(corpus.router, tags=["Corpus"])


@app.on_event("startup")
async def prewarm_models() -> None:
    """Pre-warm BGE-M3 and reranker at startup to avoid 60s penalty on first request."""
    loop = asyncio.get_event_loop()
    logger.info("Pre-warming embedding model...")
    try:
        await loop.run_in_executor(None, _load_embedding_model)
        logger.info("Embedding model ready")
    except Exception as exc:
        logger.warning("Could not pre-warm embedding model: %s", exc)

    logger.info("Pre-warming reranker model...")
    try:
        await loop.run_in_executor(None, _load_reranker_model)
        logger.info("Reranker model ready")
    except Exception as exc:
        logger.warning("Could not pre-warm reranker model: %s", exc)


def _load_embedding_model() -> None:
    from app.ingestion.embed import get_model
    get_model()


def _load_reranker_model() -> None:
    from app.retrieval.reranker import get_reranker
    get_reranker()
