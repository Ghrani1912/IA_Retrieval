"""Test cs.stanford.edu query and check synthesis temperature."""
import urllib.request, json, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 1. Test the cs.stanford.edu query
url = "http://localhost:8000/query"
payload = json.dumps({
    "query": "what were prominent ai projects hosted on the website",
    "filters": {"domain": "cs.stanford.edu"}
}).encode()

req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req, timeout=120)
data = json.loads(resp.read())

print("=" * 60)
print("cs.stanford.edu QUERY RESULT")
print("=" * 60)

segments = data.get("answer_segments", [])
print(f"\nANSWER SEGMENTS: {len(segments)}")
for i, seg in enumerate(segments):
    text = seg.get("text", "") if isinstance(seg, dict) else str(seg)
    label = seg.get("citation_type", seg.get("label", "?")) if isinstance(seg, dict) else "?"
    source_ids = seg.get("source_ids", []) if isinstance(seg, dict) else []
    print(f"  [{i}] citation_type={label} source_ids={source_ids}")
    print(f"      text={text[:300]}")
    print()

chunks = data.get("retrieved_chunks", [])
print(f"RETRIEVED CHUNKS: {len(chunks)}")
for i, c in enumerate(chunks):
    title = c.get("source_title", "?")
    src_id = c.get("source_id", "?")
    year = c.get("year", "?")
    text = c.get("text", "")
    print(f"  [{i}] source_id={src_id}, year={year}, title={title}")
    print(f"      text_preview={text[:150]}")
    print()
