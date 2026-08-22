import urllib.request, json, sys

queries = [
    ("how many snapshots were taken in 2013", "landonorris.com"),
    ("when was the first snapshot", "landonorris.com"),
    ("what years have captures", "landonorris.com"),
    ("date range of snapshots", "landonorris.com"),
    ("what is this website about", "landonorris.com"),  # should NOT be intercepted (content question)
]

for q, domain in queries:
    data = json.dumps({"query": q, "filters": {"domain": domain}}).encode()
    req = urllib.request.Request("http://localhost:8000/query", data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        segments = result.get("answer_segments", [])
        print(f"\nQuery: {q}")
        print(f"  Segments: {len(segments)}")
        for s in segments:
            text = s.get("text", "")[:200]
            print(f"  [{s.get('citation_type', '?')}] {text}")
    except Exception as e:
        print(f"\nQuery: {q}")
        print(f"  ERROR: {e}")
