"""Check error response from domain query."""
import urllib.request, json, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

url = "http://localhost:8000/query"
payload = json.dumps({
    "query": "what was on cs.stanford.edu",
    "filters": {"domain": "cs.stanford.edu"}
}).encode()

req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
try:
    resp = urllib.request.urlopen(req, timeout=180)
    print(resp.read().decode()[:1000])
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}")
    body = e.read().decode()
    print(body[:1000])
