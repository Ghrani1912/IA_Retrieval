import asyncio, asyncpg, json
from app.config import settings

db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql")

async def main():
    conn = await asyncpg.connect(db_url)
    
    # Check if landonorris.com chunks are in Postgres
    rows = await conn.fetch(
        "SELECT id, source_id, LEFT(text, 80) as preview FROM chunks "
        "WHERE source_id IN (SELECT id FROM sources WHERE ia_identifier = 'landonorris.com') "
        "LIMIT 5"
    )
    print("=== Postgres chunks for landonorris.com ===")
    for r in rows:
        print(f"  id={r['id']} source={r['source_id']} preview={r['preview']}")
    print(f"  Total: {len(rows)} shown")
    
    # Count total
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM chunks "
        "WHERE source_id IN (SELECT id FROM sources WHERE ia_identifier = 'landonorris.com')"
    )
    print(f"  Total chunks: {count}")
    
    # Check website_snapshots for timestamp distribution
    snapshots = await conn.fetch(
        "SELECT EXTRACT(YEAR FROM snapshot_timestamp)::int as year, COUNT(*) as cnt "
        "FROM website_snapshots WHERE domain = 'landonorris.com' "
        "GROUP BY year ORDER BY year"
    )
    print("\n=== Snapshots by year for landonorris.com ===")
    for s in snapshots:
        print(f"  {s['year']}: {s['cnt']} snapshots")
    
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM website_snapshots WHERE domain = 'landonorris.com'"
    )
    print(f"  Total: {total}")
    
    await conn.close()

asyncio.run(main())
