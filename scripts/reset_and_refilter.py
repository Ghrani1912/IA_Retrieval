"""Delete old junk web chunks for cs.stanford.edu and reset fetched_flag."""
import asyncio
import asyncpg
from app.config import settings

DB_URL = settings.database_url.replace("postgresql+asyncpg", "postgresql")

async def main():
    conn = await asyncpg.connect(DB_URL, ssl=False)

    # 1. Delete citations referencing cs.stanford.edu chunks first
    deleted_citations = await conn.execute(
        """
        DELETE FROM evidence_citations
        WHERE chunk_id IN (
            SELECT c.id FROM chunks c
            JOIN sources s ON c.source_id = s.id
            WHERE s.ia_identifier = 'cs.stanford.edu'
        )
        """
    )
    print(f"Deleted citations: {deleted_citations}")

    # 2. Delete old chunks for cs.stanford.edu
    deleted_chunks = await conn.execute(
        """
        DELETE FROM chunks
        WHERE source_id = (SELECT id FROM sources WHERE ia_identifier = 'cs.stanford.edu')
        """
    )
    print(f"Deleted chunks: {deleted_chunks}")

    # 2. Reset fetched_flag for cs.stanford.edu
    updated = await conn.execute(
        """
        UPDATE website_snapshots
        SET fetched_flag = false
        WHERE domain = 'cs.stanford.edu' AND fetched_flag = true
        """
    )
    print(f"Reset fetched_flag: {updated}")

    # 3. Delete from OpenSearch
    import urllib.request, json
    try:
        req = urllib.request.Request(
            "http://localhost:9200/chunks/_delete_by_query",
            data=json.dumps({
                "query": {
                    "term": {"ia_identifier": "cs.stanford.edu"}
                }
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        print(f"OpenSearch deleted: {result.get('deleted', 0)} docs")
    except Exception as e:
        print(f"OpenSearch delete failed: {e}")

    # 4. Delete from Qdrant
    try:
        from qdrant_client import QdrantClient
        from app.config import settings
        qd = QdrantClient(url=settings.qdrant_url)
        # Delete by filter
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        qd.delete(
            collection_name="chunks",
            points_selector=Filter(
                must=[FieldCondition(key="ia_identifier", match=MatchValue(value="cs.stanford.edu"))]
            )
        )
        print("Qdrant deleted cs.stanford.edu vectors")
    except Exception as e:
        print(f"Qdrant delete failed: {e}")

    # 5. Verify
    remaining = await conn.fetchval(
        "SELECT COUNT(*) FROM chunks WHERE source_id = (SELECT id FROM sources WHERE ia_identifier = 'cs.stanford.edu')"
    )
    print(f"Remaining chunks: {remaining}")

    await conn.close()

asyncio.run(main())
