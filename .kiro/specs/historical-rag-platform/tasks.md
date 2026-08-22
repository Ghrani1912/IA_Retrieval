# Implementation Plan: Historical Intelligence & RAG Platform

## Overview

This plan converts the design document into an ordered sequence of coding tasks, building from environment setup through ingestion, indexing, retrieval, answer synthesis, Wayback integration, evaluation, UI, and deployment. Each phase produces independently testable artifacts. Tasks marked with `*` are optional (test tasks) and can be deferred for a faster MVP iteration.

---

## Tasks

- [ ] 1. Project setup and environment scaffolding
  - Initialize git repository with Python 3.11+ using `uv` or `poetry`
  - Create `pyproject.toml` with pinned dependencies: fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, alembic, arq, redis, opensearch-py, qdrant-client, sentence-transformers, hypothesis, pytest, pytest-asyncio, aioboto3, httpx, pydantic>=2
  - Create `docker-compose.yml` defining services: `postgres` (15), `opensearch` (2.11.0), `qdrant` (v1.7.0), `minio` (latest), `redis` (7-alpine) with health checks, resource limits (2G memory, 2 CPU) for OpenSearch and Qdrant, and correct port mappings (5432, 9200, 6333, 9000, 6379)
  - Create `.env.example` listing all required env vars: `DATABASE_URL`, `OPENSEARCH_URL`, `OPENSEARCH_INDEX`, `QDRANT_URL`, `QDRANT_COLLECTION`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `REDIS_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `EMBEDDING_MODEL`, `RERANKER_MODEL`, `IA_BASE_URL`, `CDX_RATE_LIMIT_RPS`
  - Create `app/` directory structure: `ingestion/`, `wayback/`, `retrieval/`, `synthesis/`, `eval/`, `api/`, `jobs/`, `db/`, `models/`
  - Create `app/ingestion/open_access_collections.json` stub (populated in task 4.1); create `app/models/pydantic_models.py` with all Pydantic v2 models: `SourceMetadata`, `Chunk`, `ChunkWithEmbedding`, `CleanedText`, `AnswerSegment`, `AnswerResponse`, `StructuredQuery`, `SnapshotRecord`, `SnapshotStats`, `RankedChunk`, `RetrievalMetrics`, `FaithfulnessVerdict`, `LabeledQuery`, `RetrievalConfig`, `EvalResults`, `GroundTruth`, `RetrievalResult`
  - Define custom exception classes: `ChunkDeserializationError`, `AnswerParseError`, `RetrievalUnavailableError`
  - Create `app/db/schema.sql` (or Alembic migration) with all table DDL: `sources`, `chunks`, `website_snapshots`, `evidence_citations`, `ingestion_jobs`, `eval_runs` — including all indexes and CHECK constraints
  - Create initial Alembic migration from the schema; verify `alembic upgrade head` runs cleanly against the Docker Postgres
  - Create `tests/fixtures/` directory with a 20-item hardcoded test fixture (`subject:"artificial intelligence" AND date:[1975-01-01 TO 1990-12-31]`) listing IA identifiers and expected metadata
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [ ] 2. Internet Archive discovery adapter
  - [ ] 2.1 Implement `app/ingestion/discover.py` with `discover(query: str, date_range: tuple[str, str], media_type: str) -> list[SourceMetadata]`
    - Call `https://archive.org/advancedsearch.php` with `output=json`, paginate using `rows`/`page` params until all results are collected, respecting the 10,000-result cap
    - Extract `ia_identifier`, `title`, `author`, `publisher`, `pub_date`, `language`, `subject[]`, `collection`, `ia_url` from each result
    - Upsert each record to `sources` table immediately via `INSERT ... ON CONFLICT (ia_identifier) DO UPDATE`
    - Implement exponential backoff retry (3 attempts, delays 2s/4s/8s) for HTTP errors and timeouts
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ]* 2.2 Write unit tests for discover adapter
    - Mock IA API responses (paginated, error, empty)
    - Verify upsert behavior: running discover twice with identical results produces same row count
    - Verify pagination: mock 3-page response, confirm all items collected
    - Verify retry: mock 2 failures then success, confirm 3 attempts total
    - _Requirements: 2.2, 2.4, 2.5_

  - [ ]* 2.3 Write property test for discover idempotence (Property 10)
    - `# Feature: historical-rag-platform, Property 10: Discover Idempotence (Upsert)`
    - **Property 10: Discover Idempotence (Upsert)**
    - **Validates: Requirements 2.5**
    - Generate random lists of `SourceMetadata` objects with Hypothesis; call a mock upsert twice; assert `sources` count after second call equals count after first call

- [ ] 3. Full-text fetch adapter and object cache
  - [ ] 3.1 Implement `app/ingestion/fetch.py` with `fetch_fulltext(identifier: str) -> str | None`
    - Check MinIO Object_Cache first (`GET /{ia_identifier}/raw.txt`); on hit, return cached content without IA network call
    - On cache miss: call `https://archive.org/metadata/{identifier}`, find `_djvu.txt` in `files[]`; fall back to `_hocr.html` if `_djvu.txt` absent
    - Download OCR file; write to MinIO (`PUT /{ia_identifier}/raw.txt`) before returning content
    - Return `None` and update `sources.source_type = 'metadata_only'` if no OCR file found; never raise an exception for missing files
    - Retry download up to 3 times with exponential backoff on HTTP 4xx/5xx; mark `fetch_failed` after exhaustion
    - On MinIO write failure: log warning, continue with in-memory content for current run
    - On MinIO unavailable: fall back to direct IA fetch, log cache-miss warning
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 19.1, 19.2, 19.3, 19.4_

  - [ ]* 3.2 Write unit tests for fetch adapter
    - Mock MinIO hit path: verify no IA network call
    - Mock MinIO miss + IA success: verify write to MinIO before return
    - Mock no OCR file: verify `None` returned, source marked `metadata_only`
    - Mock HTTP 500 × 3: verify `fetch_failed` marked after exhaustion
    - _Requirements: 3.1–3.6_

  - [ ]* 3.3 Write property tests for object cache (Properties 11, 12)
    - `# Feature: historical-rag-platform, Property 11: Object Cache Read-Through`
    - **Property 11: Object Cache Read-Through**
    - **Validates: Requirements 3.4, 19.2**
    - Generate random `ia_identifier` strings; pre-populate mock MinIO; assert `fetch_fulltext` returns cached content and call count to mock IA remains 0
    - `# Feature: historical-rag-platform, Property 12: Object Cache Write-Before-Return`
    - **Property 12: Object Cache Write-Before-Return**
    - **Validates: Requirements 3.3, 19.1**
    - For any identifier with a mock IA success response, assert MinIO `PUT` is called with file content before the function returns

