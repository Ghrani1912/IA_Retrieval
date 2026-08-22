"""Full debug: test the non-streaming query API and capture the exception."""
import urllib.request
import json

url = "http://localhost:8000/query"
payload = json.dumps({
    "query": "what were prominent ai projects hosted on the website",
    "filters": {"domain": "cs.stanford.edu"}
}).encode("utf-8")

req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

try:
    resp = urllib.request.urlopen(req, timeout=180)
    data = json.loads(resp.read().decode("utf-8"))
    
    web_chunks = [c for c in data.get("retrieved_chunks", []) if "cs.stanford" in str(c.get("collection", ""))]
    doc_chunks = [c for c in data.get("retrieved_chunks", []) if "cs.stanford" not in str(c.get("collection", ""))]
    
    print(f"Answer segments: {len(data.get('answer_segments', []))}")
    for seg in data.get("answer_segments", []):
        print(f"  text: {seg['text'][:200]}")
        print(f"  citation_type: {seg.get('citation_type')}")
        print(f"  source_ids: {seg.get('source_ids')}")
        print(f"  chunk_ids: {seg.get('chunk_ids')}")
    
    print(f"\nTotal chunks: {len(data.get('retrieved_chunks', []))}")
    print(f"Web chunks: {len(web_chunks)}")
    for c in web_chunks:
        print(f"  id={c.get('id')} src={c.get('source_id')} coll={c.get('collection')} text={c.get('text', '')[:100]}...")
    print(f"Doc chunks: {len(doc_chunks)}")
    for i, c in enumerate(doc_chunks[:3]):
        print(f"  [{i+1}] id={c.get('id')} src={c.get('source_id')} coll={c.get('collection')} text={c.get('text', '')[:80]}...")

except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8")
    print(f"HTTP {e.code}:")
    print(body[:2000])
except Exception as e:
    print(f"Error: {e}")
