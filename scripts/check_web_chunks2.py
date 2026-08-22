"""Check website chunks in DB, OpenSearch, and test the on-demand pipeline."""
import asyncio
import asyncpg
import json
import urllib.request
from app.config import settings

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")


async def main():
    conn = await asyncpg.connect(DB_URL, ssl=False)

    # 1. Website chunks in DB
    rows = await conn.fetch("""
        SELECT c.id, LEFT(c.text, 80) as preview, s.ia_identifier, s.source_type
        FROM chunks c
        JOIN sources s ON c.source_id = s.id
        WHERE s.source_type = 'website'
        ORDER BY c.id
    """)
    print(f"=== Website chunks in DB: {len(rows)} ===")
    for r in rows:
        print(f"  id={r['id']} src={r['ia_identifier']} type={r['source_type']} text={r['preview'][:60]}...")

    # 2. Website sources
    sources = await conn.fetch("""
        SELECT s.id, s.ia_identifier, s.title, s.source_type,
               (SELECT COUNT(*) FROM chunks WHERE source_id = s.id) as chunk_count
        FROM sources s WHERE s.source_type = 'website'
    """)
    print(f"\n=== Website sources: {len(sources)} ===")
    for s in sources:
        print(f"  id={s['id']} identifier={s['ia_identifier']} chunks={s['chunk_count']}")

    # 3. Website snapshots (CDX data)
    snaps = await conn.fetch("""
        SELECT domain, COUNT(*) as cnt, MIN(snapshot_timestamp) as earliest, MAX(snapshot_timestamp) as latest
        FROM website_snapshots
        GROUP BY domain
    """)
    print(f"\n=== Website snapshot domains: {len(snaps)} ===")
    for s in snaps:
        print(f"  {s['domain']}: {s['cnt']} snapshots ({s['earliest']} → {s['latest']})")

    # 4. Check fetched_flag status for cs.stanford.edu
    fetched = await conn.fetch("""
        SELECT fetched_flag, COUNT(*) as cnt
        FROM website_snapshots
        WHERE domain = 'cs.stanford.edu'
        GROUP BY fetched_flag
    """)
    print(f"\n=== cs.stanford.edu fetched_flag ===")
    for f in fetched:
        print(f"  fetched_flag={f['fetched_flag']}: {f['cnt']} snapshots")

    await conn.close()


asyncio.run(main())
