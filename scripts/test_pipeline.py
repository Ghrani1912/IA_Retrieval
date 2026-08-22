"""Test the full on-demand pipeline step by step."""
import asyncio, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_URL = "postgresql://postgres:postgres@localhost:5432/platform"

async def main():
    from datetime import datetime, timezone
    from app.wayback.memento import fetch_snapshot_content
    from app.ingestion.cleaner import clean_text
    from app.ingestion.chunker import chunk_text
    
    url = "https://www.cs.stanford.edu/"
    ts = datetime(2026, 8, 16, 15, 40, 12, tzinfo=timezone.utc)
    
    print("Step 1: Fetch content...")
    content = await fetch_snapshot_content(url, ts)
    print(f"  Got {len(content)} chars")
    
    print("\nStep 2: Clean...")
    cleaned = clean_text(content)
    print(f"  Cleaned: {len(cleaned.text)} chars, {len(cleaned.page_markers)} page markers")
    
    print("\nStep 3: Chunk...")
    chunks = chunk_text(cleaned, source_id=1)
    print(f"  Produced {len(chunks)} chunks")
    for i, c in enumerate(chunks[:3]):
        print(f"  [{i}] tokens={c.token_count}, text_len={len(c.text)}, preview={c.text[:100]}")
    
    if chunks:
        print(f"\n  All chunks token counts: {[c.token_count for c in chunks]}")
    
    print("\nStep 4: Embed...")
    from app.ingestion.embed import embed_chunks
    embedded = embed_chunks(chunks)
    print(f"  Embedded {len(embedded)} chunks, dim={len(embedded[0].embedding) if embedded else 0}")

asyncio.run(main())