- [ ] 4. Copyright scope check
  - [ ] 4.1 Create `app/ingestion/open_access_collections.json` with the initial collection list
    - Include: `gutenberg`, `nasa`, `usgov`, `arxiv`, `americana`, `biodiversity`, `internetarchivebooks`, `millionbooks`, `openlibrarybooks`, `prelinger`, `audio_bookspoetry`
    - Loaded at application startup into a `frozenset[str]` module-level constant `OPEN_ACCESS_COLLECTIONS`; log the loaded set at INFO level on startup
    - This is the only place `OPEN_ACCESS_COLLECTIONS` is defined — no hardcoded collection lists anywhere else in the codebase
    - _Requirements: 26.2_

  - [ ] 4.2 Implement `app/ingestion/copyright.py` with `pd_cutoff_year()`, `parse_pub_date()`, and `check_copyright_scope()`
    - `pd_cutoff_year() -> int`: returns `datetime.date.today().year - 96` — never a hardcoded year
    - `parse_pub_date(raw: str | None) -> datetime.date | None`: attempt full ISO parse then year-only parse; return `None` for null, empty, fuzzy (`"19uu"`, `"circa 1920"`), or otherwise unparseable values; log a warning with the raw string when a non-null value fails parsing
    - `check_copyright_scope(source: SourceMetadata, ia_metadata: dict) -> bool` — runs in this priority order:
      1. Check `ia_metadata.get("licenseurl", "") or ia_metadata.get("rights", "")`: CC or publicdomain string → allow (`is_open_access=True`); "rights reserved" or "in-copyright" → block
      2. Check `source.collection in OPEN_ACCESS_COLLECTIONS` → allow (`is_open_access=True`)
      3. Call `parse_pub_date(source.pub_date)`: `None` result → `metadata_only`, log `access-scope-undetermined` with raw date string
      4. Compare `parsed_date.year < pd_cutoff_year()` → allow if True, block if False
    - Set `sources.is_open_access` based on outcome — this is the only place that field is written
    - Wire into ingestion pipeline Step 2 so the check occurs before `fetch_fulltext` is called
    - _Requirements: 26.1, 26.2, 26.3_

  - [ ]* 4.3 Write unit tests for copyright scope
    - Rolling cutoff: verify `pd_cutoff_year()` returns `current_year - 96`, never a literal year
    - `parse_pub_date`: valid ISO `"1920-03-15"` → date; year-only `"1885"` → date(1885,1,1); fuzzy `"19uu"` → None + warning logged; None → None; empty string → None
    - IA rights metadata gate: `licenseurl="https://creativecommons.org/..."` → allow; `rights="in-copyright"` → block; absent field → fall through to next check
    - Collection override: `pub_date="1990"` + `collection="nasa"` → allow (`is_open_access=True`)
    - Date boundary: `pub_date.year == pd_cutoff_year() - 1` → allow; `pub_date.year == pd_cutoff_year()` → block
    - NULL date: `pub_date=None` → `metadata_only`, warning logged with raw value
    - `is_open_access` field: verify it is set correctly for each branch
    - _Requirements: 26.1, 26.2, 26.3_

  - [ ]* 4.4 Write property test for copyright scope enforcement (Property 7 — revised per Addendum A.5)
    - `# Feature: historical-rag-platform, Property 7: Copyright Scope Enforcement`
    - **Property 7: Copyright Scope Enforcement (revised — see design.md Addendum A.5)**
    - **Validates: Requirements 26.1, 26.2, 26.3, 10.1**
    - Generate random `(ia_metadata_rights, collection, pub_date_str)` triples with Hypothesis covering: CC license URLs, "publicdomain" strings, "in-copyright" strings, absent rights field; collection values both in and outside `OPEN_ACCESS_COLLECTIONS`; pub_date strings including valid years, ISO dates, fuzzy strings like `"19uu"`, and None
    - Assert: any record with an explicit CC/PD rights field → allowed; any record with collection in `OPEN_ACCESS_COLLECTIONS` → allowed; any record with NULL/unparseable date and no rights/collection override → `metadata_only`; any record with `parsed_year >= pd_cutoff_year()` and no override → `metadata_only`; for all `metadata_only` outcomes, zero chunks rows created

- [ ] 5. Text cleaning
  - [ ] 5.1 Implement `app/ingestion/cleaner.py` with `clean_text(raw: str) -> CleanedText`
    - Detect and strip running headers/footers using line-frequency analysis (lines appearing on >50% of pages)
    - Rejoin OCR line-break hyphenation: detect `word-\n` patterns and merge into single token
    - Convert form-feed characters (`\x0c`) to inline page markers `[[PAGE:N]]`; preserve marker after cleaning
    - Return `CleanedText` with `text: str` and `page_markers: list[tuple[int, int]]` (marker_char_position, page_number)
    - Must not alter OCR word tokens — structural normalization only
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 5.2 Write unit tests for text cleaner
    - Test dehyphenation: `"artifi-\ncial"` → `"artificial"`
    - Test page marker preservation: form-feed at position 500 → `[[PAGE:2]]` in output at same position
    - Test header/footer strip: 10-page text with identical 3-word header → header removed, body preserved
    - Test no-op on clean text: already-clean text passes through unchanged
    - _Requirements: 4.1–4.4_

