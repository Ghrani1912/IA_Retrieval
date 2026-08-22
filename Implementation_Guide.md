# Implementation Guide: Build Order & Detailed Steps

This is the "what do I actually do, in order" companion to the PRD. Follow it top to bottom — each step produces something testable before you move on.

---

## Phase 0 — Setup (few hours)

1. **Repo + environment**
   - `git init`, Python 3.11+, `poetry` or `uv` for deps.
   - Docker Compose file with 3 services to start: `postgres`, `opensearch`, `qdrant`. Don't containerize your app code yet — run it locally against these for fast iteration.
2. **Get familiar with the two IA endpoints you'll use constantly**, by hand, before writing code:
   - `https://archive.org/advancedsearch.php?q=collection:americana+AND+date:[1900-01-01+TO+1928-12-31]&fl[]=identifier&fl[]=title&fl[]=date&output=json&rows=20`
   - `https://archive.org/metadata/{identifier}` — look at the `files` array, find the `_djvu.txt` entry.
3. **Pick your first 20-item test set.** Don't build against the full corpus yet — hardcode a query like `subject:"artificial intelligence" AND date:[1975-01-01 TO 1990-12-31]` and use its ~20 results as your dev fixture. This keeps every downstream step fast to test.

**Done when:** you can fetch and print the OCR text of 5 real books from the terminal.

---

## Phase 1 — Ingestion pipeline (book/paper module)

**Step 1.1 — Discovery adapter**
Write `discover(query, date_range, media_type) -> list[identifier + metadata]` wrapping the Advanced Search API. Handle pagination (rows/page params) and the 10,000-result paging cap. Store raw metadata JSON in Postgres `sources` table immediately — don't wait until later steps.

**Step 1.2 — Fetch adapter**
Write `fetch_fulltext(identifier) -> raw text` that:
- Calls the Metadata API, finds `_djvu.txt` (or `_hocr.html` if you want positional data for page anchors).
- Downloads it, caches the raw file in object storage (S3/MinIO) keyed by identifier — never re-download on re-runs.
- Returns None gracefully if no OCR text exists (in-copyright item) — mark that source as `metadata_only` in Postgres rather than failing.

