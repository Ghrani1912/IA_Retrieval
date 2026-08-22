"""Test: Does the streaming endpoint receive and process the domain filter correctly?"""
import urllib.request
import json
import sys

# Test 1: Non-streaming with domain filter
print("=== Test 1: Non-streaming /query with domain cs.stanford.edu ===")
url = "http://localhost:8000/query"
payload = json.dumps({
    "query": "what were prominent ai projects hosted on the website",
    "filters": {"domain": "cs.stanford.edu"}
}).encode("utf-8")
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
try:
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read().decode("utf-8"))
    
    # Check if any retrieved_chunks are from website
    web_chunks = [c for c in data.get("retrieved_chunks", []) if c.get("collection") == "cs.stanford.edu"]
    doc_chunks = [c for c in data.get("retrieved_chunks", []) if c.get("collection") != "cs.stanford.edu"]
    print(f"  Answer segments: {len(data.get('answer_segments', []))}")
    for seg in data.get("answer_segments", []):
        print(f"    text={seg['text'][:120]}...")
        print(f"    citation_type={seg.get('citation_type')}")
        print(f"    source_ids={seg.get('source_ids')}")
    print(f"  Total chunks: {len(data.get('retrieved_chunks', []))}")
    print(f"  Web chunks: {len(web_chunks)}")
    for c in web_chunks:
        print(f"    id={c.get('id')} src={c.get('source_id')} text={c.get('text', '')[:80]}...")
    print(f"  Doc chunks: {len(doc_chunks)}")
except urllib.error.HTTPError as e:
    print(f"  HTTP {e.code}: {e.read().decode()[:500]}")
except Exception as e:
    print(f"  Error: {e}")

# Test 2: Without domain filter
print("\n=== Test 2: Without domain filter ===")
payload2 = json.dumps({
    "query": "what were prominent ai projects hosted on the website",
    "filters": {}
}).encode("utf-8")
req2 = urllib.request.Request(url, data=payload2, headers={"Content-Type": "application/json"})
try:
    resp2 = urllib.request.urlopen(req2, timeout=120)
    data2 = json.loads(resp2.read().decode("utf-8"))
    web_chunks2 = [c for c in data2.get("retrieved_chunks", []) if c.get("collection") == "cs.stanford.edu"]
    print(f"  Answer segments: {len(data2.get('answer_segments', []))}")
    for seg in data2.get("answer_segments", []):
        print(f"    text={seg['text'][:120]}...")
        print(f"    citation_type={seg.get('citation_type')}")
    print(f"  Total chunks: {len(data2.get('retrieved_chunks', []))}")
    print(f"  Web chunks: {len(web_chunks2)}")
except urllib.error.HTTPError as e:
    print(f"  HTTP {e.code}: {e.read().decode()[:500]}")
except Exception as e:
    print(f"  Error: {e}")
