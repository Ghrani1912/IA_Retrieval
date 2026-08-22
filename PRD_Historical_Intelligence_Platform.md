# PRD: Historical Intelligence & RAG Platform on Internet Archive

**Positioning:** An AI-powered historical information retrieval and reasoning platform that uses the Internet Archive to search, understand, analyze, and compare knowledge across documents, books, publications, websites, and other archived sources over time.

---

## 1. Feasibility Verdict

The core architecture (hybrid BM25 + vector + RRF + rerank, temporal filtering, evidence-grounded citation) is sound and matches current best practice in production RAG systems. The two components that need the most care are:

1. **Legal/access scope for in-copyright books.** IA's full-text is bulk-accessible mainly for public domain works (~pre-1928 US) and specific open collections (Project Gutenberg, government docs, some open-access papers). Post-1928 books are lending-controlled — you get metadata and search-inside snippets, not full text, without a library partnership. Scope this explicitly or the "books" module will silently fail on 80% of interesting 20th-century material.
2. **Wayback CDX rate limits.** ~60 req/min average, IP-level throttling since 2024. A "snapshot frequency" feature that hits CDX per-URL live is fine for single lookups but must NOT be your ingestion strategy for bulk website analysis — cache aggressively.

Everything else — metadata, OCR text for public-domain scans, newspaper/magazine collections, advanced search — is realistically buildable with IA's existing free, no-auth APIs.

---

## 2. Source-Type → API Feasibility Matrix

| Source type | Primary API | What you actually get | Constraint |
|---|---|---|---|
| Public-domain books | Advanced Search + Metadata API + `_djvu.txt` | Full OCR text, page images | Pre-~1928 (US) or explicitly PD-marked |
| In-copyright books | Advanced Search + Metadata API only | Metadata, search-inside snippets | No bulk full text without partnership |
| Research papers / gov docs | Advanced Search API | Full text, mostly open access | Generally clean, good MVP target |
| Magazines / newspapers | Advanced Search + collection-specific metadata | Full text where in relevant collection (e.g. `pulpmagazinearchive`) | Coverage is patchy by title/year |
| Archived websites | Wayback CDX API + Memento API | Snapshot list, timestamps, raw HTML per snapshot | Rate-limited; cache CDX results in your DB |
| Scanned/OCR docs | Metadata API (`_djvu.txt`, `_hocr.html`) | Pre-computed OCR, no need to re-OCR | OCR quality varies, esp. older scans |
| Images | Advanced Search (media type filter) + item metadata | Image files + captions/metadata | No image embeddings from IA — you build this |
| Audio/video | Advanced Search + Metadata API | Metadata only for MVP (transcripts rare) | Treat as metadata-only source in MVP |

---

## 3. MVP vs Phase 2 vs Phase 3

### MVP (built and demoable, ~6-10 weeks solo)
- **Source types:** public-domain books + research papers/gov docs + one website domain module (CDX-based).
- **Retrieval:** BM25 (OpenSearch) + vector search (Qdrant/FAISS) + metadata/temporal filters + RRF fusion. Reranker included — it's cheap to add and is one of your stated differentiators.
- **UI:** AI Research Chat + Source Explorer + basic Timeline. Skip Document Viewer polish and Analytics Dashboard for MVP.
- **Citation system:** DIRECTLY VERIFIED / INFERRED / UNKNOWN labeling — build this from day one, it's cheap and it's your credibility feature.
- **Evaluation:** Recall@K, nDCG, and a faithfulness check comparing the 3 retrieval configs (vector-only, BM25-only, hybrid+RRF+rerank) on ~30 hand-labeled queries.

### Phase 2
- Newspaper/magazine module, multi-domain website comparison, historical comparison mode (1980 vs 2020 style queries), Analytics Dashboard, full Document Viewer with page-level evidence.

### Phase 3 (genuinely "advanced," don't promise these for a first release)
- Multimodal (image embeddings + OCR fusion), knowledge graph/entity tracking across decades, website redesign diffing, custom OCR pipeline for uncovered scans, source reliability scoring, automated research reports.

---

## 4. Architecture

### 4.1 Ingestion pipeline (documents/books/papers/newspapers)

```
IA Advanced Search / Scraping API  (discovery: identifiers + metadata)
        |
Metadata API (per-item: dates, subjects, file list)
        |
Fetch _djvu.txt / _hocr.html (OCR text) or PDF where available
        |
Text cleaning (dehyphenation, OCR artifact removal, page markers preserved)
        |
Chunking (semantic/paragraph-aware, ~400-600 tokens, retain page + section anchor)
        |
   ┌────┴────┐
   |         |
Embeddings   Raw chunk text
(BGE-M3)     |
   |         |
Vector DB    OpenSearch/Elasticsearch (BM25 index)
(Qdrant)     |
   |_________|
        |
Structured metadata (title, author, date, identifier, collection) → PostgreSQL
```

