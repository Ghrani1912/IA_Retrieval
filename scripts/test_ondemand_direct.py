"""Test the ondemand module directly to find the error."""
import asyncio, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_URL = "postgresql://postgres:postgres@localhost:5432/platform"

async def main():
    import asyncpg
    conn = await asyncpg.connect(DB_URL, ssl=False)
    
    # Test _get_latest_snapshot logic
    row = await conn.fetchrow(
        "SELECT id, url, snapshot_timestamp, status_code FROM website_snapshots "
        "WHERE domain = $1 AND status_code >= 200 AND status_code < 400 "
        "ORDER BY snapshot_timestamp DESC LIMIT 1",
        "cs.stanford.edu"
    )
    print(f"Latest snapshot: {row}")
    print(f"  url: {row['url']}")
    print(f"  timestamp: {row['snapshot_timestamp']}")
    print(f"  type: {type(row['snapshot_timestamp'])}")
    
    await conn.close()

asyncio.run(main())
