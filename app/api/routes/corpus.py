"""GET /corpus/stats — live corpus statistics for the UI.

GET /corpus/evolution/{domain} — LLM-powered website evolution analysis.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

import asyncpg
import httpx
from fastapi import APIRouter, HTTPException

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


@router.get("/corpus/stats")
async def corpus_stats():
    """Return live counts of sources and chunks in the database."""
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        total_sources = await conn.fetchval("SELECT COUNT(*) FROM sources")
        total_chunks = await conn.fetchval("SELECT COUNT(*) FROM chunks")
        sources_with_chunks = await conn.fetchval(
            "SELECT COUNT(DISTINCT source_id) FROM chunks WHERE source_id IS NOT NULL"
        )
        by_collection = await conn.fetch(
            """
            SELECT
                COALESCE(collection, 'other') AS collection,
                COUNT(DISTINCT s.id) AS sources,
                COUNT(c.id) AS chunks
            FROM sources s
            LEFT JOIN chunks c ON c.source_id = s.id
            GROUP BY collection
            HAVING COUNT(c.id) > 0
            ORDER BY chunks DESC
            """
        )
    finally:
        await conn.close()

    collections = [
        {"name": r["collection"], "sources": r["sources"], "chunks": r["chunks"]}
        for r in by_collection
    ]

    return {
        "total_sources": total_sources,
        "sources_with_chunks": sources_with_chunks,
        "total_chunks": total_chunks,
        "collections": collections,
    }


# ---------------------------------------------------------------------------
# Website Evolution Analysis
# ---------------------------------------------------------------------------

Evolution_SYSTEM_PROMPT = """You are a historical web analyst. Given a website domain and sample content
from different time periods (Wayback Machine snapshots), provide a concise
analysis of how the website's content and focus evolved over time.

Return ONLY valid JSON with this exact schema:
{
  "summary": "2-3 sentence overview of the website's evolution",
  "eras": [
    {
      "period": "e.g. 1996-2000",
      "focus": "What the website focused on during this era",
      "key_changes": ["Notable change 1", "Notable change 2"]
    }
  ],
  "key_topics": ["topic1", "topic2", "topic3"],
  "trend": "growing" | "shrinking" | "stable" | "shifted"
}

Rules:
- Identify 2-4 distinct eras based on content changes
- Keep each era description to 1-2 sentences
- Identify 3-5 key topics that appeared across the snapshots
- Trend should reflect overall trajectory (more content = growing, less = shrinking, etc.)
- Be factual — only describe what's in the provided content
"""


async def _background_ingest_for_evolution(domain: str) -> None:
    """Background task: ingest website content for evolution analysis."""
    try:
        from app.wayback.ondemand import fetch_web_content_for_domain
        logger.info("[EVOLUTION] Starting background ingestion for %s", domain)
        chunks = await fetch_web_content_for_domain(domain)
        logger.info("[EVOLUTION] Background ingestion complete for %s: %d chunks", domain, len(chunks))
    except Exception as exc:
        logger.error("[EVOLUTION] Background ingestion failed for %s: %s", domain, exc)


CDX_ANALYSIS_PROMPT = """You are a historical web analyst. Given a website domain and metadata about its Wayback Machine snapshots (years active, capture counts per year, peak year), provide an insightful analysis of what this website likely represented and how its archival history reflects broader trends.

Domain: {domain}
Snapshot range: {year_start} to {year_end}
Total snapshots: {total_count}
Peak year: {peak_year} ({peak_count} captures)
Year distribution: {year_dist}

Return ONLY valid JSON:
{{
  "summary": "2-3 sentences about what this website likely was and its archival significance",
  "eras": [
    {{
      "period": "e.g. 1996-2000",
      "focus": "What the website likely focused on during this era, based on historical context",
      "key_changes": ["Historically-informed change 1", "change 2"]
    }}
  ],
  "key_topics": ["topic1", "topic2", "topic3"],
  "historical_context": "1-2 sentences about what was happening in computing/AI/web during the peak period",
  "archival_notes": "Why this website matters in the history of the web"
}}