### 4.2 Website / Wayback pipeline

```
Domain input
    |
CDX API query (cached in Postgres: snapshot_id, url, timestamp, status, digest)
    |
Compute: earliest/latest snapshot, count, snapshots/year, gaps, active years
    |
On-demand: fetch specific Memento snapshot HTML → extract text → same chunk/embed path
    |
Store snapshot-level chunks tagged with capture_timestamp (not publish date)
```

### 4.3 Query-time retrieval

```
User query
    |
Query understanding (LLM call): extract topic, date range, source-type hint
    |
   ┌─────────────┬─────────────┬──────────────────┐
Vector search   BM25 search   Metadata filter   Temporal filter
(top ~50)       (top ~50)     (date/type/domain) (date range)
   └─────────────┴─────────────┴──────────────────┘
        |
Reciprocal Rank Fusion (combine ranked lists)
        |
Cross-encoder reranker (BGE reranker) → top 8-12
        |
LLM synthesis with evidence blocks + citation metadata
        |
Answer with: claim → source → DIRECTLY VERIFIED / INFERRED / UNKNOWN tag
```

### 4.4 Storage summary

| Store | Contents |
|---|---|
| PostgreSQL | Item metadata, snapshot metadata, users, saved research collections |
| OpenSearch/Elasticsearch | BM25 full-text index, chunk-level |
| Qdrant (or FAISS for MVP) | Chunk embeddings + metadata payload for filtering |
| Object storage (S3-compatible) | Cached raw source files (djvu.txt, HTML snapshots, PDFs) — avoids re-hitting IA on every query |

---

## 5. Data Model (core tables, simplified)

```
sources(id, ia_identifier, source_type, title, author, publisher,
        pub_date, language, subject[], collection, ia_url)

chunks(id, source_id, text, page_or_section, embedding_id,
       capture_timestamp NULL, char_range)

website_snapshots(id, domain, url, snapshot_timestamp, status_code,
                   digest, fetched_flag)

evidence_citations(answer_id, chunk_id, confidence_label
                    ['directly_verified','inferred','unknown'])
```

---

## 6. Evaluation Plan

Compare 5 retrieval configs on a hand-built query set (~30-50 queries spanning book lookup, date-range filtering, website history, and cross-decade comparison):

1. Vector only
2. BM25 only
3. Vector + BM25 (simple merge)
4. + RRF
5. + Reranker (full pipeline)

Metrics: Recall@10, Precision@10, MRR, nDCG@10, plus LLM-judged faithfulness (does every claim trace to a cited chunk?) and citation correctness (does the cited chunk actually support the claim?).

---

## 7. Key Risks

| Risk | Mitigation |
|---|---|
| In-copyright book text unavailable in bulk | Scope MVP to PD + open-access sources; label restricted items as "metadata only" in UI |
| CDX/Wayback rate limits under load | Cache all CDX responses in Postgres; batch/backoff; never query CDX live per user request |
| OCR noise on older scans | Keep original scan image linked as evidence alongside text; don't silently "clean" text the LLM will cite |
| "Earliest archive date" ≠ "launch date" confusion | Enforce this distinction in both data model (separate fields) and UI copy — never let the LLM conflate them |
| IA API instability/outages (post-2024 breach, ongoing legal issues) | Object storage cache layer means a temporary IA outage degrades gracefully rather than breaking the app |

---

## 8. Suggested Stack (unchanged from your draft, validated as reasonable)

Backend: Python + FastAPI · Retrieval: OpenSearch + Qdrant · Embeddings: BGE-M3 · Reranker: BGE reranker · DB: PostgreSQL · Frontend: React/Next.js + Plotly/D3 · Deployment: Docker

---

## 9. Suggested Build Order

1. Ingestion pipeline for one source type (public-domain books) end-to-end, including chunking + embeddings + BM25 index.
2. Hybrid retrieval + RRF + reranker + citation-labeled LLM answer, evaluated against the 5-config comparison.
3. Website/CDX module with caching layer.
4. Research papers/gov docs source type (same pipeline, different ingestion adapter).
5. UI: chat + source explorer + timeline.
6. Phase 2 features only after MVP evaluation numbers are in hand.
