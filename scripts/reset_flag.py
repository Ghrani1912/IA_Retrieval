import asyncio, asyncpg
from datetime import datetime, timezone

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/platform', ssl=False)
    ts = datetime(2026, 8, 16, 15, 40, 12, tzinfo=timezone.utc)
    await conn.execute(
        "UPDATE website_snapshots SET fetched_flag = false, fetched_at = NULL "
        "WHERE url = $1 AND snapshot_timestamp = $2",
        'https://www.cs.stanford.edu/',
        ts
    )
    print('Reset fetched_flag')
    await conn.close()

asyncio.run(main())