Rules:
- Use the domain name and year range to infer what the website was about
- Reference known historical events in computing/AI for context
- Identify 2-4 eras based on snapshot density changes
- Be specific about historical events (e.g. 'dot-com era', 'Web 2.0 transition')
- Keep it concise but insightful
"""


@router.get("/corpus/evolution/{domain}/cdx-analysis")
async def cdx_evolution_analysis(domain: str):
    """Use LLM to analyze CDX metadata and provide historical context."""
    import re
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        # Get year distribution
        year_rows = await conn.fetch(
            """
            SELECT EXTRACT(YEAR FROM snapshot_timestamp)::int AS year,
                   COUNT(*) AS cnt
            FROM website_snapshots
            WHERE domain = $1
            GROUP BY year ORDER BY year
            """,
            domain,
        )
        
        if not year_rows:
            raise HTTPException(status_code=404, detail="No snapshots found")
        
        by_year = {r["year"]: r["cnt"] for r in year_rows}
        years = sorted(by_year.keys())
        total = sum(by_year.values())
        peak_year = max(by_year, key=by_year.get)
        
        year_dist = ", ".join(f"{y}: {by_year[y]}" for y in years if by_year[y] >= max(by_year.values()) * 0.05)
        
        if not settings.llm_api_key:
            return {"error": "LLM not configured"}
        
        prompt = CDX_ANALYSIS_PROMPT.format(
            domain=domain,
            year_start=years[0],
            year_end=years[-1],
            total_count=total,
            peak_year=peak_year,
            peak_count=by_year[peak_year],
            year_dist=year_dist,
        )
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1500,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
            
            # Parse JSON - try to extract valid JSON from response
            import json
            analysis = None
            
            # Try direct parse first
            try:
                analysis = json.loads(content)
            except json.JSONDecodeError:
                pass
            
            # Try extracting JSON from markdown code blocks
            if analysis is None:
                try:
                    json_match = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', content, re.DOTALL)
                    if json_match:
                        analysis = json.loads(json_match.group(1))
                except (json.JSONDecodeError, AttributeError):
                    pass
            
            # Try finding first { to last }
            if analysis is None:
                try:
                    start = content.find('{')
                    end = content.rfind('}')
                    if start >= 0 and end > start:
                        # Try to fix common issues: trailing commas, unquoted keys
                        json_str = content[start:end+1]
                        # Remove trailing commas before } or ]
                        json_str = re.sub(r',\s*([}}\]])', r'\1', json_str)
                        analysis = json.loads(json_str)
                except json.JSONDecodeError:
                    pass
            
            # If all parsing fails, generate a basic analysis from the prompt data
            if analysis is None:
                analysis = {
                    "summary": f"LLM analysis of {domain} Wayback Machine snapshots. The website has been archived across {len(years)} years with peak activity in {peak_year}.",
                    "eras": [],
                    "key_topics": ["web archival", "internet history", domain],
                    "historical_context": f"The peak archival activity in {peak_year} ({by_year[peak_year]} captures) suggests significant web presence during this period.",
                    "archival_notes": f"This domain has {total} Wayback Machine snapshots spanning {years[0]} to {years[-1]}, making it a well-documented historical website."
                }
            analysis["domain"] = domain
            analysis["snapshot_years"] = years
            analysis["chunks_per_year"] = {str(y): by_year[y] for y in years}
            analysis["total_snapshots"] = total
            analysis["peak_year"] = peak_year
            return analysis
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("CDX analysis failed for %s: %s", domain, exc)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        await conn.close()


@router.get("/corpus/evolution/{domain:path}")
async def website_evolution(domain: str):
    """Analyze how a website's content evolved across Wayback snapshots.

    Fetches chunks from different time periods for the domain,
    then uses the LLM to synthesize an evolution summary.
    
    If no indexed chunks exist, triggers on-demand ingestion first.
    """
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        # Get chunks grouped by capture year
        rows = await conn.fetch(
            """
            SELECT c.text, c.capture_timestamp,
                   EXTRACT(YEAR FROM c.capture_timestamp)::int AS year
            FROM chunks c
            JOIN sources s ON c.source_id = s.id
            WHERE s.ia_identifier = $1
              AND c.capture_timestamp IS NOT NULL
              AND c.text IS NOT NULL
              AND LENGTH(c.text) > 100
            ORDER BY c.capture_timestamp
            """,
            domain,
        )

        if not rows:
            # No indexed chunks — check if domain has CDX snapshots at all
            snapshot_count = await conn.fetchval(
                "SELECT COUNT(*) FROM website_snapshots WHERE domain = $1",
                domain,
            )
            if snapshot_count == 0:
                raise HTTPException(status_code=404, detail={
                    "error": "no_snapshots",
                    "detail": f"No Wayback snapshots found for domain: {domain}",
                })

            # Domain has CDX metadata but no indexed content chunks.
            # Trigger background ingestion in the background
            import asyncio
            asyncio.create_task(_background_ingest_for_evolution(domain))

            # Get detailed year distribution from CDX metadata
            year_rows = await conn.fetch(
                """
                SELECT EXTRACT(YEAR FROM snapshot_timestamp)::int AS year,
                       COUNT(*) AS cnt
                FROM website_snapshots
                WHERE domain = $1
                GROUP BY year ORDER BY year
                """,
                domain,
            )
            by_year_meta = {r["year"]: r["cnt"] for r in year_rows}
            years = sorted(by_year_meta.keys())

            # Compute trend from CDX data
            if len(years) >= 3:
                mid = len(years) // 2
                first_half = sum(by_year_meta[y] for y in years[:mid])
                second_half = sum(by_year_meta[y] for y in years[mid:])
                if second_half > first_half * 1.5:
                    trend = "growing"
                elif first_half > second_half * 1.5:
                    trend = "shrinking"
                elif max(by_year_meta.values()) > min(by_year_meta.values()) * 3:
                    trend = "shifted"
                else:
                    trend = "stable"
            else:
                trend = "stable"

            # Identify peak year
            peak_year = max(by_year_meta, key=by_year_meta.get) if by_year_meta else None

            return {
                "domain": domain,
                "summary": (
                    f"{domain} has {snapshot_count} archived snapshots spanning "
                    f"{years[0]} to {years[-1]}. Peak activity was in {peak_year} "
                    f"with {by_year_meta[peak_year]} captures. Content ingestion is "
                    f"in progress -- more detailed analysis will be available shortly."
                ),
                "eras": [
                    {
                        "period": str(y),
                        "focus": f"{by_year_meta[y]} archived snapshots" + (" (peak year)" if y == peak_year else ""),
                        "key_changes": ["CDX metadata indexed"]
                    }
                    for y in years if by_year_meta[y] >= max(by_year_meta.values()) * 0.1
                ][:6],
                "key_topics": ["web archival", "snapshot history", domain],
                "trend": trend,
                "snapshot_years": years,
                "chunks_per_year": {str(y): by_year_meta[y] for y in years},
                "status": "ingesting",
                "snapshot_count": snapshot_count,
                "peak_year": peak_year,
                "year_span": f"{years[0]}-{years[-1]}",
                "can_llm_analyze": True,
            }

        # Group by year and sample content from each era
        by_year: dict[int, list[str]] = defaultdict(list)
        for row in rows:
            year = row["year"]
            text = row["text"][:500]  # First 500 chars per chunk
            by_year[year].append(text)

        # Sample: pick up to 2 representative chunks per year
        era_samples = []
        for year in sorted(by_year.keys()):
            chunks = by_year[year]
            # Take first and middle chunk for variety
            sample_indices = [0, len(chunks) // 2] if len(chunks) > 1 else [0]
            samples = [chunks[i] for i in sample_indices if i < len(chunks)]
            era_samples.append({
                "year": year,
                "chunk_count": len(chunks),
                "samples": samples,
            })

        # Build content for LLM
        content_parts = []
        for era in era_samples:
            content_parts.append(
                f"=== Year {era['year']} ({era['chunk_count']} chunks) ===\n"
                + "\n---\n".join(era["samples"])
            )
        content_text = "\n\n".join(content_parts)

        # Call LLM for evolution analysis
        if not settings.llm_api_key:
            # Fallback: generate a basic summary without LLM
            years = sorted(by_year.keys())
            return {
                "domain": domain,
                "summary": f"{domain} has {len(rows)} indexed chunks spanning {years[0]} to {years[-1]}.",
                "eras": [
                    {"period": f"{y}", "focus": f"Content from {y} ({len(by_year[y])} chunks)",
                     "key_changes": []}
                    for y in years[:5]
                ],
                "key_topics": [],
                "trend": "stable",
                "snapshot_years": years,
                "chunks_per_year": {str(y): len(by_year[y]) for y in years},
            }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "system", "content": Evolution_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Analyze the evolution of website: {domain}\n\nContent samples from different years:\n\n{content_text}"},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 800,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()

            # Parse JSON response
            import json
            # Try to extract JSON from response (might be wrapped in markdown)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            analysis = json.loads(content)

            # Add metadata
            analysis["domain"] = domain
            analysis["snapshot_years"] = sorted(by_year.keys())
            analysis["chunks_per_year"] = {str(y): len(by_year[y]) for y in sorted(by_year.keys())}

            return analysis

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Evolution analysis failed for %s: %s", domain, exc)
        raise HTTPException(status_code=500, detail={
            "error": "analysis_failed",
            "detail": str(exc),
        })
    finally:
        await conn.close()