- [ ] 6. Paragraph-aware chunker and serializer
  - [ ] 6.1 Implement `app/ingestion/chunker.py` with `chunk_text(cleaned: CleanedText, source_id: int) -> list[Chunk]`
    - Split at paragraph boundaries (double newline or `[[PAGE]]` markers); merge paragraphs into chunks targeting 500 tokens ±100 (range 400–600)
    - Apply 15% token overlap between adjacent chunks
    - Record `source_id`, `page_or_section` (page number of first token), `char_range_start`, `char_range_end` for every chunk
    - For chunks spanning multiple pages, record page number of the first token
    - Write chunk rows to PostgreSQL; return list of `Chunk` with populated `id` fields
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 6.2 Implement `serialize_chunk` / `deserialize_chunk` in `app/ingestion/serializers.py`
    - `serialize_chunk(chunk: Chunk) -> dict`: convert all fields to JSON-serializable types (datetime → ISO string, None → null)
    - `deserialize_chunk(data: dict) -> Chunk`: reconstruct `Chunk`; raise `ChunkDeserializationError` with offending field name on malformed input
    - _Requirements: 29.1, 29.3, 29.5_

  - [ ]* 6.3 Write unit tests for chunker
    - Test chunk size bounds: no chunk below 400 or above 600 tokens for normal input
    - Test overlap: adjacent chunks share ≥10% of tokens
    - Test page anchor: chunk starting on page 3 has `page_or_section = "3"`
    - Test empty input: returns empty list without exception
    - _Requirements: 5.1–5.5_

  - [ ]* 6.4 Write property tests for chunk coverage and metadata completeness (Properties 3, 4)
    - `# Feature: historical-rag-platform, Property 3: Chunk Coverage Invariant`
    - **Property 3: Chunk Coverage Invariant**
    - **Validates: Requirements 5.5**
    - Generate random `CleanedText` objects with Hypothesis; assert union of `(char_range_start, char_range_end)` intervals covers full text with no gap larger than overlap window
    - `# Feature: historical-rag-platform, Property 4: Chunker Metadata Completeness`
    - **Property 4: Chunker Metadata Completeness**
    - **Validates: Requirements 5.3**
    - For any source text and source ID, assert every returned `Chunk` has non-null `source_id`, `page_or_section`, `char_range_start`, `char_range_end`

  - [ ]* 6.5 Write property tests for chunk and answer serialization round-trips (Properties 1, 2)
    - `# Feature: historical-rag-platform, Property 1: Chunk Serialization Round-Trip`
    - **Property 1: Chunk Serialization Round-Trip**
    - **Validates: Requirements 29.3**
    - Generate random valid `Chunk` objects with Hypothesis; assert `deserialize_chunk(serialize_chunk(chunk)) == chunk`
    - `# Feature: historical-rag-platform, Property 2: Answer Serialization Round-Trip`
    - **Property 2: Answer Serialization Round-Trip**
    - **Validates: Requirements 29.4**
    - Generate random valid `AnswerResponse` objects; assert `parse_answer(format_answer(answer)) == answer`

- [ ] 7. Checkpoint — ingestion pipeline unit verified
  - Ensure all tests pass for tasks 2–6. Manually verify 3 chunks from the 20-item fixture against original scanned pages on archive.org. Ask the user if questions arise.

- [ ] 8. BM25 index in OpenSearch
  - [ ] 8.1 Implement `app/ingestion/index_bm25.py` with `index_bm25(chunks: list[Chunk]) -> None`
    - Create OpenSearch index `chunks` (if not exists) with mapping: `text` field (`type: text`, `analyzer: english`), keyword fields for `date`, `source_type`, `collection`, `ia_identifier`, `capture_timestamp`, `chunk_id`, `source_id`
    - Bulk-index all chunks using `opensearch-py` bulk helper
    - On re-ingestion: delete all existing documents for `ia_identifier` before inserting new ones (`delete_by_query` on `ia_identifier` field)
    - Retry failed bulk batch once; log failed `chunk_id`s and mark source `index_failed` on second failure
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 8.2 Write unit tests for BM25 indexer
    - Mock OpenSearch client; verify index creation only called when index absent
    - Verify bulk payload structure matches mapping
    - Verify delete-before-reindex: mock existing docs for identifier, assert delete called before bulk insert
    - _Requirements: 6.1, 6.4_

  - [ ]* 8.3 Write property test for BM25 index idempotence (Property 13)
    - `# Feature: historical-rag-platform, Property 13: BM25 Index Idempotence on Re-Ingestion`
    - **Property 13: BM25 Index Idempotence on Re-Ingestion**
    - **Validates: Requirements 6.4**
    - Generate random lists of `Chunk` objects for a random `ia_identifier`; index twice; assert OpenSearch document count for that identifier is the same after both runs

- [ ] 9. BGE-M3 embeddings and Qdrant vector index
  - [ ] 9.1 Implement `app/ingestion/embed.py` with `embed_chunks(chunks: list[Chunk]) -> list[ChunkWithEmbedding]`
    - Load `BAAI/bge-m3` via `sentence-transformers`; batch-encode chunk texts (batch size 32)
    - Return `ChunkWithEmbedding` list with original `Chunk` fields plus `embedding: list[float]` (1024 dims)
    - _Requirements: 7.1_

  - [ ] 9.2 Implement `app/ingestion/index_vectors.py` with `index_vectors(chunks: list[ChunkWithEmbedding]) -> None`
    - Create Qdrant collection `chunks` (dimension=1024, distance=Cosine) if not exists
    - On re-ingestion: delete all existing Qdrant points for `ia_identifier` using a filter on `ia_identifier` payload field before inserting new ones
    - Upsert embeddings with payload: `source_id`, `ia_identifier`, `date`, `source_type`, `collection`, `capture_timestamp`, `chunk_db_id`
    - Store returned Qdrant point IDs back to `chunks.embedding_id` in PostgreSQL
    - _Requirements: 7.2, 7.3, 7.4, 7.5_

  - [ ]* 9.3 Write unit tests for embedding and vector indexer
    - Mock `sentence-transformers` to return fixed-size vectors; verify batch size logic
    - Mock Qdrant client; verify delete-before-reindex logic; verify embedding_id written to chunks table
    - _Requirements: 7.2, 7.3, 7.5_

  - [ ]* 9.4 Write property test for vector index idempotence (Property 14)
    - `# Feature: historical-rag-platform, Property 14: Vector Index Idempotence on Re-Ingestion`
    - **Property 14: Vector Index Idempotence on Re-Ingestion**
    - **Validates: Requirements 7.5**
    - Generate random `ChunkWithEmbedding` lists for a random identifier; index twice; assert Qdrant point count for that identifier is the same after both runs

- [ ] 10. Checkpoint — indexing verified
  - Ensure all tests pass. Run a plain keyword query against OpenSearch for "machine intelligence" and a raw vector similarity search against Qdrant; confirm both return plausible top-10s from the 20-item fixture. Ask the user if questions arise.

- [ ] 11. Query understanding
  - [ ] 11.1 Implement `app/retrieval/query_understanding.py` with `async understand_query(raw_query: str) -> StructuredQuery`
    - Issue LLM API call (configured via `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`) with a structured prompt to extract: `topic_keywords`, `date_range_start`, `date_range_end`, `source_type_hint`, `is_temporal_comparison`
    - Parse LLM JSON response into `StructuredQuery`
    - On LLM failure or timeout: log failure and return `StructuredQuery(raw_query=raw_query, topic_keywords=[raw_query])` as fallback — never raise to caller
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [ ]* 11.2 Write unit tests for query understanding
    - Mock LLM returning valid JSON: verify all fields correctly populated
    - Mock LLM timeout: verify fallback `StructuredQuery` returned and failure logged
    - Mock LLM returning malformed JSON: verify fallback triggered
    - _Requirements: 11.1, 11.3_

