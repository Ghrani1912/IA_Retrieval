"""Debug the on-demand pipeline step by step."""
import asyncio
import sys
sys.path.insert(0, ".")

async def main():
    # Step 1: Check _get_latest_snapshot
    from app.wayback.ondemand import _get_latest_snapshot, _snapshot_already_chunked, _get_existing_chunks
    import logging
    logging.basicConfig(level=logging.INFO)
    
    domain = "cs.stanford.edu"
    
    print("=== Step 1: _get_latest_snapshot ===")
    snapshot = await _get_latest_snapshot(domain)
    if snapshot:
        print(f"  url={snapshot['url']}")
        print(f"  ts={snapshot['snapshot_timestamp']}")
        print(f"  status={snapshot['status_code']}")
        print(f"  digest={snapshot['digest']}")
    else:
        print("  No snapshot found!")
        return
    
    print("\n=== Step 2: _snapshot_already_chunked ===")
    already = await _snapshot_already_chunked(snapshot['url'], snapshot['snapshot_timestamp'])
    print(f"  already_chunked={already}")
    
    if already:
        print("\n=== Step 3: _get_existing_chunks (should return 4 chunks) ===")
        chunks = await _get_existing_chunks(domain)
        print(f"  Found {len(chunks)} chunks")
        for c in chunks:
            print(f"    id={c.id} text[:80]={c.text[:80]}...")
    
    print("\n=== Step 4: fetch_web_content_for_domain (full call) ===")
    from app.wayback.ondemand import fetch_web_content_for_domain
    result = await fetch_web_content_for_domain(domain)
    print(f"  Returned {len(result)} chunks")
    for c in result:
        print(f"    id={c.id} text[:80]={c.text[:80]}...")

asyncio.run(main())
