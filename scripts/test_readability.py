"""Test readability extraction on the fetched HTML."""
import asyncio, sys, io, httpx
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    from datetime import datetime, timezone
    from app.wayback.memento import _format_memento_ts, _extract_text_readability
    
    url = "https://www.cs.stanford.edu/"
    ts = datetime(2026, 8, 16, 15, 40, 12, tzinfo=timezone.utc)
    ts_str = _format_memento_ts(ts)
    memento_url = f"https://web.archive.org/web/{ts_str}/{url}"
    
    print(f"Fetching raw HTML from {memento_url}...")
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        resp = await client.get(memento_url, headers={"User-Agent": "HistoricalRAG/1.0"})
        print(f"Status: {resp.status_code}, length: {len(resp.text)}")
        
        # Test readability
        text = _extract_text_readability(resp.text, url)
        if text:
            print(f"\nReadability output: {len(text)} chars")
            print(f"First 300 chars: {text[:300]}")
        else:
            print("\nReadability returned None")
        
        # Check if readability is installed
        try:
            from readability import Document
            doc = Document(resp.text)
            summary = doc.summary()
            print(f"\nDirect readability test: {len(summary)} chars")
            # Strip HTML tags
            import re
            clean = re.sub(r'<[^>]+>', ' ', summary)
            clean = re.sub(r'\s+', ' ', clean).strip()
            print(f"Cleaned: {len(clean)} chars")
            print(f"First 300 chars: {clean[:300]}")
        except ImportError:
            print("\nreadability-lxml NOT installed")
        except Exception as e:
            print(f"\nreadability error: {e}")

asyncio.run(main())
