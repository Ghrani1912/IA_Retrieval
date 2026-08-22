"""Test the streaming query endpoint with domain filter."""
import urllib.request
import json
import sys

url = "http://localhost:8000/query/stream"
payload = json.dumps({
    "query": "what were prominent ai projects hosted on the website",
    "filters": {"domain": "cs.stanford.edu"}
}).encode("utf-8")

req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

try:
    resp = urllib.request.urlopen(req, timeout=60)
    raw = resp.read().decode("utf-8")
    
    # Parse SSE events
    segments = []
    answer_data = None
    for line in raw.split("\n"):
        if line.startswith("event: "):
            event_type = line[7:].strip()
        elif line.startswith("data: "):
            data_str = line[6:].strip()
            if not data_str:
                continue
            try:
                data = json.loads(data_str)
                if event_type == "done":
                    answer_data = data
                elif event_type == "token":
                    sys.stdout.write(data.get("text", ""))
                    sys.stdout.flush()
            except json.JSONDecodeError:
                pass
    
    print("\n\n=== FINAL ANSWER ===")
    if answer_data:
        print(f"Segments: {len(answer_data.get('answer_segments', []))}")
        for i, seg in enumerate(answer_data.get('answer_segments', [])):
            print(f"\n  Segment {i+1}:")
            print(f"    Text: {seg.get('text', '')[:200]}...")
            print(f"    Citation: {seg.get('citation_type', 'N/A')}")
            print(f"    Sources: {seg.get('source_ids', [])}")
        
        print(f"\nRetrieved chunks: {len(answer_data.get('retrieved_chunks', []))}")
        for i, chunk in enumerate(answer_data.get('retrieved_chunks', [])):
            print(f"  [{i+1}] source={chunk.get('source_id', 'N/A')} coll={chunk.get('collection', 'N/A')} text={chunk.get('text', '')[:80]}...")
    else:
        print("No done event received")
        print(f"Raw response length: {len(raw)} chars")
        print(f"First 500 chars: {raw[:500]}")

except Exception as e:
    print(f"Error: {e}")
