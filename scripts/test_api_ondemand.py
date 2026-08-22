"""Test the on-demand pipeline exactly as the API query route does it."""
import asyncio
import sys
sys.path.insert(0, ".")

async def main():
    from app.models.pydantic_models import RankedChunk, SourceMetadata, StructuredQuery
    from app.retrieval.query_understanding import understand_query
    
    # Simulate what the API does
    body_query = "what were prominent ai projects hosted on the website"
    domain = "cs.stanford.edu"
    
    # Step 1: understand_query
    sq = await understand_query(body_query)
    print(f"understand_query domain: {sq.domain}")
    
    # Apply domain filter from request body
    sq.domain = domain
    print(f"After applying filter, domain: {sq.domain}")
    
    # Step 1b: on-demand fetch
    web_chunks = []
    if sq.domain:
        from app.wayback.ondemand import fetch_web_content_for_domain
        print(f"Calling fetch_web_content_for_domain({sq.domain})...")
        web_raw = await fetch_web_content_for_domain(sq.domain)
        print(f"Got {len(web_raw)} raw chunks")
        for chunk in web_raw:
            web_chunks.append(RankedChunk(
                chunk=chunk,
                rrf_score=0.0,
                source_metadata=SourceMetadata(
                    ia_identifier=sq.domain,
                    title=f"Website: {sq.domain}",
                    collection=sq.domain,
                ),
            ))
        print(f"Created {len(web_chunks)} RankedChunks")
    
    print(f"\nFinal web_chunks count: {len(web_chunks)}")
    for wc in web_chunks:
        print(f"  chunk_id={wc.chunk.id} text[:80]={wc.chunk.text[:80]}...")
        print(f"  source_metadata.collection={wc.source_metadata.collection}")

asyncio.run(main())
