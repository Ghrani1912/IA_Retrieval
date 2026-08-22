"""Test each step of on-demand pipeline individually."""
import asyncio, sys, io, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_URL = "postgresql://postgres:postgres@localhost:5432/platform"

async def main():
    # Step 1: Get snapshot
    print("Step 1: Get latest snapshot...")
    import asyncpg
    conn = await asyncpg.connect(DB_URL, ssl=False)
    row = await conn.fetchrow(
        "SELECT id, url, snapshot_timestamp, status_code "
        "FROM website_snapshots "
        "WHERE domain = $1 AND status_code >= 200 AND status_code < 400 "
        "ORDER BY snapshot_timestamp DESC LIMIT 1",
        "cs.stanford.edu"
    )
    await conn.close()
    print(f"  Snapshot: url={row['url']}, ts={row['snapshot_timestamp']}")
    
    # Step 2: Check fetched_flag
    print("\nStep 2: Check fetched_flag...")
    conn = await asyncpg.connect(DB_URL, ssl=False)
    flag_row = await conn.fetchrow(
        "SELECT fetched_flag FROM website_snapshots WHERE url = $1 AND snapshot_timestamp = $2",
        row['url'], row['snapshot_timestamp']
    )
    await conn.close()
    print(f"  fetched_flag = {flag_row['fetched_flag']}")
    
    if flag_row['fetched_flag']:
        print("  SKIPPING — already fetched")
        return
    
    # Step 3: Memento fetch
    print("\nStep 3: Memento fetch...")
    from app.wayback.memento import fetch_snapshot_content
    content = await fetch_snapshot_content(row['url'], row['snapshot_timestamp'], db_url=DB_URL)
    print(f"  Content: {len(content) if content else 0} chars")
    if content:
        print(f"  Preview: {content[:200]}")
    
    if not content:
        print("  FAILED — no content")
        return
    
    # Step 4: Clean
    print("\nStep 4: Clean...")
    from app.ingestion.cleaner import clean_text
    cleaned = clean_text(content)
    print(f"  Cleaned: {len(cleaned.text)} chars")
    
    # Step 5: Chunk
    print("\nStep 5: Chunk...")
    from app.ingestion.chunker import chunk_text
    chunks = chunk_text(cleaned, source_id=1)
    print(f"  Chunks: {len(chunks)}")
    for i, c in enumerate(chunks):
        print(f"    [{i}] tokens={c.token_count}, text_len={len(c.text)}")
    
    if not chunks:
        print("  FAILED — no chunks")
        return
    
    # Step 6: Embed
    print("\nStep 6: Embed...")
    from app.ingestion.embed import embed_chunks
    try:
        embedded = embed_chunks(chunks)
        print(f"  Embedded: {len(embedded)} chunks, dim={len(embedded[0].embedding)}")
    except Exception as e:
        print(f"  EMBED ERROR: {e}")
        traceback.print_exc()
        return
    
    print("\nAll steps passed!")

asyncio.run(main())
