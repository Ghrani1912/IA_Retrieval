"""GET /sources and GET /sources/{ia_identifier} — source browsing endpoints."""
from __future__ import annotations

import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


class SourceSummary(BaseModel):
    id: int
    ia_identifier: str
    source_type: str
    title: str | None
    author: str | None
    pub_date: str | None
    year: int | None = None
    collection: str | None = None
    ia_url: str | None
    chunk_count: int


class SourceDetail(BaseModel):
    id: int
    ia_identifier: str
    source_type: str
    title: str | None
    author: str | None
    publisher: str | None
    pub_date: str | None
    year: int | None = None
    language: str | None
    subject: list[str]
    collection: str | None
    ia_url: str | None
    is_open_access: bool
    chunk_count: int


class SourceListResponse(BaseModel):
    items: list[SourceSummary]
    total: int
    page: int
    page_size: int


@router.get("/sources", response_model=SourceListResponse)
async def list_sources(
    source_type: str | None = Query(None),
    collection: str | None = Query(None),
    date_from: int | None = Query(None, description="Year (e.g. 1975)"),
    date_to: int | None = Query(None, description="Year (e.g. 1990)"),
    language: str | None = Query(None),
    q: str | None = Query(None, description="Search title, author, subject"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> SourceListResponse:
    """List sources with optional filtering and pagination."""
    # Map friendly frontend collection names to DB collection names
    COLLECTION_MAP: dict[str, list[str]] = {
        "DTIC": ["dticarchive", "defense-dept"],
        "DTIC (Defense)": ["dticarchive", "defense-dept"],
        "ERIC": ["ericarchive"],
        "ERIC (Education)": ["ericarchive"],
        "Americana": ["americana"],
    }

    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if source_type:
        conditions.append(f"s.source_type = ${idx}")
        params.append(source_type)
        idx += 1
    if collection:
        db_collections = COLLECTION_MAP.get(collection, [collection])
        placeholders = ", ".join(f"${idx + i}" for i in range(len(db_collections)))
        conditions.append(f"s.collection IN ({placeholders})")
        params.extend(db_collections)
        idx += len(db_collections)
    if date_from:
        conditions.append(f"CAST(LEFT(s.pub_date_raw, 4) AS INTEGER) >= ${idx}")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"CAST(LEFT(s.pub_date_raw, 4) AS INTEGER) <= ${idx}")
        params.append(date_to)
        idx += 1
    if language:
        conditions.append(f"s.language = ${idx}")
        params.append(language)
        idx += 1
    if q:
        conditions.append(f"(s.title ILIKE ${idx} OR s.author ILIKE ${idx} OR s.ia_identifier ILIKE ${idx})")
        params.append(f"%{q}%")
        idx += 1

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * page_size

    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM sources s {where}", *params
        )
        rows = await conn.fetch(
            f"""
            SELECT s.id, s.ia_identifier, s.source_type, s.title, s.author,
                   s.pub_date_raw, s.collection, s.ia_url,
                   COUNT(c.id) AS chunk_count
            FROM sources s
            LEFT JOIN chunks c ON c.source_id = s.id
            {where}
            GROUP BY s.id
            ORDER BY s.id
            LIMIT ${idx} OFFSET ${idx+1}
            """,
            *params, page_size, offset,
        )
    finally:
        await conn.close()

    def _parse_year(raw: str | None) -> int | None:
        if not raw:
            return None
        try:
            return int(raw[:4])
        except (ValueError, TypeError):
            return None

    items = [
        SourceSummary(
            id=r["id"],
            ia_identifier=r["ia_identifier"],
            source_type=r["source_type"],
            title=r["title"],
            author=r["author"],
            pub_date=r["pub_date_raw"],
            year=_parse_year(r["pub_date_raw"]),
            collection=r["collection"],
            ia_url=r["ia_url"],
            chunk_count=r["chunk_count"],
        )
        for r in rows
    ]
    return SourceListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/sources/{ia_identifier}", response_model=SourceDetail)
async def get_source(ia_identifier: str) -> SourceDetail:
    """Get full metadata for a single source by its Internet Archive identifier."""
    conn = await asyncpg.connect(DB_URL, ssl=False)
    try:
        row = await conn.fetchrow(
            """
            SELECT s.id, s.ia_identifier, s.source_type, s.title, s.author,
                   s.publisher, s.pub_date_raw, s.language, s.subject,
                   s.collection, s.ia_url, s.is_open_access,
                   COUNT(c.id) AS chunk_count
            FROM sources s
            LEFT JOIN chunks c ON c.source_id = s.id
            WHERE s.ia_identifier = $1
            GROUP BY s.id
            """,
            ia_identifier,
        )
    finally:
        await conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})

    pub_raw = row["pub_date_raw"]
    yr = None
    if pub_raw:
        try:
            yr = int(pub_raw[:4])
        except (ValueError, TypeError):
            pass

    return SourceDetail(
        id=row["id"],
        ia_identifier=row["ia_identifier"],
        source_type=row["source_type"],
        title=row["title"],
        author=row["author"],
        publisher=row["publisher"],
        pub_date=pub_raw,
        year=yr,
        language=row["language"],
        subject=list(row["subject"] or []),
        collection=row["collection"],
        ia_url=row["ia_url"],
        is_open_access=bool(row["is_open_access"]),
        chunk_count=row["chunk_count"],
    )