- [ ] 12. Pre-fusion metadata and temporal filtering
  - [ ] 12.1 Implement `app/retrieval/filters.py` with `build_opensearch_filter(query: StructuredQuery) -> dict` and `build_qdrant_filter(query: StructuredQuery) -> dict`
    - Apply date range as OpenSearch `range` on `date` field; apply as Qdrant `range` filter on `date` payload field
    - Apply `source_type` filter as keyword match in both indexes
    - Apply `collection` filter as keyword match in both indexes
    - Always exclude `source_type = 'metadata_only'` from both indexes (hard filter, regardless of query)
    - When no filter is active, return empty filter object (no restriction)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 10.3_

  - [ ]* 12.2 Write unit tests for filter builders
    - Date range filter: verify range bounds map correctly to OpenSearch and Qdrant filter dicts
    - metadata_only exclusion: verify exclusion clause always present in returned filter
    - No-filter case: verify output passes all documents
    - _Requirements: 12.1–12.4, 10.3_

- [ ] 13. Parallel BM25 and vector retrieval
  - [ ] 13.1 Implement `app/retrieval/retrieve.py` with `async retrieve_bm25(query: StructuredQuery) -> list[RankedChunk]` and `async retrieve_vector(query: StructuredQuery) -> list[RankedChunk]`
    - `retrieve_bm25`: call OpenSearch with `topic_keywords` as multi-match query, apply filters from `build_opensearch_filter`, return top-50 results with rank positions 1–50
    - `retrieve_vector`: embed `topic_keywords` with BGE-M3, call Qdrant with cosine similarity, apply filters from `build_qdrant_filter`, return top-50 with rank positions 1–50
    - Execute both calls concurrently via `asyncio.gather`
    - On BM25 failure: log and return empty list; caller proceeds with vector results only
    - On vector failure: log and return empty list; caller proceeds with BM25 results only
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [ ]* 13.2 Write unit tests for parallel retrieval
    - Mock both indexes returning results: verify both called in same gather
    - Mock BM25 failure: verify vector results returned, error logged
    - Mock vector failure: verify BM25 results returned, error logged
    - _Requirements: 13.1–13.4_

- [ ] 14. Reciprocal Rank Fusion
  - [ ] 14.1 Implement `app/retrieval/rrf.py` with `fuse_rrf(bm25_results: list[RankedChunk], vector_results: list[RankedChunk]) -> list[RankedChunk]`
    - Compute RRF score for each chunk: `score(chunk) = sum(1 / (60 + rank_i))` for each list the chunk appears in (k=60)
    - Chunks in both lists accumulate contributions from both
    - Chunks in only one list use single-list contribution
    - Return top 30 chunks sorted by descending RRF score
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [ ]* 14.2 Write unit tests for RRF
    - Known input: BM25 rank=[1,2,3], vector rank=[2,3,4]; verify chunk at rank 2 in both gets double contribution
    - Verify top-30 cutoff: 100-item merged input returns exactly 30
    - Verify sort order: descending by RRF score
    - _Requirements: 14.1–14.4_

  - [ ]* 14.3 Write property test for RRF formula correctness (Property 5)
    - `# Feature: historical-rag-platform, Property 5: RRF Score Formula Correctness`
    - **Property 5: RRF Score Formula Correctness**
    - **Validates: Requirements 14.1, 14.2, 14.3, 14.4**
    - Generate random BM25 and vector ranked lists with Hypothesis (up to 50 items each with varying overlap); assert each chunk's score equals `sum(1/(60+rank_i))`, result is sorted descending, and contains at most 30 items

- [ ] 15. Cross-encoder reranker
  - [ ] 15.1 Implement `app/retrieval/reranker.py` with `rerank(query: str, candidates: list[RankedChunk]) -> list[RankedChunk]`
    - Load `BAAI/bge-reranker-v2-m3` via `sentence-transformers` cross-encoder interface
    - Score each (query, chunk_text) pair; sort descending; return top 8–12 chunks
    - On reranker unavailable or error: log fallback event; return top 8–12 from input list by existing RRF score
    - _Requirements: 15.1, 15.2, 15.3_

  - [ ]* 15.2 Write unit tests for reranker
    - Mock cross-encoder; verify top-8 returned from 30-item candidate list
    - Mock cross-encoder failure; verify fallback to top-8 RRF list and fallback logged
    - _Requirements: 15.1–15.3_

- [ ] 16. Pre-fusion filter property tests
  - [ ]* 16.1 Write property tests for filter enforcement (Properties 6, 18)
    - `# Feature: historical-rag-platform, Property 6: Filter Builder Always Excludes Metadata-Only Sources`
    - **Property 6: Filter Builder Always Excludes Metadata-Only Sources**
    - **Validates: Requirements 10.3, 26.1**
    - Generate random `StructuredQuery` objects with Hypothesis; call `build_opensearch_filter` and `build_qdrant_filter`; assert returned filter dicts always contain a clause excluding `source_type = 'metadata_only'`, regardless of query parameters — this tests the filter construction code, not end-to-end retrieval
    - `# Feature: historical-rag-platform, Property 18: Pre-Fusion Filter Constrains All Results`
    - **Property 18: Pre-Fusion Filter Constrains All Results**
    - **Validates: Requirements 12.1, 11.2**
    - Generate random date range filters and mock chunk sets with Hypothesis; run the filter construction + mock retrieval with date filter active; assert every chunk in the candidate set passed to RRF has `pub_date` or `capture_timestamp` within the specified range

- [ ] 17. Checkpoint — retrieval pipeline verified
  - Ensure all tests pass for tasks 11–16. Run end-to-end: submit a query with a date filter, verify returned chunks have dates in range and no metadata_only chunks present. Ask the user if questions arise.

