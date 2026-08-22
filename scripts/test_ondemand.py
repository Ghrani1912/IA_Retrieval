"""Test on-demand web content fetch for cs.stanford.edu."""
import urllib.request, json, sys, io, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

url = "http://localhost:8000/query"
payload = json.dumps({
    "query": "what were prominent ai projects hosted on the website",
    "filters": {"domain": "cs.stanford.edu"}
}).encode()

print("=" * 60)
print("TEST: On-demand web content fetch for cs.stanford.edu")
print("=" * 60)
print(f"\nSending query... (may take 60-120s for first run)")

t0 = time.time()
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req, timeout=300)
elapsed = time.time() - t0
data = json.loads(resp.read())

segments = data.get("answer_segments", [])
chunks = data.get("retrieved_chunks", [])

print(f"\nCompleted in {elapsed:.1f}s")
print(f"\nANSWER SEGMENTS: {len(segments)}")
for i, seg in enumerate(segments):
    text = seg.get("text", "") if isinstance(seg, dict) else str(seg)
    label = seg.get("citation_type", "?") if isinstance(seg, dict) else "?"
    source_ids = seg.get("source_ids", []) if isinstance(seg, dict) else []
    print(f"  [{i}] citation_type={label} source_ids={source_ids}")
    print(f"      text={text[:300]}")
    print()

print(f"RETRIEVED CHUNKS: {len(chunks)}")
for i, c in enumerate(chunks):
    title = c.get("source_title", "?")
    src_id = c.get("source_id", "?")
    year = c.get("year", "?")
    text = c.get("text", "")
    is_web = c.get("capture_timestamp") is not None
    print(f"  [{i}] source_id={src_id}, year={year}, {'WEB' if is_web else 'DOC'}")
    print(f"      title={title}")
    print(f"      text_preview={text[:150]}")
    print()
