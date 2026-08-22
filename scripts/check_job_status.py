import asyncio, asyncpg, json
from app.config import settings

db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql")

async def main():
    conn = await asyncpg.connect(db_url)
    # Check actual columns
    cols = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='ingestion_jobs' ORDER BY ordinal_position")
    print("Columns:", [r['column_name'] for r in cols])
    rows = await conn.fetch("SELECT * FROM ingestion_jobs ORDER BY created_at DESC LIMIT 3")
    for r in rows:
        print(json.dumps(dict(r), default=str, indent=2))
    await conn.close()

asyncio.run(main())
