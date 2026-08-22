"""Test on-demand pipeline directly to confirm it works."""
import asyncio
import sys
sys.path.insert(0, ".")

async def main():
    from app.wayback.ondemand import fetch_web_content_for_domain
    from app.models.pydantic_models import RankedChunk, SourceMetadata
    
    domain = "cs.stanford.edu"
    print(f"Testing fetch_web_content_for_domain({domain})...")
    
    web_raw = await fetch_web_content_for_domain(domain)
    print(f"Got {len(web_raw)} chunks")
    
    for i, chunk in enumerate(web_raw):
        rc = RankedChunk(
            chunk=chunk,
            rank=0,
            score=0.0,
            source_metadata=SourceMetadata(
                ia_identifier=domain,
                title=f"Website: {domain}",
                collection=domain,
            ),
        )
        print(f"  RankedChunk {i}: rank={rc.rank}, score={rc.score}, coll={rc.source_metadata.collection}")
    
    print(f"\nAll {len(web_raw)} RankedChunks created successfully")

asyncio.run(main())
