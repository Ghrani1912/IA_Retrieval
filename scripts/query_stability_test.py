"""Run identical query 3 times and record segment count each time."""
import urllib.request, json, sys, io, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

url = "http://localhost:8000/query"
payload = json.dumps({
    "query": "What are Minsky frames in knowledge representation",
    "filters": {}
}).encode()

results = []
for run in range(1, 4):
    print(f"--- RUN {run} ---")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=120)
    elapsed = time.time() - t0
    data = json.loads(resp.read())

    segments = data.get("answer_segments", [])
    chunks = data.get("retrieved_chunks", [])

    seg_count = len(segments)
    chunk_count = len(chunks)

    # Print segment details
    for i, seg in enumerate(segments):
        text = seg.get("text", "") if isinstance(seg, dict) else str(seg)
        label = seg.get("label", "?") if isinstance(seg, dict) else "?"
        print(f"  segment[{i}] label={label} len={len(text)}")
        print(f"    text={text[:150]}...")

    # Print chunk IDs to see if retrieval order changes
    chunk_ids = [c.get("source_id") for c in chunks]
    print(f"  chunks: {chunk_count}, source_ids: {chunk_ids}")
    print(f"  elapsed: {elapsed:.1f}s")
    print()

    results.append({"run": run, "segments": seg_count, "chunks": chunk_count, "chunk_ids": chunk_ids, "elapsed": elapsed})
    if run < 3:
        time.sleep(2)  # small gap between runs

print("=" * 60)
print("SUMMARY")
print("=" * 60)
for r in results:
    print(f"  Run {r['run']}: {r['segments']} segments, {r['chunks']} chunks, {r['elapsed']:.1f}s")
    print(f"    chunk_ids: {r['chunk_ids']}")
