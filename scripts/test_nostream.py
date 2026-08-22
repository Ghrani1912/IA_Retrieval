"""Test the NON-streaming query endpoint with domain filter to see the error."""
import urllib.request
import json

url = "http://localhost:8000/query"
payload = json.dumps({
    "query": "what were prominent ai projects hosted on the website",
    "filters": {"domain": "cs.stanford.edu"}
}).encode("utf-8")

req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

try:
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read().decode("utf-8"))
    print(json.dumps(data, indent=2)[:2000])
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8")
    print(f"HTTP {e.code}: {body[:1000]}")
except Exception as e:
    print(f"Error: {e}")
