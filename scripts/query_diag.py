"""Check raw backend query response: segment count, chunk count, chunk details."""
import urllib.request, json, sys

url = "http://localhost:8000/query"
payload = json.dumps({
    "query": "what were prominent ai projects hosted on the website",
    "filters": {"domain": "cs.stanford.edu"}
}).encode()

req = urllib.request.Request(
    url, data=payload,
    headers={"Content-Type": "application/json"}
)

try:
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

print("=" * 60)
print("RAW BACKEND RESPONSE")
print("=" * 60)

# Answer segments
segments = data.get("answer_segments", [])
print(f"\nANSWER SEGMENTS: {len(segments)}")
for i, seg in enumerate(segments):
    text = seg.get("text", "") if isinstance(seg, dict) else str(seg)
    label = seg.get("label", "?") if isinstance(seg, dict) else "?"
    print(f"  [{i}] label={label}")
    print(f"      text={text[:300]}")
    print()

# Retrieved chunks
chunks = data.get("retrieved_chunks", [])
print(f"\nRETRIEVED CHUNKS: {len(chunks)}")
for i, c in enumerate(chunks):
    title = c.get("source_title", "?")
    src_id = c.get("source_id", "?")
    text = c.get("text", "")
    page = c.get("page_number", "?")
    year = c.get("year", "?")
    print(f"  [{i}] source_id={src_id}, year={year}, page={page}")
    print(f"      title={title}")
    print(f"      text_len={len(text)} chars")
    print(f"      text_preview={text[:150]}")
    print()

# Any other keys
print(f"\nOTHER KEYS: {[k for k in data.keys() if k not in ('answer_segments', 'retrieved_chunks')]}")
