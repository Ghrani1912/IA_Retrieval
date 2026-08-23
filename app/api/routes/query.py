"""POST /query — end-to-end retrieval + synthesis endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.exceptions import AnswerParseError
from app.models.pydantic_models import AnswerResponse, StructuredQuery
from app.retrieval.query_understanding import understand_query
from app.retrieval.retrieve import retrieve_bm25, retrieve_vector, hydrate_chunks
from app.retrieval.rrf import fuse_rrf
from app.retrieval.reranker import rerank_blended
from app.synthesis.synthesizer import synthesize_answer, synthesize_answer_stream

logger = logging.getLogger(__name__)
router = APIRouter()


async def _background_ingest(query: str) -> None:
    """Run on-demand ingestion in the background. Fire-and-forget."""
    try:
        from app.ingestion.ondemand import on_demand_ingest
        result = await on_demand_ingest(query=query, max_sources=5)
        logger.info(
            "[ON-DEMAND] Background ingestion complete for %r: %s",
            query[:60], result,
        )
    except Exception as exc:
        logger.error("[ON-DEMAND] Background ingestion failed for %r: %s", query[:60], exc)


class QueryFilters(BaseModel):
    date_range: dict[str, int] | None = None   # {"from": 1975, "to": 1995}
    source_type: str | None = None
    collection: str | None = None
    domain: str | None = None  # website domain filter (e.g. "cs.stanford.edu")


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    filters: QueryFilters = Field(default_factory=QueryFilters)


@router.post("/query", response_model=AnswerResponse, status_code=200)
async def post_query(body: QueryRequest) -> AnswerResponse:
    """Run the full retrieval + synthesis pipeline for a user query.

    Steps: query understanding → BM25 + vector retrieval → RRF → rerank → synthesize.
    """
    try:
        # Step 1: structured query understanding
        sq: StructuredQuery = await understand_query(body.query)

        # Apply explicit filters from request body (override LLM-extracted ones)
        if body.filters.date_range:
            sq.date_range_start = body.filters.date_range.get("from")
            sq.date_range_end = body.filters.date_range.get("to")
        if body.filters.source_type:
            sq.source_type_hint = body.filters.source_type
        if body.filters.domain:
            sq.domain = body.filters.domain

        # Step 1a: intercept Wayback metadata questions
        # If the user is asking about snapshot counts, dates, etc.,
        # answer directly from the snapshots table instead of retrieval.
        if sq.domain:
            try:
                from app.wayback.metadata_answer import try_answer_metadata_query
                metadata_answer = await try_answer_metadata_query(body.query, sq.domain)
                if metadata_answer:
                    from app.models.pydantic_models import AnswerSegment, AnswerResponse
                    import uuid as _uuid
                    return AnswerResponse(
                        answer_id=str(_uuid.uuid4()),
                        query=body.query,
                        answer_segments=[
                            AnswerSegment(
                                text=metadata_answer,
                                citation_type="DIRECTLY_VERIFIED",
                                source_ids=[sq.domain],
                            )
                        ],
                        retrieved_chunks=[],
                    )
            except Exception as meta_exc:
                logger.warning("Metadata answer failed for %s: %s -- continuing", sq.domain, meta_exc, exc_info=True)

        # Step 1b: on-demand web content fetch if domain filter present
        web_chunks = []
        if sq.domain:
            try:
                from app.wayback.ondemand import fetch_web_content_for_domain
                from app.models.pydantic_models import RankedChunk, SourceMetadata
                web_raw = await fetch_web_content_for_domain(sq.domain)
                for i, chunk in enumerate(web_raw):
                    rc = RankedChunk(
                        chunk=chunk,
                        rank=0,
                        score=0.0,
                        source_metadata=SourceMetadata(
                            ia_identifier=sq.domain,
                            title=f"Website: {sq.domain}",
                            collection=sq.domain,
                        ),
                    )
                    web_chunks.append(rc)
            except Exception as web_exc:
                logger.warning("On-demand web fetch failed for %s: %s -- continuing with document corpus only", sq.domain, web_exc, exc_info=True)

        logger.info("[STEP 2] Starting parallel retrieval")
        # Step 2: parallel retrieval
        import asyncio
        bm25_results, vector_results = await asyncio.gather(
            retrieve_bm25(sq),
            retrieve_vector(sq),
        )
        logger.info("[STEP 2] BM25=%d, vector=%d", len(bm25_results), len(vector_results))

        # Step 3: RRF fusion
        fused = fuse_rrf(bm25_results, vector_results)
        logger.info("[STEP 3] Fused=%d", len(fused))

        # Step 4: hydrate (fill chunk text from DB — vector results have no text)
        hydrated = await hydrate_chunks(list(fused))
        logger.info("[STEP 4] Hydrated=%d", len(hydrated))

        # Step 5: blend web chunks in front (high priority) + rerank
        all_evidence = web_chunks + hydrated
        ranked = rerank_blended(sq.raw_query, all_evidence, top_k=10, alpha=0.3)

        # When domain filter is active, guarantee web chunks appear in final output
        # even if the reranker scored them lower than document chunks.
        if web_chunks:
            web_chunk_ids = {c.chunk.id for c in web_chunks}
            ranked_ids = {r.chunk.id for r in ranked}
            missing_web = [c for c in web_chunks if c.chunk.id not in ranked_ids]
            if missing_web:
                # Remove lowest-ranked non-web chunks to make room
                non_web = [r for r in ranked if r.chunk.id not in web_chunk_ids]
                slots_needed = len(missing_web)
                keep = non_web[: len(non_web) - slots_needed]
                ranked = missing_web + keep
                for i, r in enumerate(ranked, 1):
                    r.rank = i

        # Step 5b: thin-result detection — trigger background on-demand ingestion
        unique_sources = len({r.chunk.source_id for r in ranked if r.chunk.source_id})
        if unique_sources < 3 and not sq.domain:
            try:
                from app.ingestion.ondemand import on_demand_ingest
                logger.info(
                    "[ON-DEMAND] Thin results (%d unique sources) for %r — triggering background ingestion",
                    unique_sources, body.query[:60],
                )
                asyncio.create_task(_background_ingest(body.query))
            except Exception as od_exc:
                logger.warning("Failed to trigger on-demand ingestion: %s", od_exc)

        # Step 6: synthesize
        answer = await synthesize_answer(sq.raw_query, ranked)
        return answer

    except AnswerParseError as exc:
        logger.error("Answer parse error: %s", exc)
        raise HTTPException(status_code=500, detail={
            "error": "synthesis_failed",
            "detail": str(exc),
        })
    except Exception as exc:
        logger.exception("Unexpected error in /query: %s", exc)
        raise HTTPException(status_code=500, detail={
            "error": "internal_error",
            "detail": str(exc),
        })


import json
import asyncio


@router.post("/query/stream", status_code=200)
async def post_query_stream(body: QueryRequest):
    """Streaming version of /query — returns SSE events.

    Events:
      event: status   {"text": "..."}
      event: token    {"text": "..."}     (raw LLM tokens)
      event: done     {"answer": {...}}    (final AnswerResponse JSON)
      event: error    {"detail": "..."}
    """
    try:
        # Step 1: structured query understanding
        sq: StructuredQuery = await understand_query(body.query)

        if body.filters.date_range:
            sq.date_range_start = body.filters.date_range.get("from")
            sq.date_range_end = body.filters.date_range.get("to")
        if body.filters.source_type:
            sq.source_type_hint = body.filters.source_type
        if body.filters.domain:
            sq.domain = body.filters.domain

        # Step 1a: intercept Wayback metadata questions
        if sq.domain:
            try:
                from app.wayback.metadata_answer import try_answer_metadata_query
                metadata_answer = await try_answer_metadata_query(body.query, sq.domain)
                if metadata_answer:
                    from app.models.pydantic_models import AnswerSegment, AnswerResponse
                    import uuid as _uuid
                    meta_response = AnswerResponse(
                        answer_id=str(_uuid.uuid4()),
                        query=body.query,
                        answer_segments=[
                            AnswerSegment(
                                text=metadata_answer,
                                citation_type="DIRECTLY_VERIFIED",
                                source_ids=[sq.domain],
                            )
                        ],
                        retrieved_chunks=[],
                    )
                    async def _meta_stream():
                        yield f"event: done\ndata: {json.dumps(meta_response.model_dump())}\n\n"
                    return StreamingResponse(_meta_stream(), media_type="text/event-stream")
            except Exception as meta_exc:
                logger.warning("Metadata answer failed for %s: %s -- continuing", sq.domain, meta_exc)

        # Step 1b: on-demand web content fetch if domain filter present
        web_chunks = []
        if sq.domain:
            from app.wayback.ondemand import fetch_web_content_for_domain
            from app.models.pydantic_models import RankedChunk, SourceMetadata
            web_raw = await fetch_web_content_for_domain(sq.domain)
            for i, chunk in enumerate(web_raw):
                web_chunks.append(RankedChunk(
                    chunk=chunk,
                    rank=0,
                    score=0.0,
                    source_metadata=SourceMetadata(
                        ia_identifier=sq.domain,
                        title=f"Website: {sq.domain}",
                        collection=sq.domain,
                    ),
                ))
            logger.info("On-demand fetch returned %d web chunks for %s", len(web_chunks), sq.domain)

        # Step 2: parallel retrieval (non-streaming — these are fast)
        bm25_results, vector_results = await asyncio.gather(
            retrieve_bm25(sq),
            retrieve_vector(sq),
        )

        # Step 3-5: RRF + hydrate + rerank (non-streaming)
        fused = fuse_rrf(bm25_results, vector_results)
        hydrated = await hydrate_chunks(list(fused))
        all_evidence = web_chunks + hydrated
        ranked = rerank_blended(sq.raw_query, all_evidence, top_k=10, alpha=0.3)

        # When domain filter is active, guarantee web chunks appear in final output
        if web_chunks:
            web_chunk_ids = {c.chunk.id for c in web_chunks}
            ranked_ids = {r.chunk.id for r in ranked}
            missing_web = [c for c in web_chunks if c.chunk.id not in ranked_ids]
            if missing_web:
                non_web = [r for r in ranked if r.chunk.id not in web_chunk_ids]
                keep = non_web[: len(non_web) - len(missing_web)]
                ranked = missing_web + keep
                for i, r in enumerate(ranked, 1):
                    r.rank = i

        # Step 5b: thin-result detection — trigger background on-demand ingestion
        unique_sources_stream = len({r.chunk.source_id for r in ranked if r.chunk.source_id})
        if unique_sources_stream < 3 and not sq.domain:
            try:
                logger.info(
                    "[ON-DEMAND] Thin results (%d unique sources) for %r — triggering background ingestion",
                    unique_sources_stream, body.query[:60],
                )
                asyncio.create_task(_background_ingest(body.query))
            except Exception as od_exc:
                logger.warning("Failed to trigger on-demand ingestion: %s", od_exc)

        # Step 6: streaming synthesis
        async def event_generator():
            # Notify user if background ingestion is happening
            if unique_sources_stream < 3 and not sq.domain:
                yield f"event: status\ndata: {json.dumps({'text': 'Finding additional sources from the Internet Archive...'})}\n\n"
            async for event in synthesize_answer_stream(sq.raw_query, ranked):
                etype = event["type"]
                if etype == "token":
                    data = json.dumps({"text": event.get("text", "")})
                elif etype == "status":
                    data = json.dumps({"text": event.get("text", "")})
                elif etype == "done":
                    # Frontend expects the AnswerResponse object directly
                    data = json.dumps(event.get("answer", {}))
                elif etype == "error":
                    data = json.dumps({"detail": event.get("detail", "Unknown error")})
                else:
                    data = json.dumps(event)
                yield f"event: {etype}\ndata: {data}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # disable nginx buffering
            },
        )

    except Exception as exc:
        logger.exception("Unexpected error in /query/stream: %s", exc)
        raise HTTPException(status_code=500, detail={
            "error": "internal_error",
            "detail": str(exc),
        })
