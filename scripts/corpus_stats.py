import asyncio, asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/platform', ssl=False)
    chunks = await conn.fetchval('SELECT COUNT(*) FROM chunks')
    src_total = await conn.fetchval('SELECT COUNT(*) FROM sources')
    by_collection = await conn.fetch(
        "SELECT COALESCE(collection, 'none') as col, COUNT(*) as cnt "
        "FROM sources GROUP BY col ORDER BY cnt DESC LIMIT 15"
    )
    by_type = await conn.fetch(
        "SELECT source_type, COUNT(*) as cnt FROM sources GROUP BY source_type ORDER BY cnt DESC"
    )
    ingested = await conn.fetchval('SELECT COUNT(DISTINCT source_id) FROM chunks')
    await conn.close()
    print(f"Sources: {src_total}")
    print(f"Chunks: {chunks}")
    print(f"Sources with chunks: {ingested}")
    print(f"\nBy type:")
    for r in by_type:
        print(f"  {r['source_type']}: {r['cnt']}")
    print(f"\nBy collection:")
    for r in by_collection:
        print(f"  {r['col']}: {r['cnt']}")

asyncio.run(main())
