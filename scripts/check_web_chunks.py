import asyncio, asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/platform', ssl=False)
    rows = await conn.fetch(
        "SELECT id, source_id, text, page_or_section FROM chunks "
        "WHERE source_id IN (SELECT id FROM sources WHERE ia_identifier = 'cs.stanford.edu')"
    )
    print(f"Chunks for cs.stanford.edu: {len(rows)}")
    for r in rows:
        print(f"  id={r['id']}, text_len={len(r['text'])}, preview={r['text'][:100]}")
    await conn.close()

asyncio.run(main())
