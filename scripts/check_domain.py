import asyncio, asyncpg

DB_URL = "postgresql://postgres:postgres@localhost:5432/platform"

async def main():
    conn = await asyncpg.connect(DB_URL, ssl=False)
    
    # 1. Check chunks for cs.stanford.edu
    r = await conn.fetch("""
        SELECT COUNT(*) as cnt FROM chunks 
        WHERE source_id IN (SELECT id FROM sources WHERE collection = 'cs.stanford.edu')
    """)
    print(f"Chunks for cs.stanford.edu: {r[0]['cnt']}")
    
    # 2. Check snapshots for cs.stanford.edu
    r2 = await conn.fetch("""
        SELECT COUNT(*) as cnt FROM website_snapshots 
        WHERE domain = 'cs.stanford.edu'
    """)
    print(f"Snapshots for cs.stanford.edu: {r2[0]['cnt']}")
    
    # 3. Check if cs.stanford.edu has any sources
    r3 = await conn.fetch("""
        SELECT id, title, collection FROM sources 
        WHERE collection LIKE '%stanford%'
        LIMIT 5
    """)
    print(f"Sources with 'stanford' in collection: {len(r3)}")
    for row in r3:
        print(f"  id={row['id']}, collection={row['collection']}, title={row['title'][:80]}")
    
    # 4. Check all domains in website_snapshots
    r4 = await conn.fetch("""
        SELECT domain, COUNT(*) as cnt FROM website_snapshots 
        GROUP BY domain ORDER BY cnt DESC LIMIT 10
    """)
    print("\nTop domains in website_snapshots:")
    for row in r4:
        print(f"  {row['domain']}: {row['cnt']} snapshots")
    
    # 5. Check how domain filter is used in retrieval
    r5 = await conn.fetch("""
        SELECT COUNT(*) as cnt FROM chunks WHERE text ILIKE '%cs.stanford.edu%'
    """)
    print(f"\nChunks containing 'cs.stanford.edu' in text: {r5[0]['cnt']}")
    
    await conn.close()

asyncio.run(main())
