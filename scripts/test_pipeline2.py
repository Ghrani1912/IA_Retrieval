"""Test the on-demand pipeline step by step — no embedding."""
import asyncio, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

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
    print(f"  First 200 chars: {content[:200]}")
    
    print("\nStep 2: Clean...")
    cleaned = clean_text(content)
    print(f"  Cleaned: {len(cleaned.text)} chars")
    print(f"  First 200 chars: {cleaned.text[:200]}")
    
    print("\nStep 3: Chunk...")
    chunks = chunk_text(cleaned, source_id=1)
    print(f"  Produced {len(chunks)} chunks")
    for i, c in enumerate(chunks[:5]):
        print(f"  [{i}] tokens={c.token_count}, text_len={len(c.text)}")
        print(f"      preview: {c.text[:120]}")

asyncio.run(main())
