"""Test Memento fetch step by step."""
import asyncio, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_URL = "postgresql://postgres:postgres@localhost:5432/platform"

async def main():
    from datetime import datetime, timezone
    from app.wayback.memento import fetch_snapshot_content
    
    url = "https://www.cs.stanford.edu/"
    ts = datetime(2026, 8, 16, 15, 40, 12, tzinfo=timezone.utc)
    
    print(f"Fetching content from {url} @ {ts}...")
    content = await fetch_snapshot_content(url, ts, db_url=DB_URL)
    
    if content:
        print(f"Got {len(content)} chars")
        print(f"Preview: {content[:300]}")
    else:
        print("No content returned")

asyncio.run(main())
