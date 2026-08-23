"""Pull actual chunk text to confirm the Americana cannibalization mechanism."""
import asyncio
import asyncpg


async def main():
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@localhost:5432/platform", ssl=False
    )

    # === Part 1: Chunk length stats by collection ===
    stats = await conn.fetch("""
        SELECT s.collection,
               COUNT(*) as chunks,
               AVG(LENGTH(c.text))::int as avg_len,
               MIN(LENGTH(c.text)) as min_len,
               MAX(LENGTH(c.text)) as max_len
        FROM chunks c JOIN sources s ON c.source_id = s.id
        GROUP BY s.collection ORDER BY chunks DESC
    """)
    print("=== CHUNK LENGTH STATS BY COLLECTION ===")
    for r in stats:
        print(
            f"  {r['collection']:20s}: {r['chunks']:5d} chunks, "
            f"avg={r['avg_len']:5d} chars, min={r['min_len']}, max={r['max_len']}"
        )

    # === Part 2: q001 (semantic networks) — pull GT + displaced Americana ===
    print("\n" + "=" * 70)
    print("QUERY q001: 'What are semantic networks and how do they represent knowledge?'")
    print("GT chunks: 4370, 4369, 4376, 4406, 4407 (all DTIC)")
    print("Top-10 composition: 8 Americana, 2 DTIC")
    print("=" * 70)

    gt_ids = [4370, 4369, 4376, 4406, 4407]
    for cid in gt_ids:
        row = await conn.fetchrow(
            "SELECT c.id, c.text, s.collection, s.title "
            "FROM chunks c JOIN sources s ON c.source_id = s.id "
            "WHERE c.id = $1",
            cid,
        )
        if row:
            print(f"\n--- GT chunk {cid} [{row['collection']}] ---")
            print(f"Source: {row['title'][:80]}")
            print(f"Length: {len(row['text'])} chars")
            print(f"Text: {row['text'][:500]}")

    # Get Americana chunks that are semantically similar to "semantic networks"
    # These are the ones displacing the GT chunks
    am_chunks = await conn.fetch(
        "SELECT c.id, c.text, s.title, LENGTH(c.text) as tlen "
        "FROM chunks c JOIN sources s ON c.source_id = s.id "
        "WHERE s.collection = 'americana' "
        "AND (c.text ILIKE '%semantic%' OR c.text ILIKE '%network%' "
        "OR c.text ILIKE '%knowledge representation%') "
        "LIMIT 5"
    )
    print(f"\n--- AMERICANA chunks matching 'semantic/knowledge' keywords ({len(am_chunks)} found) ---")
    for row in am_chunks:
        print(f"\nChunk {row['id']} ({row['tlen']} chars) from: {row['title'][:80]}")
        print(f"Text: {row['text'][:500]}")

    # === Part 3: q002 (MYCIN expert systems) — another displaced case ===
    print("\n" + "=" * 70)
    print("QUERY q002: 'How do expert systems like MYCIN use rule-based inference?'")
    print("GT chunks: 9156, 9157, 9158, 4100, 8392 (DTIC)")
    print("Top-10 composition: 9 Americana, 1 DTIC")
    print("=" * 70)

    gt2 = [9156, 9157, 4100, 8392]
    for cid in gt2:
        row = await conn.fetchrow(
            "SELECT c.id, c.text, s.collection, s.title "
            "FROM chunks c JOIN sources s ON c.source_id = s.id "
            "WHERE c.id = $1",
            cid,
        )
        if row:
            print(f"\n--- GT chunk {cid} [{row['collection']}] ---")
            print(f"Source: {row['title'][:80]}")
            print(f"Length: {len(row['text'])} chars")
            print(f"Text: {row['text'][:500]}")

    am_mycin = await conn.fetch(
        "SELECT c.id, c.text, s.title, LENGTH(c.text) as tlen "
        "FROM chunks c JOIN sources s ON c.source_id = s.id "
        "WHERE s.collection = 'americana' "
        "AND (c.text ILIKE '%MYCIN%' OR c.text ILIKE '%expert system%' "
        "OR c.text ILIKE '%rule-based%' OR c.text ILIKE '%inference%') "
        "LIMIT 5"
    )
    print(f"\n--- AMERICANA chunks matching 'MYCIN/expert system' keywords ({len(am_mycin)} found) ---")
    for row in am_mycin:
        print(f"\nChunk {row['id']} ({row['tlen']} chars) from: {row['title'][:80]}")
        print(f"Text: {row['text'][:500]}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
