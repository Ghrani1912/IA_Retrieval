"""Test a normal (non-website) query against the retrieval pipeline."""
import urllib.request, json, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

url = "http://localhost:8000/query"
payload = json.dumps({
    "query": "What are Minsky frames in knowledge representation",
    "filters": {}
}).encode()

req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req, timeout=120)
data = json.loads(resp.read())

print("=" * 60)
print("NORMAL QUERY: 'What are Minsky frames in knowledge representation'")
print("=" * 60)

segments = data.get("answer_segments", [])
print(f"\nANSWER SEGMENTS: {len(segments)}")
for i, seg in enumerate(segments):
    text = seg.get("text", "") if isinstance(seg, dict) else str(seg)
    label = seg.get("label", "?") if isinstance(seg, dict) else "?"
    print(f"  [{i}] label={label}")
    print(f"      text={text[:250]}")
    print()

chunks = data.get("retrieved_chunks", [])
print(f"RETRIEVED CHUNKS: {len(chunks)}")
for i, c in enumerate(chunks):
    title = c.get("source_title", "?")
    src_id = c.get("source_id", "?")
    year = c.get("year", "?")
    text = c.get("text", "")
    print(f"  [{i}] source_id={src_id}, year={year}")
    print(f"      title={title}")
    print(f"      text_len={len(text)} chars, preview={text[:120]}")
    print()
