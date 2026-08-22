# Design Document: Historical Intelligence & RAG Platform

## Overview

The Historical Intelligence & RAG Platform is a multi-subsystem application that ingests public-domain books, research papers, government documents, and archived websites from the Internet Archive, indexes them for hybrid retrieval, and surfaces evidence-grounded LLM-synthesized answers with citation confidence labels.

The system is architected around three independently deployable subsystems — the Ingestion Pipeline, the Wayback Pipeline, and the Query/Answer Engine — backed by five storage services and coordinated through an async job queue. A React/Next.js frontend consumes a FastAPI REST API.

**Design objectives:**
- Never block HTTP request threads with I/O-bound ingestion work
- Never query the CDX API live per user request
- Never index full text from in-copyright sources
- Provide graceful degradation when IA or any backing service is unavailable
- Every answer claim traces to a specific chunk with a typed confidence label

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        React / Next.js UI                           │
│  Research Chat │ Source Explorer │ Timeline View                    │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTPS / REST
┌────────────────────────────▼────────────────────────────────────────┐
│                     FastAPI Application                              │
│  POST /query  │ GET /sources  │ POST /ingest  │ GET /health  │ …    │
└────┬──────────┬───────────────┬───────────────┬─────────────────────┘
     │          │               │               │
     ▼          ▼               ▼               ▼
┌─────────┐ ┌──────────┐  ┌─────────┐   ┌───────────────┐
│ Query & │ │  Source  │  │  Job    │   │  Health       │
│ Answer  │ │  Read    │  │  Enqueue│   │  Probe        │
│ Engine  │ │  Layer   │  │         │   │               │
└────┬────┘ └────┬─────┘  └────┬────┘   └───────────────┘
     │           │             │
     │           │        ┌────▼─────────────────────────────────────┐
     │           │        │           arq / Redis Job Queue          │
     │           │        │   Worker: discover→fetch→clean→chunk→    │
     │           │        │            embed→index                   │
     │           │        └────┬─────────────────────────────────────┘
     │           │             │
     │     ┌─────▼─────────────▼─────┐
     │     │      PostgreSQL          │
     │     │  sources, chunks,        │
     │     │  website_snapshots,      │
     │     │  evidence_citations,     │
     │     │  ingestion_jobs,         │
     │     │  eval_runs               │
     │     └─────────────────────────┘
     │
     ├──► OpenSearch (BM25 Index)
     ├──► Qdrant (Vector Index)
     ├──► MinIO (Object Cache — raw IA files)
     └──► LLM API (query understanding + answer synthesis)