- [ ] 18. Answer synthesizer and format/parse serializers
  - [ ] 18.1 Implement `app/synthesis/synthesizer.py` with `async synthesize_answer(query: str, evidence: list[RankedChunk]) -> AnswerResponse`
    - Build LLM prompt using `SYSTEM_PROMPT` literal constant (never dynamically generated) that instructs evidence-only answering, DIRECTLY_VERIFIED/INFERRED/UNKNOWN tagging, and "first archived"/"earliest snapshot" language for website sources (never "launched")
    - Include evidence block per chunk: title, author, pub_date or capture_timestamp, ia_identifier, page_or_section, chunk text
    - Call LLM API; parse response with `parse_answer`; on `AnswerParseError`: log raw output, raise `AnswerParseError` to be caught by API layer for HTTP 500
    - Check for word "launched" in website-source answer segments; set warning flag on segment if found
    - Call `persist_citations(answer)` to write evidence_citations rows
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 18.3, 18.4_

  - [ ] 18.2 Implement `format_answer` / `parse_answer` in `app/synthesis/serializers.py`
    - `format_answer(answer: AnswerResponse) -> str`: serialize to JSON string matching LLM output schema `{answer_segments: [{text, citation_type, source_ids, chunk_ids}]}`
    - `parse_answer(raw: str) -> AnswerResponse`: parse JSON; validate `citation_type` is one of `DIRECTLY_VERIFIED`, `INFERRED`, `UNKNOWN`; raise `AnswerParseError` on malformed JSON or invalid citation_type
    - _Requirements: 29.2, 29.4, 29.6, 16.3, 16.7_

  - [ ] 18.3 Implement `async persist_citations(answer: AnswerResponse) -> None` in `app/synthesis/citations.py`
    - Insert one row per (answer_segment, chunk_id) pair into `evidence_citations` with `answer_id`, `chunk_id`, `confidence_label`
    - Validate `confidence_label` against allowed values before insert; raise validation error on invalid value
    - Ensure at least one citation row exists for every non-UNKNOWN segment before returning
    - _Requirements: 17.1, 17.2, 17.3_

  - [ ]* 18.4 Write unit tests for answer synthesizer
    - Mock LLM returning valid JSON: verify segments parsed, citations persisted
    - Mock LLM returning malformed JSON: verify `AnswerParseError` raised, raw output logged
    - Test "launched" detection: answer containing "launched" for web source sets warning flag
    - Test citation persistence: verify correct number of rows inserted for multi-segment answer
    - _Requirements: 16.1–16.7, 17.1–17.3, 18.3–18.4_

  - [ ]* 18.5 Write property test for answer serialization round-trip (Property 2 — implementation)
    - Already specified in task 6.5; verify Hypothesis tests cover `AnswerResponse` with multiple segments and all three citation types

- [ ] 19. CDX cache ingestion (Wayback Pipeline)
  - [ ] 19.1 Implement `app/wayback/cdx.py` with `async get_snapshots(domain: str) -> list[SnapshotRecord]`
    - Check `website_snapshots` table: if any record exists with `fetched_at > now() - 24h` for this domain, return cached records without CDX call
    - CDX API call: `GET https://web.archive.org/cdx/search/cdx?url={domain}/*&output=json` with pagination (`limit=10000`)
    - Rate limit: `asyncio.sleep(1)` between pages
    - On HTTP 429: exponential backoff starting at 2s, up to 5 retries
    - Upsert rows to `website_snapshots` with `fetched_flag=false`; set `fetched_at = now()` on the domain-level record
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ] 19.2 Implement `compute_snapshot_stats(domain: str) -> SnapshotStats` in `app/wayback/stats.py`
    - Derive all stats (earliest, latest, total_count, per_year, gap_years) from cached `website_snapshots` rows only — never re-query CDX
    - Compute gap_years as years between earliest and latest with zero snapshots
    - _Requirements: 8.6, 8.7_

  - [ ]* 19.3 Write unit tests for CDX cache
    - Cache hit (fresh fetched_at): verify no CDX call, cached records returned
    - Cache miss: verify CDX called, records upserted
    - 429 backoff: mock 429 × 2 then 200; verify backoff applied and eventual success
    - Stats derivation: seed 5 rows, verify stats computed correctly from DB
    - _Requirements: 8.1–8.7_

  - [ ]* 19.4 Write property tests for CDX cache statistics and no-live-CDX (Properties 8, 15)
    - `# Feature: historical-rag-platform, Property 8: CDX Cache-Only Statistics`
    - **Property 8: CDX Cache-Only Statistics**
    - **Validates: Requirements 8.6, 8.7**
    - Generate random sets of `SnapshotRecord` objects with Hypothesis; seed DB; assert `compute_snapshot_stats` returns values derivable exactly from those rows
    - `# Feature: historical-rag-platform, Property 15: Snapshot CDX Never Called During User Queries`
    - **Property 15: Snapshot CDX Never Called During User Queries**
    - **Validates: Requirements 8.7**
    - For any `POST /query` or `GET /snapshots/{domain}` request handled by mocked handlers, assert CDX API call count to `web.archive.org/cdx/...` remains zero

- [ ] 20. On-demand Wayback snapshot content fetch
  - [ ] 20.1 Implement `async fetch_snapshot_content(url: str, snapshot_timestamp: str) -> str | None` in `app/wayback/memento.py`
    - Check `website_snapshots.fetched_flag` for `(url, snapshot_timestamp)`; if true, return existing chunks from DB without refetching
    - Fetch HTML via Memento API `https://web.archive.org/web/{timestamp}/{url}`; extract main text via `readability-lxml` or equivalent (strip nav, ads, boilerplate)
    - Run extracted text through `clean_text()` → `chunk_text()` → `embed_chunks()` pipeline
    - Tag every resulting chunk with `capture_timestamp = snapshot_timestamp`; do NOT set `pub_date`
    - Index chunks to OpenSearch and Qdrant
    - Update `website_snapshots.fetched_flag = true`, `fetched_at = now()`
    - On Memento fetch failure: log and skip; leave `fetched_flag = false`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 18.1_

  - [ ]* 20.2 Write unit tests for on-demand snapshot fetch
    - Mock `fetched_flag = true`: verify no Memento call, existing chunks returned
    - Mock Memento success: verify chunk pipeline called, `capture_timestamp` set, `pub_date` not set
    - Mock Memento failure: verify skip, `fetched_flag` remains false
    - _Requirements: 9.1–9.5_

  - [ ]* 20.3 Write property test for web chunk capture_timestamp invariant (Property 9)
    - `# Feature: historical-rag-platform, Property 9: Web Chunk capture_timestamp Invariant`
    - **Property 9: Web Chunk capture_timestamp Invariant**
    - **Validates: Requirements 9.5, 18.1**
    - Generate random snapshot timestamps and HTML content with Hypothesis; run through wayback chunk pipeline; assert every produced chunk has non-null `capture_timestamp` equal to snapshot timestamp and null `pub_date`

- [ ] 21. Checkpoint — Wayback pipeline verified
  - Ensure all tests pass for tasks 19–20. Verify "when was this website first archived?" returns cached answer without live CDX call, and chunk `capture_timestamp` values are correctly set. Ask the user if questions arise.

