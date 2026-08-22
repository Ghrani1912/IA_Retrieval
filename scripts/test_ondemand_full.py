"""Test on-demand pipeline with full error handling."""
import asyncio, sys, io, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_URL = "postgresql://postgres:postgres@localhost:5432/platform"

async def main():
    try:
        from app.wayback.ondemand import fetch_web_content_for_domain
        print("Testing fetch_web_content_for_domain('cs.stanford.edu')...")
        chunks = await fetch_web_content_for_domain("cs.stanford.edu")
        print(f"Got {len(chunks)} chunks")
        for i, c in enumerate(chunks):
            print(f"  [{i}] id={c.id}, tokens={c.token_count}, text_len={len(c.text)}")
            print(f"      preview: {c.text[:120]}")
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()

asyncio.run(main())
