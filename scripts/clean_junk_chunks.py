"""Delete junk chunks (TOC, index, front matter) from all indexes."""
import asyncio
import asyncpg
import httpx
import re

from app.config import settings

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")
OS_URL = settings.opensearch_url
QDRANT_URL = settings.qdrant_url


def is_junk(text: str) -> bool:
    """Detect non-content pages: TOC, index, title, copyright, name lists."""
    if not text or len(text.strip()) < 50:
        return True
    total_words = len(text.split())
    if total_words < 30:
        return True
    if re.search(r"Digitized by|Internet Archive|Library of Congress|archive\.org/", text, re.IGNORECASE):
        return True
    if len(re.findall(r"\d+\.\s+.+/\s*\d+\b", text)) >= 3:
        return True
    if len(re.findall(r"^[A-Z][a-z]+\s+[A-Z][a-z]+", text, re.MULTILINE)) >= 8:
        return True
    if re.search(r"acknowledgment|acknowledgement|preface|foreword|since the.*project began|we wish|we are grateful", text, re.IGNORECASE):
        return True
    whitespace_ratio = 1 - (total_words / max(len(text), 1))
    if total_words < 50 and whitespace_ratio > 0.4:
        return True
    return False


async def main():
    conn = await asyncpg.connect(DB_URL, ssl=False)

    # 1. Find all Americana junk chunks
    rows = await conn.fetch("""
        SELECT c.id, c.text
        FROM chunks c JOIN sources s ON c.source_id = s.id
        WHERE s.collection = 'americana'
    """)

    junk_ids = [r["id"] for r in rows if is_junk(r["text"])]
    print(f"Found {len(junk_ids)} junk chunks out of {len(rows)} Americana chunks")

    if not junk_ids:
        print("Nothing to clean.")
        await conn.close()
        return

    # Show a few samples
    for cid in junk_ids[:3]:
        row = next(r for r in rows if r["id"] == cid)
        print(f"  Junk chunk {cid}: {row['text'][:100].strip()!r}")

    # 2. Delete from Postgres (citations first, then chunks)
    for cid in junk_ids:
        await conn.execute("DELETE FROM evidence_citations WHERE chunk_id = $1", cid)
        await conn.execute("DELETE FROM chunks WHERE id = $1", cid)
    print(f"Deleted {len(junk_ids)} chunks from Postgres")

    # 3. Delete from OpenSearch
    async with httpx.AsyncClient() as client:
        for cid in junk_ids:
            await client.delete(f"{OS_URL}/chunks/_doc/{cid}", timeout=5.0)
        # Refresh index
        await client.post(f"{OS_URL}/chunks/_refresh", timeout=5.0)
    print(f"Deleted {len(junk_ids)} chunks from OpenSearch")

    # 4. Delete from Qdrant
    async with httpx.AsyncClient() as client:
        await client.put(
            f"{QDRANT_URL}/collections/chunks/points/delete",
            json={"points": junk_ids},
            timeout=30.0,
        )
    print(f"Deleted {len(junk_ids)} chunks from Qdrant")

    # 5. Verify remaining Americana chunk count
    remaining = await conn.fetchval("""
        SELECT COUNT(*) FROM chunks c
        JOIN sources s ON c.source_id = s.id
        WHERE s.collection = 'americana'
    """)
    print(f"Americana chunks remaining: {remaining}")

    total = await conn.fetchval("SELECT COUNT(*) FROM chunks")
    print(f"Total chunks remaining: {total}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