- [ ] 22. Async job queue and ingestion job orchestration
  - [ ] 22.1 Implement `app/jobs/worker.py` with arq `WorkerSettings` and `run_ingestion_job` async function
    - Define `run_ingestion_job(ctx, job_id: str, query: str, date_range: tuple, source_type: str) -> None`
    - Execute full pipeline in order: `discover` → copyright check → `fetch_fulltext` → `clean_text` → `chunk_text` → `embed_chunks` → `index_vectors` → `index_bm25`
    - Update `ingestion_jobs` table at each step: increment `sources_done`, `chunks_created`; set `status='completed'` on success
    - On any unhandled exception: set `job.status='failed'`, `job.error_step`, `job.error_msg`; continue with remaining sources
    - Emit structured JSON logs for each pipeline step: step name, ia_identifier, duration_ms, outcome
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 30.1_

  - [ ]* 22.2 Write unit tests for job orchestration
    - Mock pipeline steps; verify order of calls
    - Mock failure at `chunk_text` step: verify `error_step = 'chunk_text'` recorded, other sources continue
    - Verify `sources_done` incremented correctly
    - _Requirements: 20.1–20.5_

- [ ] 23. Database migrations (Alembic)
  - [ ] 23.1 Write Alembic migration scripts for all tables from schema.sql
    - Migrations for: `sources`, `chunks`, `website_snapshots`, `evidence_citations`, `ingestion_jobs`, `eval_runs`
    - Include all indexes and CHECK constraints as per `schema.sql`
    - Wire `alembic upgrade head` to run automatically in the Docker `app` container `command` before uvicorn starts
    - _Requirements: 28.3_

- [ ] 24. FastAPI application endpoints
  - [ ] 24.1 Implement `app/api/routes/query.py`: `POST /query`
    - Accept `{query: str, filters: {date_range, source_type, collection}}`; validate with Pydantic; return 422 on invalid
    - Call `understand_query` → `build_filters` → `asyncio.gather(retrieve_bm25, retrieve_vector)` → `fuse_rrf` → `rerank` → `synthesize_answer`
    - Log query_id, extracted filters, BM25/vector/RRF/rerank counts, total latency_ms
    - On both retrievals failing: return HTTP 503 `{"error": "retrieval_unavailable"}`
    - On synthesis failure: return HTTP 500 `{"error": "synthesis_failed", "detail": "..."}`
    - _Requirements: 27.1, 13.1, 30.2_

  - [ ] 24.2 Implement `app/api/routes/sources.py`: `GET /sources` and `GET /sources/{ia_identifier}`
    - `GET /sources`: accept filter params (`source_type`, `collection`, `date_from`, `date_to`, `language`, `page`, `page_size` default=50 max=100); return paginated list with `total`, `page`, `page_size`
    - `GET /sources/{ia_identifier}`: return full source metadata + `chunk_count` for non-metadata_only sources; 404 if not found
    - Return 422 for invalid params
    - _Requirements: 27.2, 27.3, 27.7_

  - [ ] 24.3 Implement `app/api/routes/ingest.py`: `POST /ingest` and `GET /ingest/{job_id}/status`
    - `POST /ingest`: validate request, generate UUID job_id, insert `ingestion_jobs` row with `status='queued'`, enqueue to arq; return 202 `{"job_id": "..."}`
    - `GET /ingest/{job_id}/status`: fetch from `ingestion_jobs`; return `job_id`, `status`, `sources_total`, `sources_done`, `chunks_created`, `error_step`, `error_msg`, timestamps
    - _Requirements: 27.4, 27.5, 20.5_

  - [ ] 24.4 Implement `app/api/routes/snapshots.py`: `GET /snapshots/{domain}`
    - Serve from CDX cache only: call `compute_snapshot_stats(domain)`
    - If no cached data: return 404 `{"error": "domain_not_cached"}`
    - Never call CDX API from this route
    - _Requirements: 27.6, 8.7_

  - [ ] 24.5 Implement `app/api/routes/health.py`: `GET /health`
    - Probe PostgreSQL (execute `SELECT 1`), OpenSearch (cluster health), Qdrant (healthz), MinIO (health/live), Redis (PING) in parallel
    - Record latency_ms for each; return 200 `{"status": "healthy", "services": {...}}` when all pass
    - Return 503 `{"status": "degraded", "services": {...}}` when any service fails
    - _Requirements: 27.7, 30.5_

  - [ ]* 24.6 Write unit tests for API endpoints
    - `POST /query`: mock pipeline, verify 422 on missing query, 503 on dual retrieval failure, 500 on parse error
    - `GET /sources`: verify pagination math, filter params passed to DB query
    - `POST /ingest`: verify job enqueued, 202 returned, job row created
    - `GET /health`: mock all services healthy → 200; mock one down → 503
    - _Requirements: 27.1–27.7_

- [ ] 25. Evaluation harness
  - [ ] 25.1 Create `app/eval/queries.json` with 30–50 labeled queries
    - Include at least 4 query types: `book_lookup`, `date_range_filtering`, `website_history`, `cross_decade_comparison`
    - Each entry: `id`, `query`, `query_type`, `relevant_chunk_ids[]`, `date_range` (where applicable)
    - _Requirements: 21.1_

  - [ ] 25.2 Implement `app/eval/configs.py` with 5 retrieval config definitions
    - Config 1: `vector_only` — Qdrant top-10, no BM25, no fusion, no rerank
    - Config 2: `bm25_only` — OpenSearch top-10, no vector, no fusion, no rerank
    - Config 3: `simple_merge` — Qdrant top-50 + OpenSearch top-50, interleave by score (no RRF)
    - Config 4: `rrf` — Qdrant top-50 + OpenSearch top-50, RRF fusion, top-10, no rerank
    - Config 5: `full_pipeline` — Config 4 + BGE cross-encoder rerank → top 8–12
    - _Requirements: 21.2_

  - [ ] 25.3 Implement `app/eval/metrics.py` with `compute_metrics(results, ground_truth) -> RetrievalMetrics`
    - Compute Recall@10: `len(relevant ∩ retrieved[:10]) / len(relevant)`
    - Compute Precision@10: `len(relevant ∩ retrieved[:10]) / 10`
    - Compute MRR: `1 / rank_of_first_relevant` (0 if none in top-10)
    - Compute nDCG@10: DCG@10 / ideal DCG@10 using binary relevance
    - _Requirements: 21.3_

  - [ ] 25.4 Implement `app/eval/judge.py` with `judge_faithfulness` and `compute_citation_correctness`
    - `judge_faithfulness(answer, chunks) -> list[FaithfulnessVerdict]`: LLM-as-judge using `JUDGE_PROMPT` literal; one verdict per (answer_segment, chunk_id) pair; output `"supported"` or `"not_supported"`
    - `compute_citation_correctness(verdicts) -> float`: `count(verdict == "supported") / len(verdicts)`; raise `ZeroDivisionError` when verdicts is empty
    - Emit warning when correctness rate < 0.8
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5_

  - [ ] 25.5 Implement `app/eval/run_eval.py` CLI entry point
    - `run_eval(labeled_queries, config) -> EvalResults`: run all queries against given config; aggregate metrics
    - Loop over 5 configs, collect results, produce comparison table (printed and persisted to `eval_runs` table)
    - This is the verification mechanism for Property 17 (retrieval metric monotonicity across configs) — that property is an empirical claim about model quality on the labeled dataset, not a Hypothesis PBT
    - _Requirements: 21.2, 21.4, 21.5_

  - [ ]* 25.6 Write unit tests for evaluation metrics
    - Test Recall@10: known relevant set of 4, retrieved top-10 contains 3 → 0.75
    - Test Precision@10: 3 relevant in top-10 → 0.3
    - Test MRR: first relevant at rank 3 → 0.333
    - Test nDCG@10: known DCG and ideal DCG → verify formula
    - Test `compute_citation_correctness`: 3 supported / 4 total → 0.75
    - _Requirements: 21.3, 22.4_

  - [ ]* 25.7 Write property test for citation correctness rate formula (Property 16)
    - `# Feature: historical-rag-platform, Property 16: Citation Correctness Rate Formula`
    - **Property 16: Citation Correctness Rate Formula**
    - **Validates: Requirements 22.4**
    - Generate random lists of `FaithfulnessVerdict` with Hypothesis; assert `compute_citation_correctness(verdicts) == count("supported") / len(verdicts)`; assert empty list raises `ZeroDivisionError`