```

### Component Summary

| Component | Technology | Responsibility |
|---|---|---|
| FastAPI App | Python 3.11, FastAPI | REST API, request routing, validation |
| Ingestion Worker | arq + Python | Async pipeline: discover→fetch→clean→chunk→embed→index |
| Wayback Worker | arq + Python | CDX cache population and on-demand Memento fetch |
| Query Engine | Python | Parallel BM25+vector retrieval, RRF, reranking |
| Answer Synthesizer | Python + LLM | Evidence-grounded answer generation, citation labeling |
| PostgreSQL | PostgreSQL 15 | Relational metadata, job state, citation records |
| OpenSearch | OpenSearch 2.x | BM25 full-text index over chunks |
| Qdrant | Qdrant 1.x | Vector embedding index with metadata payloads |
| MinIO | MinIO (S3-compatible) | Object cache for raw IA source files |
| Redis | Redis 7 | arq job queue backend |

---

## Components and Interfaces

### 2.1 Ingestion Pipeline

**Module path:** `app/ingestion/`

**Public functions:**
```python
def discover(query: str, date_range: tuple[str, str], media_type: str) -> list[SourceMetadata]
def fetch_fulltext(identifier: str) -> str | None
def clean_text(raw: str) -> CleanedText
def chunk_text(cleaned: CleanedText, source_id: int) -> list[Chunk]
def embed_chunks(chunks: list[Chunk]) -> list[ChunkWithEmbedding]
def index_bm25(chunks: list[Chunk]) -> None
def index_vectors(chunks: list[ChunkWithEmbedding]) -> None
def serialize_chunk(chunk: Chunk) -> dict
def deserialize_chunk(data: dict) -> Chunk
```

**Job entrypoint:**
```python
async def run_ingestion_job(job_id: str, query: str, date_range: tuple, source_type: str) -> None
```

### 2.2 Wayback Pipeline

**Module path:** `app/wayback/`

**Public functions:**
```python
def get_snapshots(domain: str) -> list[SnapshotRecord]
def compute_snapshot_stats(domain: str) -> SnapshotStats
async def fetch_snapshot_content(url: str, snapshot_timestamp: str) -> str | None
```

### 2.3 Query Engine

**Module path:** `app/retrieval/`

**Public functions:**
```python
async def understand_query(raw_query: str) -> StructuredQuery
async def retrieve_bm25(query: StructuredQuery) -> list[RankedChunk]
async def retrieve_vector(query: StructuredQuery) -> list[RankedChunk]
def fuse_rrf(bm25_results: list[RankedChunk], vector_results: list[RankedChunk]) -> list[RankedChunk]
def rerank(query: str, candidates: list[RankedChunk]) -> list[RankedChunk]
```

### 2.4 Answer Synthesizer

**Module path:** `app/synthesis/`

**Public functions:**
```python
async def synthesize_answer(query: str, evidence: list[RankedChunk]) -> AnswerResponse
def format_answer(answer: AnswerResponse) -> str
def parse_answer(raw: str) -> AnswerResponse
async def persist_citations(answer: AnswerResponse) -> None
```

### 2.5 Evaluation Harness

**Module path:** `app/eval/`

**Public functions:**
```python
def run_eval(labeled_queries: list[LabeledQuery], config: RetrievalConfig) -> EvalResults
def compute_metrics(results: list[RetrievalResult], ground_truth: list[GroundTruth]) -> RetrievalMetrics
def judge_faithfulness(answer: AnswerResponse, chunks: list[Chunk]) -> list[FaithfulnessVerdict]
def compute_citation_correctness(verdicts: list[FaithfulnessVerdict]) -> float
```

---

## Data Models

### 3.1 PostgreSQL Schema

```sql
-- Sources: one row per IA item (book, paper, gov doc, or website snapshot set)
CREATE TABLE sources (
    id              SERIAL PRIMARY KEY,
    ia_identifier   TEXT NOT NULL UNIQUE,
    source_type     TEXT NOT NULL CHECK (source_type IN (
                        'book', 'paper', 'gov_doc', 'magazine',
                        'newspaper', 'website', 'metadata_only', 'fetch_failed'
                    )),
    title           TEXT,
    author          TEXT,
    publisher       TEXT,
    pub_date        DATE,
    language        TEXT,
    subject         TEXT[],
    collection      TEXT,
    ia_url          TEXT,
    is_open_access  BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Chunks: text segments produced by the chunker
CREATE TABLE chunks (
    id                  SERIAL PRIMARY KEY,
    source_id           INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    text                TEXT NOT NULL,
    page_or_section     TEXT,
    embedding_id        TEXT,            -- Qdrant point ID
    capture_timestamp   TIMESTAMPTZ,     -- non-null for web snapshot chunks only
    char_range_start    INTEGER NOT NULL,
    char_range_end      INTEGER NOT NULL,
    token_count         INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_source_id ON chunks(source_id);
CREATE INDEX idx_chunks_capture_timestamp ON chunks(capture_timestamp);

-- Website snapshots: CDX cache rows (one per Wayback snapshot)
CREATE TABLE website_snapshots (
    id                  SERIAL PRIMARY KEY,
    domain              TEXT NOT NULL,
    url                 TEXT NOT NULL,
    snapshot_timestamp  TIMESTAMPTZ NOT NULL,
    status_code         INTEGER,
    digest              TEXT,
    fetched_flag        BOOLEAN NOT NULL DEFAULT false,
    fetched_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (url, snapshot_timestamp)
);
CREATE INDEX idx_snapshots_domain ON website_snapshots(domain);
CREATE INDEX idx_snapshots_fetched_flag ON website_snapshots(domain, fetched_flag);

-- Evidence citations: one row per answer segment
CREATE TABLE evidence_citations (
    id                  SERIAL PRIMARY KEY,
    answer_id           TEXT NOT NULL,
    chunk_id            INTEGER NOT NULL REFERENCES chunks(id),
    confidence_label    TEXT NOT NULL CHECK (confidence_label IN (
                            'directly_verified', 'inferred', 'unknown'
                        )),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_citations_answer_id ON evidence_citations(answer_id);

-- Ingestion jobs: tracks async job status and progress
CREATE TABLE ingestion_jobs (
    id              TEXT PRIMARY KEY,    -- UUID generated at enqueue time
    query           TEXT NOT NULL,
    date_range_from DATE,
    date_range_to   DATE,
    source_type     TEXT,
    status          TEXT NOT NULL CHECK (status IN (
                        'queued', 'running', 'completed', 'failed'
                    )) DEFAULT 'queued',
    sources_total   INTEGER,
    sources_done    INTEGER DEFAULT 0,
    chunks_created  INTEGER DEFAULT 0,
    error_step      TEXT,
    error_msg       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Evaluation runs: persisted benchmark results
CREATE TABLE eval_runs (
    id                      SERIAL PRIMARY KEY,
    config_name             TEXT NOT NULL,
    recall_10               FLOAT,
    precision_10            FLOAT,
    mrr                     FLOAT,
    ndcg_10                 FLOAT,
    citation_correctness    FLOAT,
    query_count             INTEGER,
    run_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 3.2 Python Data Models (Pydantic)

```python
class SourceMetadata(BaseModel):
    ia_identifier: str
    title: str | None
    author: str | None
    publisher: str | None
    pub_date: date | None
    language: str | None
    subject: list[str] = []
    collection: str | None
    ia_url: str | None

class Chunk(BaseModel):
    id: int | None
    source_id: int
    text: str
    page_or_section: str | None
    embedding_id: str | None
    capture_timestamp: datetime | None   # only for web snapshot chunks
    char_range_start: int
    char_range_end: int
    token_count: int | None

class AnswerSegment(BaseModel):
    text: str
    citation_type: Literal["DIRECTLY_VERIFIED", "INFERRED", "UNKNOWN"]
    source_ids: list[str]
    chunk_ids: list[int]

class AnswerResponse(BaseModel):
    answer_id: str
    query: str
    answer_segments: list[AnswerSegment]
    retrieved_chunks: list[Chunk]

class StructuredQuery(BaseModel):
    raw_query: str
    topic_keywords: list[str]
    date_range_start: int | None    # year
    date_range_end: int | None      # year
    source_type_hint: str | None
    is_temporal_comparison: bool = False

class SnapshotRecord(BaseModel):
    domain: str
    url: str
    snapshot_timestamp: datetime
    status_code: int | None
    digest: str | None
    fetched_flag: bool = False

class SnapshotStats(BaseModel):
    domain: str
    earliest: datetime | None
    latest: datetime | None
    total_count: int
    per_year: dict[int, int]    # year -> count
    gap_years: list[int]        # years with zero snapshots within active range

class RetrievalMetrics(BaseModel):
    recall_10: float
    precision_10: float
    mrr: float
    ndcg_10: float

class FaithfulnessVerdict(BaseModel):
    answer_id: str
    claim_text: str
    chunk_id: int
    verdict: Literal["supported", "not_supported"]
```

### 3.3 OpenSearch Index Mapping

```json
{
  "mappings": {
    "properties": {
      "chunk_id":      { "type": "integer" },
      "source_id":     { "type": "integer" },
      "ia_identifier": { "type": "keyword" },
      "text":          { "type": "text", "analyzer": "english" },
      "date":          { "type": "date", "format": "yyyy-MM-dd||yyyy" },
      "source_type":   { "type": "keyword" },
      "collection":    { "type": "keyword" },
      "language":      { "type": "keyword" },
      "capture_timestamp": { "type": "date" }
    }
  }
}
```

### 3.4 Qdrant Collection Schema

```python
# Collection: "chunks"
# Vector dimension: 1024  (BGE-M3 output)
# Distance: Cosine
# Payload fields (all filterable):
#   source_id: int
#   ia_identifier: str
#   date: str (ISO)
#   source_type: str
#   collection: str
#   capture_timestamp: str | null
#   chunk_db_id: int   (foreign key back to chunks.id)
```

---

## API Design

### 4.1 POST /query

**Request:**
```json
{
  "query": "What did researchers believe about artificial intelligence in the 1980s?",
  "filters": {
    "date_range": { "from": 1975, "to": 1995 },
    "source_type": "paper",
    "collection": null
  }
}
```

**Response (200):**
```json
{
  "answer_id": "ans_01HZ...",
  "query": "What did researchers believe...",
  "answer_segments": [
    {
      "text": "In the early 1980s, researchers widely believed...",
      "citation_type": "DIRECTLY_VERIFIED",
      "source_ids": ["minsky1981frames"],
      "chunk_ids": [4821]
    },
    {
      "text": "This optimism later gave way to a period of reduced funding...",
      "citation_type": "INFERRED",
      "source_ids": ["minsky1981frames", "lighthill1973report"],
      "chunk_ids": [4821, 3092]
    }
  ],
  "retrieved_chunks": [
    {
      "id": 4821,
      "source_id": 77,
      "text": "Frames provide a means of representing...",
      "page_or_section": "42",
      "capture_timestamp": null,
      "char_range_start": 18430,
      "char_range_end": 19120
    }
  ]
}
```

**Error (422):** Standard FastAPI validation error body.
**Error (500):** `{ "error": "synthesis_failed", "detail": "..." }`

### 4.2 GET /sources

**Query params:** `source_type`, `collection`, `date_from` (YYYY), `date_to` (YYYY), `language`, `page` (default 1), `page_size` (default 50, max 100)

**Response (200):**
```json
{
  "items": [
    {
      "id": 77,
      "ia_identifier": "minsky1981frames",
      "source_type": "paper",
      "title": "A Framework for Representing Knowledge",
      "author": "Minsky, Marvin",
      "pub_date": "1974",
      "collection": "nasa",
      "ia_url": "https://archive.org/details/minsky1981frames",
      "chunk_count": 83
    }
  ],
  "total": 1243,
  "page": 1,
  "page_size": 50
}
```

### 4.3 GET /sources/{ia_identifier}

**Response (200):**
```json
{
  "id": 77,
  "ia_identifier": "minsky1981frames",
  "source_type": "paper",
  "title": "A Framework for Representing Knowledge",
  "author": "Minsky, Marvin",
  "publisher": "MIT AI Lab",
  "pub_date": "1974-01-01",
  "language": "en",
  "subject": ["artificial intelligence", "knowledge representation"],
  "collection": "nasa",
  "ia_url": "https://archive.org/details/minsky1981frames",
  "is_open_access": true,
  "chunk_count": 83
}
```

**Error (404):** `{ "error": "not_found" }`

### 4.4 POST /ingest

**Request:**
```json
{
  "query": "subject:\"artificial intelligence\" AND date:[1975-01-01 TO 1990-12-31]",
  "date_range": { "from": "1975-01-01", "to": "1990-12-31" },
  "source_type": "paper"
}
```

**Response (202):**
```json
{ "job_id": "job_01HZ..." }
```

### 4.5 GET /ingest/{job_id}/status

**Response (200):**
```json
{
  "job_id": "job_01HZ...",
  "status": "running",
  "sources_total": 87,
  "sources_done": 34,
  "chunks_created": 4102,
  "error_step": null,
  "error_msg": null,
  "created_at": "2024-01-15T10:22:00Z",
  "updated_at": "2024-01-15T10:24:13Z"
}
```

### 4.6 GET /snapshots/{domain}

**Response (200) — served from CDX cache only:**
```json
{
  "domain": "example.com",
  "earliest": "1996-11-01T00:00:00Z",
  "latest": "2024-06-15T12:30:00Z",
  "total_count": 2847,
  "per_year": { "1996": 3, "1997": 12, "1998": 47, "...": "..." },
  "gap_years": [2001, 2002]
}
```

**Error (404):** Domain not yet ingested — `{ "error": "domain_not_cached" }`

### 4.7 GET /health

**Response (200):**
```json
{
  "status": "healthy",
  "services": {
    "postgres":    { "status": "ok",   "latency_ms": 2 },
    "opensearch":  { "status": "ok",   "latency_ms": 8 },
    "qdrant":      { "status": "ok",   "latency_ms": 5 },
    "minio":       { "status": "ok",   "latency_ms": 3 },
    "redis":       { "status": "ok",   "latency_ms": 1 }
  }
}
```

**Response (503) when any service is down:**
```json
{
  "status": "degraded",
  "services": {
    "postgres":   { "status": "ok",   "latency_ms": 2 },
    "opensearch": { "status": "error", "error": "connection refused" },
    "...": "..."
  }
}
```

---

## Ingestion Pipeline Flow

```
POST /ingest
    │
    ▼
enqueue_job(job_id, query, date_range, source_type) → Redis
    │
    ▼
[Worker process — arq]
    │
    ├─ Step 1: discover()
    │   ├─ GET /advancedsearch.php?q=...&rows=100&page=1,2,...
    │   ├─ Upsert each result to sources table by ia_identifier
    │   └─ Update job: sources_total = N
    │
    ├─ Step 2: Copyright scope check (per source) — see Addendum A.2 for full logic
    │   ├─ Check IA rights/licenseurl metadata field first (CC or publicdomain → allow; in-copyright → block)
    │   ├─ Check collection against OPEN_ACCESS_COLLECTIONS frozenset (see Addendum A.3)
    │   ├─ Fall back to date heuristic: parse_pub_date() → compare against pd_cutoff_year() = today.year - 96
    │   ├─ NULL or unparseable pub_date → metadata_only (safe default; see Addendum A.4)
    │   ├─ Set sources.is_open_access based on outcome
    │   └─ If metadata_only: skip to next source without calling fetch_fulltext
    │
    ├─ Step 3: fetch_fulltext()
    │   ├─ Check Object_Cache (MinIO): GET /{ia_identifier}/raw.txt
    │   │   └─ Cache hit → return cached content directly
    │   ├─ Cache miss → GET /metadata/{ia_identifier} → find _djvu.txt or _hocr.html
    │   ├─ Download file, PUT to Object_Cache
    │   └─ Return text | None (metadata_only if no OCR file)
    │
    ├─ Step 4: clean_text()
    │   ├─ Detect and strip running headers/footers (line frequency analysis)
    │   ├─ Rejoin hyphenated line-break words
    │   ├─ Convert form-feed characters → page markers (e.g., "\x0c" → "[[PAGE:N]]")
    │   └─ Return CleanedText with page_markers: list[tuple[int, int]]
    │
    ├─ Step 5: chunk_text()
    │   ├─ Split by paragraph boundaries (double newline or [[PAGE]] marker)
    │   ├─ Merge paragraphs into chunks targeting 500 tokens (±100)
    │   ├─ Apply 15% token overlap between adjacent chunks
    │   ├─ Record source_id, page_or_section, char_range_start, char_range_end
    │   └─ Write chunk rows to PostgreSQL
    │
    ├─ Step 6: embed_chunks()
    │   ├─ Batch embed chunk texts with BGE-M3 (batch size 32)
    │   └─ Return list[ChunkWithEmbedding]
    │
    ├─ Step 7: index_vectors()
    │   ├─ Delete existing Qdrant points for ia_identifier (if re-ingesting)
    │   ├─ Upsert embeddings to Qdrant with metadata payload
    │   └─ Update chunks.embedding_id with returned Qdrant point IDs
    │
    ├─ Step 8: index_bm25()
    │   ├─ Delete existing OpenSearch docs for ia_identifier (if re-ingesting)
    │   └─ Bulk index chunks to OpenSearch
    │
    └─ Update job: status='completed', chunks_created=N, updated_at=now()
```

**Error handling per step:** Any unhandled exception sets `job.status='failed'`, `job.error_step`, `job.error_msg` and stops processing for that source. Other sources in the same job continue.

---

## Wayback Pipeline Flow

### 7.1 CDX Cache Population (Ingestion)

```
POST /ingest  (source_type = 'website')
    │
    ▼
[Worker — Wayback ingestion job]
    │
    ├─ Check website_snapshots WHERE domain = ? AND fetched_at > now() - 24h
    │   └─ Cache fresh → return cached records, skip CDX call
    │
    ├─ CDX API: GET https://web.archive.org/cdx/search/cdx?url={domain}/*&output=json
    │   ├─ Rate limit: 1 req/sec (asyncio.sleep(1) between pages)
    │   ├─ On 429: exponential backoff starting at 2s, up to 5 retries
    │   └─ Paginate using &limit=10000&from=&to= until all snapshots returned
    │
    ├─ Upsert snapshot rows to website_snapshots
    │   (domain, url, snapshot_timestamp, status_code, digest, fetched_flag=false)
    │
    └─ Compute and cache snapshot stats from DB records (no re-query to CDX)
```

### 7.2 On-Demand Snapshot Content Fetch

```
POST /query  (implies a specific domain and time period)
    │
    ▼
Retrieval_Engine identifies relevant (url, snapshot_timestamp) pairs
    │
    ├─ Check fetched_flag for each snapshot
    │   └─ fetched_flag=true → use existing chunks from PostgreSQL, skip
    │
    ├─ Memento API: GET https://web.archive.org/web/{timestamp}/{url}
    │   └─ Extract main text content (strip nav, ads, boilerplate via readability)
    │
    ├─ Run extracted text through clean_text() → chunk_text() → embed_chunks()
    │   └─ IMPORTANT: capture_timestamp = snapshot_timestamp, pub_date = NULL
    │
    ├─ Index chunks to OpenSearch + Qdrant
    │
    └─ Update website_snapshots: fetched_flag=true, fetched_at=now()
```

---

## Query-Time Retrieval Flow

```
POST /query → {query, filters}
    │
    ▼
Step 1: understand_query(raw_query) — LLM call
    │   Input: raw query string
    │   Output: StructuredQuery {topic_keywords, date_range, source_type_hint, ...}
    │   Fallback: if LLM fails → StructuredQuery with raw_query as topic, no filters
    │
    ▼
Step 2: Pre-fusion filter construction
    │   date_range filter → applied to both OpenSearch (range on `date` field) and
    │                       Qdrant (filter on date payload)
    │   source_type filter → keyword match in both indexes
    │   Exclude source_type = 'metadata_only' from all queries
    │
    ▼
Step 3: Parallel retrieval (asyncio.gather)
    ├─ BM25 query → OpenSearch.search(text=topic_keywords, filters=..., top_k=50)
    │   Returns: list[RankedChunk] with rank 1..50
    └─ Vector query → embed(topic_keywords) → Qdrant.search(vector=..., filters=..., top_k=50)
        Returns: list[RankedChunk] with rank 1..50
    │
    ▼
Step 4: RRF fusion
    │   score(chunk) = Σ 1/(60 + rank_i)  for each list where chunk appears
    │   Sort descending by score → top 30 candidates
    │
    ▼
Step 5: Reranking
    │   BGE cross-encoder: score(query, chunk_text) for each of top 30
    │   Sort descending → top 8–12 evidence chunks
    │   Fallback: if reranker unavailable → return top 8–12 from RRF list
    │
    ▼
Step 6: Answer synthesis (see next section)
```

---

## Answer Synthesis and Citation Flow

```
evidence_chunks: list[RankedChunk]  (8–12 items)
    │
    ▼
Build LLM prompt:
    System: "Answer only from provided evidence. Tag each claim.
             For website sources, use 'first archived' not 'launched'."
    Evidence block per chunk:
        "[SOURCE {i}] Title: {title} | Author: {author} | Date: {pub_date or capture_timestamp}
         Identifier: {ia_identifier} | Page: {page_or_section}
         ---
         {chunk.text}"
    Instruction:
        "Return JSON: {answer_segments: [{text, citation_type, source_ids}]}
         citation_type must be exactly one of: DIRECTLY_VERIFIED, INFERRED, UNKNOWN"
    │
    ▼
LLM API call → raw JSON string
    │
    ├─ Parse with parse_answer(raw) → AnswerResponse
    │   └─ On parse failure: raise AnswerParseError, log raw output, return HTTP 500
    │
    ├─ Check for "launched" in web-source answer segments
    │   └─ If found: set warning flag on segment (for UI to render warning)
    │
    ├─ Persist citations:
    │   INSERT INTO evidence_citations (answer_id, chunk_id, confidence_label)
    │   One row per (answer_segment, chunk_id) pair
    │
    └─ Return AnswerResponse to caller
```

**Prompt template (literal string — not LLM-generated):**
```python
SYSTEM_PROMPT = """You are a historical research assistant. Answer questions using ONLY
the provided evidence chunks. Do not draw on external knowledge.

For each claim in your answer:
- Tag as DIRECTLY_VERIFIED if it is directly stated in a single evidence chunk
- Tag as INFERRED if it synthesizes across multiple chunks without direct quotation  
- Tag as UNKNOWN if the evidence does not support the claim

For website sources: always write "first archived" or "earliest snapshot date" —
never write "launched" or "went live".

Return valid JSON matching this schema exactly:
{"answer_segments": [{"text": "...", "citation_type": "...", "source_ids": ["..."]}]}"""
```

---

## Evaluation Harness Design

### 9.1 Structure

```
app/eval/
├── queries.json         # 30–50 labeled queries with expected chunk IDs
├── run_eval.py          # CLI entry point
├── configs.py           # 5 retrieval config definitions
├── metrics.py           # Recall@K, Precision@K, MRR, nDCG@K
└── judge.py             # LLM-as-judge faithfulness check
```

### 9.2 Labeled Query Format

```json
{
  "queries": [
    {
      "id": "q001",
      "query": "What were the main arguments in the AI winter debate of the late 1980s?",
      "query_type": "date_range_filtering",
      "relevant_chunk_ids": [3092, 3105, 3211, 4821],
      "date_range": { "from": 1985, "to": 1995 }
    }
  ]
}
```

**Query types (minimum 4 required):**
1. `book_lookup` — query that should retrieve a specific known book
2. `date_range_filtering` — query with an explicit time constraint
3. `website_history` — query about a domain's archive history
4. `cross_decade_comparison` — query comparing two time periods

### 9.3 Five Retrieval Configs

| Config | Name | Description |
|---|---|---|
| 1 | `vector_only` | Qdrant top-10, no BM25, no fusion, no rerank |
| 2 | `bm25_only` | OpenSearch top-10, no vector, no fusion, no rerank |
| 3 | `simple_merge` | Qdrant top-50 + OpenSearch top-50, interleave by score, no RRF |
| 4 | `rrf` | Qdrant top-50 + OpenSearch top-50, RRF fusion, top-10, no rerank |
| 5 | `full_pipeline` | Config 4 + BGE cross-encoder rerank → top 8–12 |

### 9.4 Metric Formulas

```python
# Recall@K: fraction of relevant chunks appearing in top-K results
recall_k = len(relevant ∩ retrieved[:K]) / len(relevant)

# Precision@K: fraction of top-K results that are relevant
precision_k = len(relevant ∩ retrieved[:K]) / K

# MRR: reciprocal of rank of first relevant result
mrr = 1 / rank_of_first_relevant  (0 if none in top-K)

# nDCG@K: normalized discounted cumulative gain
dcg_k = Σ rel_i / log2(i+1)  for i in 1..K
ndcg_k = dcg_k / ideal_dcg_k
```

### 9.5 Faithfulness Evaluation

```python
# For each (answer_segment, cited_chunk) pair:
# LLM judge prompt:
JUDGE_PROMPT = """Does the following chunk support the claim?
Claim: {claim_text}
Chunk: {chunk_text}
Answer with exactly: supported | not_supported"""

# Aggregate:
citation_correctness_rate = len(supported) / len(total_pairs)
# Emit warning if rate < 0.8
```

### 9.6 Results Persistence

```python
INSERT INTO eval_runs (config_name, recall_10, precision_10, mrr, ndcg_10,
                       citation_correctness, query_count, run_at)
VALUES (?, ?, ?, ?, ?, ?, ?, now())
```

---

## UI Component Structure

```
app/frontend/
├── pages/
│   ├── index.tsx             # Research Chat (main page)
│   ├── sources/
│   │   ├── index.tsx         # Source Explorer
│   │   └── [ia_identifier].tsx  # Source detail page
│   └── timeline.tsx          # Timeline view
├── components/
│   ├── chat/
│   │   ├── ChatInput.tsx     # Query input + submit button
│   │   ├── AnswerSegment.tsx # Renders one answer segment + citation chips
│   │   ├── CitationChip.tsx  # Inline chip: title, author, year, confidence label
│   │   └── ChunkDrawer.tsx   # Slide-in panel: full chunk text + source metadata
│   ├── sources/
│   │   ├── SourceTable.tsx   # Paginated source list with filter controls
│   │   ├── SourceCard.tsx    # Single source row/card with metadata badge
│   │   └── FilterBar.tsx     # source_type, collection, date range, language filters
│   └── timeline/
│       ├── TimelineChart.tsx # Plotly/D3 bar chart grouped by year
│       └── YearFilter.tsx    # Brush or date range selector on chart
├── lib/
│   ├── api.ts                # Typed API client (fetch wrappers)
│   └── types.ts              # TypeScript interfaces matching Pydantic models
└── styles/
    └── globals.css
```

### 10.1 Research Chat Component Behavior

- On submit: POST /query → show skeleton loader → render answer segments
- Each `AnswerSegment` renders inline `CitationChip` components
- `CitationChip` color coding:
  - `DIRECTLY_VERIFIED`: green background
  - `INFERRED`: yellow/amber background
  - `UNKNOWN`: gray background with italic text
- Click `CitationChip` → open `ChunkDrawer` (slide-in panel)
- `ChunkDrawer` shows: chunk text, source title/author/date, ia_url link
- For web snapshot chunks: display `capture_timestamp` as "Archived on {date}" — never "Published"
- Prevent duplicate submission while loading (disable input + button)

### 10.2 Source Explorer

- Default: all sources, page 1, sorted by pub_date desc
- `FilterBar` controls update URL query params → triggers API refetch
- `metadata_only` sources display "Full text unavailable" badge (gray)
- `fetch_failed` sources display "Fetch failed" badge (red)
- Source detail page shows chunk_count for non-metadata_only sources

### 10.3 Timeline View

- Renders after a query is submitted, using `retrieved_chunks` from answer
- X-axis: years spanning earliest–latest in result set
- Y-axis: source count per year
- Zero-height bars (or gaps) for years with no sources — never hidden
- Web source charts: axis label = "Year Archived" not "Year Published"
- Bar click → filter Source Explorer to that year
- Date range brush → propagates to active query filter context

---

## Deployment Architecture

### 11.1 Docker Compose Services

```yaml
services:

  app:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }
      opensearch: { condition: service_healthy }
      qdrant: { condition: service_healthy }
      minio: { condition: service_healthy }
      redis: { condition: service_healthy }
    command: >
      sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"

  worker:
    build: .
    env_file: .env
    depends_on: [redis, postgres, opensearch, qdrant, minio]
    command: python -m arq app.jobs.WorkerSettings

  postgres:
    image: postgres:15
    volumes: [postgres_data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 5s
      retries: 10

  opensearch:
    image: opensearchproject/opensearch:2.11.0
    environment:
      - discovery.type=single-node
      - "OPENSEARCH_JAVA_OPTS=-Xms1g -Xmx1g"
    deploy:
      resources:
        limits: { memory: 2G, cpus: "2.0" }
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9200/_cluster/health"]

  qdrant:
    image: qdrant/qdrant:v1.7.0
    volumes: [qdrant_data:/qdrant/storage]
    deploy:
      resources:
        limits: { memory: 2G, cpus: "2.0" }
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    volumes: [minio_data:/data]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]

volumes:
  postgres_data:
  qdrant_data:
  minio_data:
```

### 11.2 Environment Variables

```ini
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/platform

# OpenSearch
OPENSEARCH_URL=http://opensearch:9200
OPENSEARCH_INDEX=chunks

# Qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=chunks

# MinIO / Object storage
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET=ia-cache

# Redis (arq)
REDIS_URL=redis://redis:6379

# LLM
LLM_API_KEY=...
LLM_MODEL=gpt-4o-mini   # or any OpenAI-compatible endpoint
LLM_BASE_URL=https://api.openai.com/v1

# Embeddings
EMBEDDING_MODEL=BAAI/bge-m3
RERANKER_MODEL=BAAI/bge-reranker-v2-m3

# Internet Archive
IA_BASE_URL=https://archive.org
CDX_RATE_LIMIT_RPS=1
```

---

## Error Handling

### 12.1 Ingestion Failures

| Failure | Handling |
|---|---|
| IA API HTTP error | Retry 3× with exponential backoff (2s, 4s, 8s); mark source `fetch_failed` after exhaustion |
| No OCR file found | Return None, mark `metadata_only`; never raise exception |
| Object cache write failure | Log warning, continue with in-memory content for current run |
| Object cache unavailable | Fall back to direct IA fetch; log cache-miss warning |
| OpenSearch bulk index failure | Log failed chunk IDs, retry batch once; mark source `index_failed` |
| Qdrant upsert failure | Log failed point IDs, retry batch once; mark source `index_failed` |
| Job-level exception | Set `job.status='failed'`, `job.error_step`, `job.error_msg`; continue other sources |

### 12.2 Query-Time Failures

| Failure | Handling |
|---|---|
| LLM query understanding timeout | Fall back to raw query string with no extracted filters; log failure |
| BM25 retrieval failure | Proceed with vector results only; log failure; do not return HTTP error |
| Vector retrieval failure | Proceed with BM25 results only; log failure |
| Both retrievals fail | Return HTTP 503 with `{"error": "retrieval_unavailable"}` |
| Reranker unavailable | Fall back to top 8–12 from RRF list; log fallback |
| LLM synthesis failure / JSON parse error | Return HTTP 500 with `{"error": "synthesis_failed", "detail": "..."}` |

### 12.3 CDX / Wayback Failures

| Failure | Handling |
|---|---|
| CDX 429 (rate limit) | Exponential backoff from 2s; up to 5 retries |
| CDX domain not cached | Return HTTP 404 `{"error": "domain_not_cached"}` — never trigger live CDX from user request |
| Memento fetch failure | Log and skip that snapshot; fetched_flag remains false |

### 12.4 Data Integrity Guardrails

- `capture_timestamp` and `pub_date` are never set together on the same chunk
- `confidence_label` is enforced by PostgreSQL CHECK constraint and Pydantic validation
- Metadata-only sources are excluded from retrieval at the query level via an OpenSearch/Qdrant filter
- Re-ingestion always deletes existing index entries before inserting new ones (prevents stale duplicates)
- The SYSTEM_PROMPT for answer synthesis is a literal string constant — never dynamically generated

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Chunk Serialization Round-Trip

*For any* valid `Chunk` object, serializing it with `serialize_chunk` and then deserializing the result with `deserialize_chunk` SHALL produce a `Chunk` object equal to the original in all fields.

**Validates: Requirements 29.3**

### Property 2: Answer Serialization Round-Trip

*For any* valid `AnswerResponse` object, formatting it with `format_answer` and then parsing the result with `parse_answer` SHALL produce an `AnswerResponse` equal to the original in all fields.

**Validates: Requirements 29.4**

### Property 3: Chunk Coverage Invariant

*For any* source text passed to `chunk_text`, the union of all `(char_range_start, char_range_end)` intervals in the returned chunks SHALL cover the full character span of the input text with no gap larger than the overlap window (15% of chunk size).

**Validates: Requirements 5.5**

### Property 4: Chunker Metadata Completeness

*For any* source text and source ID passed to `chunk_text`, every returned `Chunk` SHALL have `source_id`, `page_or_section`, `char_range_start`, and `char_range_end` populated with non-null values.

**Validates: Requirements 5.3**

### Property 5: RRF Score Formula Correctness

*For any* two ranked candidate lists (BM25 top-50 and vector top-50), `fuse_rrf` SHALL assign each chunk an RRF score equal to the sum of `1 / (60 + rank_i)` over every list in which the chunk appears, and the returned list SHALL contain the top 30 chunks sorted by descending score.

**Validates: Requirements 14.1, 14.2, 14.3, 14.4**

### Property 6: Filter Builder Always Excludes Metadata-Only Sources

*For any* call to `build_opensearch_filter` or `build_qdrant_filter`, regardless of the query parameters provided, the returned filter object SHALL include a clause that excludes documents with `source_type = 'metadata_only'`.

*Note: This property tests the filter construction logic, not end-to-end retrieval quality. Whether the correct chunks are retrieved for a given query is evaluated by the Phase 6 eval harness.*

**Validates: Requirements 10.3, 26.1**

### Property 7: Copyright Scope Enforcement

*Superseded by Addendum A.5.* The original formulation hardcoded a 1928 cutoff and left `OPEN_ACCESS_COLLECTIONS` undefined. See **Addendum A.5** for the revised, testable property that uses `pd_cutoff_year()`, the `open_access_collections.json` artifact, and explicit NULL-date handling.

**Validates: Requirements 26.1, 26.2, 26.3, 10.1**

### Property 8: CDX Cache-Only Statistics

*For any* domain whose snapshot statistics are requested via `GET /snapshots/{domain}`, the returned `SnapshotStats` values (earliest, latest, total_count, per_year, gap_years) SHALL be exactly derivable from the rows in `website_snapshots` for that domain — no difference is permitted between statistics computed from the cache and statistics that would result from a live CDX query.

**Validates: Requirements 8.6, 8.7**

### Property 9: Web Chunk capture_timestamp Invariant

*For any* chunk produced by the Wayback Pipeline from an HTML snapshot, `capture_timestamp` SHALL be non-null and equal to the Wayback snapshot timestamp, and `pub_date` / `pub_date`-equivalent fields SHALL be null.

**Validates: Requirements 9.5, 18.1**

### Property 10: Discover Idempotence (Upsert)

*For any* discovery query run twice against the same IA Advanced Search result set, the `sources` table SHALL contain the same number of rows after both runs as after the first run — the second run SHALL NOT create duplicate rows for any `ia_identifier`.

**Validates: Requirements 2.5**

### Property 11: Object Cache Read-Through

*For any* `ia_identifier` that has been previously fetched (file exists in Object_Cache), a subsequent call to `fetch_fulltext(identifier)` SHALL return the cached content without issuing any network request to IA.

**Validates: Requirements 3.4, 19.2**

### Property 12: Object Cache Write-Before-Return

*For any* `ia_identifier` whose raw file is successfully downloaded from IA, the file SHALL be present in the Object_Cache before `fetch_fulltext` returns the text content.

**Validates: Requirements 3.3, 19.1**

### Property 13: BM25 Index Idempotence on Re-Ingestion

*For any* source, ingesting it twice SHALL produce the same number of OpenSearch documents for that `ia_identifier` as ingesting it once — re-ingestion SHALL delete existing documents before inserting new ones.

**Validates: Requirements 6.4**

### Property 14: Vector Index Idempotence on Re-Ingestion

*For any* source, ingesting it twice SHALL produce the same number of Qdrant points for that source as ingesting it once — re-ingestion SHALL delete existing points before inserting new ones.

**Validates: Requirements 7.5**

### Property 15: Snapshot CDX Never Called During User Queries

*For any* HTTP request to `POST /query` or `GET /snapshots/{domain}`, zero calls SHALL be made to the CDX API (`web.archive.org/cdx/...`) as a direct or indirect consequence of handling that request.

**Validates: Requirements 8.7**

### Property 16: Citation Correctness Rate Formula

*For any* set of `FaithfulnessVerdict` records produced by the evaluation harness, `compute_citation_correctness(verdicts)` SHALL return exactly `count(verdict == "supported") / len(verdicts)`, and SHALL raise a `ZeroDivisionError` (or return `None`) when `verdicts` is empty.

**Validates: Requirements 22.4**

### Property 17: Retrieval Metric Monotonicity Across Configs

*For the labeled query set defined in the evaluation harness*, the full pipeline (config 5: vector + BM25 + RRF + reranker) SHALL achieve a Recall@10 no lower than vector-only (config 1) or BM25-only (config 2), evaluated on the same corpus.

*Note: This is an empirical claim about model quality on a specific labeled dataset — it cannot be tested as a "for all inputs" property and is not suitable for Hypothesis. It is verified exclusively by running the Phase 6 eval harness (`run_eval.py`) against the hand-labeled query set. A regression failure here means the pipeline config degraded, not a code bug.*

**Validates: Requirements 21.2, 21.4**
**Verification method: Phase 6 eval harness only — not a Hypothesis PBT**

### Property 18: Pre-Fusion Filter Constrains All Results

*For any* query where a date range filter is active, every chunk in the final evidence set returned by `POST /query` SHALL have its source's `pub_date` (or `capture_timestamp` for web sources) fall within the specified date range — no out-of-range chunks SHALL appear in the final answer.

**Validates: Requirements 12.1, 11.2**

---

## Testing Strategy

### Unit Tests

Use `pytest` for all unit tests. Unit tests focus on specific examples, edge cases, and error conditions:

- `test_ingestion_discover.py` — mock IA API responses, verify pagination and upsert behavior
- `test_fetch_adapter.py` — mock MinIO and IA, verify cache hit/miss paths and fallback logic
- `test_text_cleaner.py` — test dehyphenation, page marker preservation, header/footer stripping
- `test_chunker.py` — test chunk size bounds, overlap calculation, page anchor assignment
- `test_rrf.py` — test RRF formula with known inputs, verify top-30 selection
- `test_copyright_scope.py` — test pub_date threshold and open-access collection bypass
- `test_synthesis.py` — test JSON parsing, label validation, "launched" word detection
- `test_eval_metrics.py` — test Recall@K, Precision@K, MRR, nDCG@K with known inputs

### Property-Based Tests

Use **Hypothesis** (Python) as the property-based testing library. Each test runs a minimum of **100 iterations**.

Tag format: `# Feature: historical-rag-platform, Property N: {property_text}`

- `test_pbt_chunk_roundtrip.py` — Properties 1, 2 (serialization round-trips)
- `test_pbt_chunker.py` — Properties 3, 4 (coverage invariant, metadata completeness)
- `test_pbt_rrf.py` — Property 5 (RRF formula across random ranked lists)
- `test_pbt_copyright.py` — Property 7 (copyright scope enforcement for random source dates)
- `test_pbt_cache.py` — Properties 11, 12 (Object Cache read-through and write-before-return)
- `test_pbt_index_idempotence.py` — Properties 13, 14 (BM25 + vector re-ingestion idempotence)
- `test_pbt_filters.py` — Properties 6, 18 (filter builder always includes metadata-only exclusion clause; date filter constrains all results)
- `test_pbt_cdx_cache.py` — Properties 8, 15 (CDX cache statistics, no live CDX during queries)
- `test_pbt_web_chunks.py` — Property 9 (capture_timestamp invariant for web chunks)
- `test_pbt_discover_idempotence.py` — Property 10 (discover upsert idempotence)
- `test_pbt_citation_correctness.py` — Property 16 (citation correctness rate formula)

### Integration Tests

- `test_integration_ingestion.py` — end-to-end ingestion of a fixture set of 5 real-IA items into a local test stack
- `test_integration_retrieval.py` — round-trip query through BM25 + vector + RRF + reranker, verify chunks are returned
- `test_integration_health.py` — verify `/health` endpoint returns correct status for all services

### Smoke Tests

- Verify Docker Compose starts all services within 3 minutes and all health checks pass
- Verify OpenSearch index is created with correct field mappings after `alembic upgrade head`
- Verify Qdrant collection is created with correct vector dimensions at startup

---

## Key Design Decisions

### Decision 1: arq over Celery for Job Queue

**Chosen:** arq (async Redis queue)
**Rationale:** The ingestion pipeline is already async Python (asyncio). arq integrates natively with asyncio, eliminates the Celery process pool overhead, and the dev team is a single engineer. Celery adds operational complexity (separate broker config, worker discovery) that is not justified for a solo-engineer MVP.

### Decision 2: Pre-Fusion Filtering vs. Post-Fusion Filtering

**Chosen:** Apply all metadata/temporal filters before RRF fusion
**Rationale:** Each retrieval index has a top-K budget (50 candidates). If out-of-scope results are included in the top-50 and only filtered after fusion, the budget is partially wasted on irrelevant candidates. Pre-fusion filtering maximizes the fraction of the top-50 budget used on candidates that can actually appear in the final answer.

### Decision 3: MinIO for Local Object Cache

**Chosen:** MinIO (S3-compatible)
**Rationale:** MinIO is self-hosted, runs in Docker Compose, and is S3-API-compatible — meaning the same boto3/aioboto3 client code works for a future migration to real S3 without modification. It avoids the IA re-download problem during development iteration.

### Decision 4: k=60 for RRF

**Chosen:** k = 60 (standard default)
**Rationale:** k=60 is the empirically validated default from the original RRF paper (Cormack et al., 2009) and is consistently used in production RAG systems. It can be tuned after the evaluation harness produces comparative data.

### Decision 5: BGE-M3 + BGE Cross-Encoder

**Chosen:** BAAI/bge-m3 for embeddings, BAAI/bge-reranker-v2-m3 for reranking
**Rationale:** BGE-M3 is a multi-lingual, multi-granularity model that handles long contexts (up to 8192 tokens) and produces 1024-dimensional embeddings. The paired BGE cross-encoder shares vocabulary and training, producing high-quality relevance scores for the same input distribution as the bi-encoder.

### Decision 6: Structured JSON Answer Format

**Chosen:** LLM must return JSON `{answer_segments: [{text, citation_type, source_ids}]}`
**Rationale:** Free-text citation formatting (e.g., `[SOURCE 3, p.42]`) is fragile — LLMs hallucinate citation numbers and misformat brackets. Requiring JSON output and parsing it server-side (with a hard type error on failure) makes citation data reliable enough to persist and evaluate offline.

### Decision 7: capture_timestamp Never Conflated with pub_date

**Chosen:** Enforce as a data model constraint, a UI copy template, and a prompt template literal
**Rationale:** This is the single most common historical-reasoning error the platform could introduce. Enforcing it at three independent layers (schema, UI, LLM prompt) makes it extremely unlikely to leak through even if one layer is modified.

---

## Security and Legal Constraints

This section documents two non-negotiable constraints that apply to the entire platform. They are not implementation details — they are design commitments that affect what the system will and will not do.

---

### S.1 Copyright: Heuristic Filtering, Not Legal Guarantee

**The Internet Archive explicitly states that it does not guarantee the copyright status of any item in its collections, and that users are responsible for ensuring their use complies with applicable law.**

The copyright scope check in `app/ingestion/copyright.py` (and documented in Addendum A.2) is a **conservative filtering heuristic**, not a copyright clearance system. Specifically:

- The `pd_cutoff_year()` formula (`current_year - 96`) approximates US copyright duration for published works. It is **US-law-specific** and does not account for:
  - Foreign works (many countries use life + 70 years, not a fixed publication cutoff)
  - Sound recordings (different rules in the US pre-1972)
  - Works with complex publication histories (posthumous publication, corporate authorship)
  - Works where copyright was renewed vs. not renewed (relevant for 1924–1963 US works)
  - Government works of foreign governments (not automatically public domain outside the US)

- IA's `licenseurl`/`rights` metadata is user-supplied and may be inaccurate or absent.

- The `OPEN_ACCESS_COLLECTIONS` list is a best-effort enumeration and may include items with contested or complex rights.

**Design commitments that follow from this:**

1. **Full text is stored only in the private Object Cache (MinIO), never publicly exposed.** The `/sources` API returns metadata and chunk text for research use, not bulk downloads of raw OCR files.
2. **The UI must not present the platform as a copyright clearance tool.** Any research interface should display a disclaimer: *"Copyright status of indexed material is not guaranteed. This platform is intended for research and educational use. Users are responsible for ensuring their use complies with applicable law."*
3. **The system does not redistribute full text in machine-readable bulk form.** Chunks are returned per-query for research synthesis, not as downloadable corpora.
4. **When in doubt, the system defaults to `metadata_only`.** Any source with uncertain or unparseable rights metadata is withheld from full-text retrieval (Addendum A.4).
5. **The date heuristic is treated as a conservative floor, not a safe harbor.** A source passing the date check is eligible for indexing; it is not certified as legally public domain.

**Operational note:** For a college or research project context, keep the deployment private (localhost or institutional access only), log all ingestion activity, and configure the ingestion queries to target well-established public-domain collections (`gutenberg`, `americana`, `nasa`, government documents) where the open-access status is most reliable.

---

### S.2 Personal Information: No Collection, No Indexing, No Exposure

**The platform must not intentionally collect, expose, or index sensitive personal information (SPI) about living or recently deceased individuals.**

The Internet Archive contains historical material that may include:
- Census records, voter rolls, city directories with names and addresses
- Historical newspapers with court records, crime reports, personal announcements
- Scanned books and periodicals containing personal correspondence or biographical detail
- Archived websites that may have captured personal profiles or contact information

**Design commitments that follow from this:**

1. **Ingestion scope is restricted to clearly historical, bibliographic, and institutional material.** The default source types are public-domain books, research papers, government documents, and archived websites of public institutions. The system is not designed for ingesting personal records, social media archives, or people-search databases.

2. **No SPI extraction pipeline exists.** The platform does not run named entity recognition or structured extraction aimed at identifying, indexing, or exposing personal attributes (names, addresses, contact details, biometric data, financial information) as first-class data fields.

3. **The `/query` endpoint is for research synthesis, not person lookup.** The answer synthesis prompt (`SYSTEM_PROMPT`) instructs the LLM to answer only from provided evidence chunks. The system does not maintain a people index, does not support "tell me everything about [person]" queries as a design intent, and does not aggregate personal records across sources.

4. **Wayback snapshot ingestion is domain-scoped.** The CDX module ingests snapshots for a specified domain (e.g., a historical newspaper site), not for URLs that correspond to individual user profiles or personal pages on social platforms.

5. **The object cache is not indexed for PII.** Raw OCR files cached in MinIO are stored for pipeline reproducibility, not as a searchable personal records store. Access to MinIO is restricted to the application service account.

6. **Operators are responsible for scoping ingestion appropriately.** The `OPEN_ACCESS_COLLECTIONS` list and ingestion queries should be configured to target institutional and bibliographic collections. Operators who extend the system to ingest personal records datasets take on the associated legal and ethical obligations (GDPR, CCPA, etc.) independently.

**If SPI is encountered incidentally** (e.g., a historical newspaper article containing a named individual's address), it is handled passively — the text is chunked and indexed for research synthesis in context, not extracted into a structured personal records field. The system has no mechanism to actively seek, aggregate, or expose SPI.

---

### S.3 Summary Table

| Constraint | Mechanism | Where enforced |
|---|---|---|
| Full-text only for open-access material | `check_copyright_scope()` → `metadata_only` fallback | `app/ingestion/copyright.py` |
| Date heuristic is conservative floor, not legal guarantee | Documentation, UI disclaimer | Design doc S.1, UI copy |
| No bulk redistribution of full text | Chunks returned per-query only; raw files in private MinIO | API design, no bulk-download endpoint |
| No SPI collection as structured data | No NER extraction pipeline; query endpoint is for synthesis | `SYSTEM_PROMPT`, API design |
| Ingestion scope restricted to institutional/bibliographic | `OPEN_ACCESS_COLLECTIONS`, ingestion query targeting | `open_access_collections.json`, operator config |
| Wayback scope is domain-based, not person-based | `get_snapshots(domain)` interface | `app/wayback/cdx.py` |
| Object cache access restricted | MinIO service account only | Docker Compose environment config |

---

## Addendum: Copyright Scope Logic — Specification Gaps Closed

Four underspecifications in the copyright access control logic were identified after initial design and are closed here. This section supersedes the `check_copyright_scope` description in the Ingestion Pipeline Flow and the original formulation of Property 7.

---

### A.1 Rolling Public Domain Cutoff — No Hardcoded Year

**Problem:** The original design hardcoded `pub_date >= 1928-01-01` as the in-copyright boundary. US public domain is a rolling wall: works published in year Y enter the public domain on January 1st of year Y+96. As of 2026 that means works through 1930 are PD; in 2027 it will be 1931. A hardcoded 1928 becomes stale immediately and silently misclassifies legitimately PD works.

**Fix:** The cutoff MUST be computed dynamically at runtime:

```python
import datetime

def pd_cutoff_year() -> int:
    """Returns the most recent year whose works are in US public domain."""
    return datetime.date.today().year - 96
```

The copyright check compares `pub_date.year < pd_cutoff_year()`, never against a literal year. This function is called once per ingestion run (not per item) and its result is logged so pipeline runs are reproducible in audit.

**Scope note:** This cutoff applies to US copyright law only. The pipeline is US-law-biased by default because IA's bulk-accessible PD corpus is predominantly US-origin material. The IA rights metadata check (A.2 below) is the primary gate; the date heuristic is the fallback.

---

### A.2 IA Rights Metadata — Check First, Date-Heuristic Second

**Problem:** The original design treated collection membership and pub_date as the only access signals. IA already provides structured rights metadata on most items — using it avoids both false positives (blocking PD-marked post-cutoff works) and false negatives (allowing items with explicit rights restrictions).

**Fix:** The copyright check runs in this priority order:

```
1. Check ia_metadata["licenseurl"] or ia_metadata["rights"]:
   - Contains "creativecommons.org" → is_open_access = True, allow full text
   - Contains "publicdomain" or "public domain" (case-insensitive) → is_open_access = True, allow full text
   - Contains "rights reserved" or "in-copyright" → metadata_only, do not fetch
   - Field absent or empty → fall through to step 2

2. Check collection membership against OPEN_ACCESS_COLLECTIONS:
   - Match found → is_open_access = True, allow full text
   - No match → fall through to step 3

3. Date heuristic (fallback only):
   - pub_date is NULL or unparseable → metadata_only, log access-scope-undetermined
   - pub_date.year < pd_cutoff_year() → allow full text
   - pub_date.year >= pd_cutoff_year() → metadata_only

4. Set sources.is_open_access based on outcome of steps 1–3
```

The `is_open_access` field on the `sources` table is populated here — this is the only place it is written. It is set to `True` only when the IA rights metadata explicitly confirms it or the date heuristic clears the rolling cutoff; it defaults to `False`.

---

### A.3 OPEN_ACCESS_COLLECTIONS — Defined Artifact

**Problem:** `OPEN_ACCESS_COLLECTIONS` was referenced in the pipeline and in Property 7 but never defined anywhere as an actual artifact — no config file, no table, no env var. Property 7 is untestable without it.

**Fix:** The collection list is stored as a static JSON config file loaded at startup:

**File:** `app/ingestion/open_access_collections.json`

```json
{
  "_comment": "IA collection identifiers whose items are always treated as open access regardless of pub_date. Update this list when adding new source types.",
  "collections": [
    "gutenberg",
    "nasa",
    "usgov",
    "arxiv",
    "americana",
    "biodiversity",
    "internetarchivebooks",
    "millionbooks",
    "openlibrarybooks",
    "prelinger",
    "audio_bookspoetry"
  ]
}
```

**Loading:** Read once at application startup into a `frozenset[str]` module-level constant `OPEN_ACCESS_COLLECTIONS`. Log the loaded set at INFO level on startup so the active list is visible in run logs.

**Update path:** To add a collection, edit `open_access_collections.json` and redeploy — no schema migration required. The file is version-controlled, making changes auditable.

**Testability:** `OPEN_ACCESS_COLLECTIONS` is now a concrete, importable artifact. Property 7's Hypothesis test can generate random `(collection, pub_date)` pairs and assert correctness against the real loaded set.

---

### A.4 NULL and Unparseable pub_date — Explicit Safe Default

**Problem:** IA items frequently have missing, fuzzy, or unparseable dates (e.g., `"19uu"`, `"circa 1920"`, `"[between 1900 and 1910]"`). The original design said nothing about the NULL case, leaving the behavior undefined.

**Fix:** The copyright check treats NULL and unparseable pub_date as `metadata_only` — always. This is the safe default: refuse to fetch rather than accidentally fetch in-copyright material.

```python
def parse_pub_date(raw: str | None) -> datetime.date | None:
    """
    Returns a date if raw is parseable as a full or partial ISO date.
    Returns None for null, empty, fuzzy, or circa-style strings.
    Logs a warning when a non-null value could not be parsed.
    """
    if not raw:
        return None
    try:
        # Try full date first, then year-only
        return datetime.date.fromisoformat(raw[:10])
    except (ValueError, TypeError):
        try:
            year = int(raw[:4])
            return datetime.date(year, 1, 1)
        except (ValueError, TypeError):
            logger.warning("Unparseable pub_date value: %r — treating as metadata_only", raw)
            return None
```

This function is called before the date heuristic in step 3 of A.2. A `None` return routes directly to `metadata_only` with an `access-scope-undetermined` log entry that includes the raw date string for manual review.

---

### A.5 Revised Property 7 (supersedes original)

**Property 7: Copyright Scope Enforcement**

*For any* source record processed by `check_copyright_scope`:

1. IF `ia_metadata` contains a recognized rights field indicating open access (CC license or explicit public domain marking) → `is_open_access = True`, no chunks blocked
2. ELSE IF `collection` is in `OPEN_ACCESS_COLLECTIONS` → `is_open_access = True`, no chunks blocked
3. ELSE IF `pub_date` is NULL or unparseable → `source_type = 'metadata_only'`, `is_open_access = False`, zero chunks created
4. ELSE IF `pub_date.year >= pd_cutoff_year()` → `source_type = 'metadata_only'`, `is_open_access = False`, zero chunks created
5. ELSE (`pub_date.year < pd_cutoff_year()`) → allow full text, `is_open_access = False` (PD by age, not explicit rights)

*For any* source marked `metadata_only` by this check, the `Ingestion_Pipeline` SHALL NOT create any `chunks` rows for that source.

**Validates: Requirements 26.1, 26.2, 26.3, 10.1**
**Testable with Hypothesis:** Yes — `OPEN_ACCESS_COLLECTIONS` is a concrete artifact; `pd_cutoff_year()` is a pure function; `parse_pub_date()` is a pure function. All branches are reachable with generated inputs.