**Step 1.3 — Cleaning**
- Strip page-break artifacts, OCR line-break hyphenation, and running headers/footers if detectable.
- Keep a `page_number` marker inline (djvu text usually has form-feed characters between pages — preserve as anchors, don't destroy them during cleaning).

**Step 1.4 — Chunking**
- Paragraph-aware chunker, ~400–600 tokens, ~15% overlap.
- Every chunk keeps: `source_id`, `page_or_section`, `char_range`. This is what makes citations page-accurate later, not just document-accurate.

**Done when:** for your 20-item test set, you have clean, chunked text in Postgres with page anchors preserved, and you can manually verify 3 chunks against the original scanned page on archive.org.

---

## Phase 2 — Indexing

**Step 2.1 — BM25 index**
- Stand up OpenSearch, create an index with a `text` field (chunk text) and keyword fields for `date`, `source_type`, `collection`, `identifier`.
- Bulk-index your chunks.
- Test: run a plain keyword query, confirm reasonable top-10 results for something like "machine intelligence."

**Step 2.2 — Embeddings + vector index**
- Run BGE-M3 (via `sentence-transformers` or a hosted embedding API) over every chunk.
- Insert into Qdrant with payload = same metadata fields as OpenSearch (date, source_type, collection) so you can filter at query time without a join.
- Test: embed a query, do a raw similarity search, sanity-check top results.

**Done when:** the same query returns *different but both plausible* top-10s from BM25 vs vector search — that's the signal hybrid retrieval will actually add value.

---

## Phase 3 — Hybrid retrieval

**Step 3.1 — Metadata + temporal filtering**
Before fusion, apply hard filters (date range, source_type, collection) to both the BM25 and vector candidate lists — don't filter after fusion, it wastes your top-K budget on irrelevant results.

**Step 3.2 — Reciprocal Rank Fusion**
Simple, don't overthink it:
```
score(doc) = sum over each ranked list of  1 / (k + rank_in_that_list)
```
`k=60` is the standard default. Merge BM25 top-50 and vector top-50 this way into a single top-30.

**Step 3.3 — Reranker**
Run a cross-encoder (BGE reranker) over the top-30 fused candidates against the original query, take top 8–12. This step is where most of your quality gain will actually come from — don't skip it to save time.

**Done when:** you can hand it a query and get back 8–12 chunks with metadata, ranked, filtered by date/type correctly.

---

## Phase 4 — Answer synthesis with citations

**Step 4.1 — Prompt design**
Feed the LLM the evidence chunks (with source metadata inline: title, author, date, identifier, page) and instruct it to:
- Answer only from provided evidence.
- Tag each claim as `[DIRECTLY VERIFIED: source X, p.Y]` or `[INFERRED: synthesized from sources X,Y]`.
- Say `[UNKNOWN]` rather than guessing if evidence doesn't cover the question.

**Step 4.2 — Structured output**
Have the LLM return JSON: `{answer_segments: [{text, citation_type, source_ids}]}`. Parse this server-side so your UI can render clickable citations rather than trusting free-text formatting.

**Done when:** you can ask "What did researchers think about AI in the 1980s?" against your test set and get an answer where every sentence traces to a real chunk you can pull up.

---

## Phase 5 — Website / Wayback module

**Step 5.1 — CDX ingestion with caching**
- Write `get_snapshots(domain) -> list[snapshot]` hitting the CDX API once per domain, and cache results in `website_snapshots` table with a `fetched_at` timestamp.
- Respect ~1 req/sec pacing; implement exponential backoff on 429s.
- Compute derived stats server-side from cached data (earliest/latest, count, per-year histogram, gaps) — never recompute by re-hitting CDX.

**Step 5.2 — On-demand snapshot fetch**
Only fetch actual HTML content (via Memento API, `web.archive.org/web/{timestamp}/{url}`) when a user asks a content question about a specific period — not for every snapshot in the index. Extract text, run through the same chunk/embed pipeline, tag chunks with `capture_timestamp` (not a "publish date").

**Step 5.3 — UI copy guardrail**
Anywhere you show "earliest snapshot," label it exactly that — never auto-phrase it as "website launched." Keep this as a literal string template, not something the LLM free-generates.

**Done when:** you can ask "when was this website first archived?" and "how many times was it archived in 2015?" and get correct cached answers without live CDX calls.

---

## Phase 6 — Evaluation harness

1. Hand-label 30–50 queries across your source types with expected relevant chunk IDs (tedious but essential — do this before you tune anything).
2. Run all 5 retrieval configs (vector-only → full hybrid+RRF+rerank) against the labeled set.
3. Compute Recall@10, nDCG@10, MRR automatically.
4. For faithfulness/citation-correctness, use an LLM-as-judge pass: does each cited chunk actually support its claim? Log disagreements for manual review.

**Done when:** you have a table showing config 5 (full pipeline) beating config 1 (vector-only) — this is your proof-of-concept artifact, keep it, you'll want it for writeups or demos.

---

## Phase 7 — Minimal UI

Build in this order, each is independently demoable:
1. Chat interface hitting your Phase 4 endpoint, rendering citations as clickable chips.
2. Source Explorer — list/filter view over `sources` table.
3. Timeline — simple bar chart of source count by year (Plotly), filterable by current query's retrieved sources.

Skip Document Viewer polish, Analytics Dashboard, and Historical Comparison UI until MVP is validated — they're additive, not blocking.

---

## Phase 8 — Deploy

- Dockerize app + Postgres + OpenSearch + Qdrant via Compose for a single-VM deploy first. Don't reach for Kubernetes until you have a reason to.
- Add a simple job queue (even just `arq` or Celery) for ingestion — it's slow, I/O-bound work that shouldn't block request threads.

---

## Immediate Next Action

Start Phase 0 + Phase 1.1–1.2 today: get the Advanced Search query working and pull real OCR text for your 20-item test set into Postgres. Everything else depends on having real data in front of you, and it'll surface IA's actual data quirks (missing OCR, weird date formats, mixed PD status) faster than any amount of planning will.