- [ ] 26. Checkpoint — backend fully integrated
  - Ensure all tests pass for tasks 18–25. Run end-to-end: POST /ingest for 5 fixture items, poll status until completed, POST /query, verify structured answer with citations returned. Ask the user if questions arise.

- [ ] 27. React/Next.js frontend — project setup and API client
  - [ ] 27.1 Create `app/frontend/` with Next.js (TypeScript) project structure
    - Pages: `pages/index.tsx` (Research Chat), `pages/sources/index.tsx` (Source Explorer), `pages/sources/[ia_identifier].tsx` (Source detail), `pages/timeline.tsx`
    - Components: `components/chat/`, `components/sources/`, `components/timeline/`
    - `lib/api.ts`: typed fetch wrappers for all 7 API endpoints using TypeScript interfaces
    - `lib/types.ts`: TypeScript interfaces matching all Pydantic models (`SourceMetadata`, `Chunk`, `AnswerResponse`, `AnswerSegment`, `SnapshotStats`, etc.)
    - `styles/globals.css`
    - _Requirements: 23.1_

- [ ] 28. Research Chat UI components
  - [ ] 28.1 Implement `components/chat/ChatInput.tsx`
    - Text input + submit button; disable both while query in progress to prevent duplicate submission
    - Show skeleton loader while awaiting API response
    - _Requirements: 23.1, 23.4_

  - [ ] 28.2 Implement `components/chat/CitationChip.tsx` and `components/chat/AnswerSegment.tsx`
    - `CitationChip`: render inline chip with source title, author, year, and color-coded confidence label (green=DIRECTLY_VERIFIED, amber=INFERRED, gray+italic=UNKNOWN)
    - `AnswerSegment`: render answer text with inline `CitationChip` components for each citation; apply distinct visual style (italic/warning color) for UNKNOWN segments
    - _Requirements: 23.2, 23.5_

  - [ ] 28.3 Implement `components/chat/ChunkDrawer.tsx`
    - Slide-in panel triggered by `CitationChip` click
    - Display: full chunk text, source title, author, pub_date (or `capture_timestamp` labeled "Archived on {date}" for web chunks — never "Published"), ia_url link, page/section reference
    - For web snapshot chunks: display `capture_timestamp` as "Archived on {date}" — never display a publication date
    - _Requirements: 23.3, 23.6, 18.2_

  - [ ] 28.4 Wire `pages/index.tsx` Research Chat page
    - Assemble `ChatInput` → POST /query → render `AnswerSegment` list with `ChunkDrawer`
    - _Requirements: 23.1–23.6_

  - [ ] 28.5 Add copyright and research-use disclaimer to the UI (design.md S.1)
    - Render a persistent notice in the Research Chat page footer and the Source Explorer header:
      *"Copyright status of indexed material is not guaranteed. This platform is for research and educational use only. Users are responsible for ensuring their use complies with applicable law."*
    - The disclaimer must be visible on every page that renders source content or answer segments — it must not be hidden behind a modal or require user action to display
    - Do NOT label any source as "public domain confirmed" or "copyright cleared" — only display the raw `source_type` and `is_open_access` flag values as-is
    - _Implements: design.md S.1 commitment 2_

- [ ] 29. Source Explorer UI components
  - [ ] 29.1 Implement `components/sources/FilterBar.tsx` and `components/sources/SourceTable.tsx`
    - `FilterBar`: controls for `source_type`, `collection`, date range, language; update URL query params on change; trigger API refetch
    - `SourceTable`: paginated list (max 50/page); display title, author, pub_date, source_type, collection, ia_url
    - Show "Full text unavailable" badge (gray) for `metadata_only` sources
    - Show "Fetch failed" badge (red) for `fetch_failed` sources
    - _Requirements: 24.1, 24.2, 24.4, 24.5_

  - [ ] 29.2 Implement `pages/sources/[ia_identifier].tsx` source detail page
    - Display full source metadata; show `chunk_count` for non-metadata_only sources
    - _Requirements: 24.3_

- [ ] 30. Timeline View UI component
  - [ ] 30.1 Implement `components/timeline/TimelineChart.tsx` and `components/timeline/YearFilter.tsx`
    - `TimelineChart`: Plotly or D3 bar chart of source count by year; zero-height bars for empty years (never hidden)
    - For web source queries: label x-axis "Year Archived" not "Year Published"
    - Bar click → filter Source Explorer to that year
    - `YearFilter`: brush/date range selector; propagate to Source Explorer and active query context
    - When query submitted: filter timeline to retrieved sources only, not full corpus
    - _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5_

