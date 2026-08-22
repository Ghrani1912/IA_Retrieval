"""Test the web chunk filtering."""
import sys
sys.path.insert(0, ".")

from app.wayback.ondemand import _get_existing_chunks, _filter_web_chunks
from app.models.pydantic_models import Chunk

# Test 1: raw DB chunks
import asyncio
async def main():
    chunks = await _get_existing_chunks("cs.stanford.edu")
    print(f"After _get_existing_chunks: {len(chunks)} chunks")
    for c in chunks:
        print(f"  id={c.id} text[:80]={c.text[:80]}...")

asyncio.run(main())