- [ ] 31. Full Docker Compose deployment configuration
  - [ ] 31.1 Add `app` and `worker` service definitions to `docker-compose.yml`
    - `app` service: `build: .`, ports `["8000:8000"]`, `env_file: .env`, `depends_on` all backing services with `condition: service_healthy`, command: `sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"`
    - `worker` service: same build, `depends_on: [redis, postgres, opensearch, qdrant, minio]`, command: `python -m arq app.jobs.WorkerSettings`
    - Resource limits for OpenSearch and Qdrant: `memory: 2G, cpus: "2.0"`
    - Verify `docker compose up` from clean state reaches healthy state within 3 minutes
    - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.5_

  - [ ] 31.2 Restrict MinIO access to the application service account (design.md S.2)
    - MinIO must NOT expose port 9000 on the host in production configuration — bind only to `127.0.0.1:9000` or use Docker internal networking (no published port for external access)
    - Set `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` from `.env` secrets, never hardcoded defaults in production
    - The `worker` and `app` containers access MinIO via the internal Docker network hostname (`minio:9000`), not via the host
    - Add a comment in `docker-compose.yml` explicitly stating: "MinIO port 9000 intentionally not published externally — raw OCR cache is not a public API"
    - _Implements: design.md S.2 commitment 5_

- [ ] 32. Integration tests and smoke tests
  - [ ]* 32.1 Write integration test: end-to-end ingestion
    - `tests/integration/test_integration_ingestion.py`
    - Ingest 5 items from the fixture set against a local test stack (Docker Compose)
    - Assert chunks created in PostgreSQL, documents in OpenSearch, points in Qdrant
    - Assert object cache populated in MinIO
    - _Requirements: 3.3, 6.2, 7.2_

  - [ ]* 32.2 Write integration test: retrieval round-trip
    - `tests/integration/test_integration_retrieval.py`
    - Submit a test query; verify BM25 + vector + RRF + reranker pipeline returns at least 1 chunk from the expected source
    - _Requirements: 13.1, 14.1, 15.1_

  - [ ]* 32.3 Write integration test: health endpoint
    - `tests/integration/test_integration_health.py`
    - GET /health with all services running → 200 `{"status": "healthy"}`
    - GET /health with OpenSearch stopped → 503 `{"status": "degraded"}`
    - _Requirements: 30.5_

  - [ ]* 32.4 Write smoke tests for Docker Compose stack
    - Verify all service health checks pass within 3 minutes of `docker compose up`
    - Verify OpenSearch index `chunks` exists with correct field mappings after `alembic upgrade head`
    - Verify Qdrant collection `chunks` created with dimension=1024 at startup
    - _Requirements: 28.2_

- [ ] 33. Final checkpoint — all tests pass and system is deployable
  - Ensure all unit, property, and integration tests pass. Verify `docker compose up` brings the full stack to healthy state. Run a POST /ingest followed by POST /query and confirm a structured cited answer is returned. Ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP — property and integration tests provide correctness guarantees but are not required for a running system
- Each task references specific requirements for traceability — all 30 requirements are covered
- The 18 correctness properties from the design document each have a dedicated property-based test sub-task using Hypothesis with ≥100 iterations
- Checkpoints at tasks 7, 10, 17, 21, 26, and 33 validate incremental progress before moving to the next phase
- The CDX API is never called during user queries — CDX ingestion (task 19) must complete before any domain is queryable via `GET /snapshots/{domain}`
- Copyright scope check (task 4) must be wired into the pipeline before `fetch_fulltext` is invoked (task 3)
- Serializer round-trip tests (Properties 1, 2) are implemented in tasks 6.5 and 18.5 alongside the serializer implementations

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1"], "description": "Project setup and environment scaffolding" },
    { "wave": 2, "tasks": ["2"], "description": "Discovery adapter", "dependsOn": ["1"] },
    { "wave": 3, "tasks": ["3"], "description": "Fetch adapter and object cache", "dependsOn": ["2"] },
    { "wave": 4, "tasks": ["4"], "description": "Copyright scope check", "dependsOn": ["3"] },
    { "wave": 5, "tasks": ["5"], "description": "Text cleaning", "dependsOn": ["4"] },
    { "wave": 6, "tasks": ["6"], "description": "Chunker and serializers", "dependsOn": ["5"] },
    { "wave": 7, "tasks": ["7"], "description": "Checkpoint: ingestion pipeline unit verified", "dependsOn": ["6"] },
    { "wave": 8, "tasks": ["8"], "description": "BM25 index in OpenSearch", "dependsOn": ["7"] },
    { "wave": 9, "tasks": ["9"], "description": "BGE-M3 embeddings and Qdrant vector index", "dependsOn": ["8"] },
    { "wave": 10, "tasks": ["10"], "description": "Checkpoint: indexing verified", "dependsOn": ["9"] },
    { "wave": 11, "tasks": ["11"], "description": "Query understanding", "dependsOn": ["10"] },
    { "wave": 12, "tasks": ["12"], "description": "Pre-fusion metadata and temporal filtering", "dependsOn": ["11"] },
    { "wave": 13, "tasks": ["13"], "description": "Parallel BM25 and vector retrieval", "dependsOn": ["12"] },
    { "wave": 14, "tasks": ["14"], "description": "Reciprocal Rank Fusion", "dependsOn": ["13"] },
    { "wave": 15, "tasks": ["15"], "description": "Cross-encoder reranker", "dependsOn": ["14"] },
    { "wave": 16, "tasks": ["16"], "description": "Pre-fusion filter and metadata-only exclusion property tests", "dependsOn": ["15"] },
    { "wave": 17, "tasks": ["17"], "description": "Checkpoint: retrieval pipeline verified", "dependsOn": ["16"] },
    { "wave": 18, "tasks": ["18", "19", "22", "23"], "description": "Answer synthesizer, CDX cache, job queue, migrations", "dependsOn": ["17"] },
    { "wave": 19, "tasks": ["20"], "description": "On-demand Wayback snapshot content fetch", "dependsOn": ["18", "19"] },
    { "wave": 20, "tasks": ["21"], "description": "Checkpoint: Wayback pipeline verified", "dependsOn": ["20"] },
    { "wave": 21, "tasks": ["24"], "description": "FastAPI application endpoints", "dependsOn": ["18", "22", "23"] },
    { "wave": 22, "tasks": ["25"], "description": "Evaluation harness", "dependsOn": ["24"] },
    { "wave": 23, "tasks": ["26"], "description": "Checkpoint: backend fully integrated", "dependsOn": ["25"] },
    { "wave": 24, "tasks": ["27"], "description": "Frontend project setup and API client", "dependsOn": ["26"] },
    { "wave": 25, "tasks": ["28", "29", "30"], "description": "Research Chat, Source Explorer, Timeline UI components", "dependsOn": ["27"] },
    { "wave": 26, "tasks": ["31"], "description": "Full Docker Compose deployment configuration", "dependsOn": ["28", "29", "30"] },
    { "wave": 27, "tasks": ["32"], "description": "Integration tests and smoke tests", "dependsOn": ["31"] },
    { "wave": 28, "tasks": ["33"], "description": "Final checkpoint", "dependsOn": ["32"] }
  ]
}
```
