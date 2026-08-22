# Requirements Document

## Introduction

The Historical Intelligence & RAG Platform is an AI-powered historical information retrieval and reasoning system built on top of the Internet Archive (IA). It enables researchers to search, understand, analyze, and compare knowledge across public-domain books, research papers, government documents, and archived websites over time. The platform combines BM25 keyword search, vector semantic search, temporal filtering, and a cross-encoder reranker into a hybrid retrieval pipeline, culminating in evidence-grounded LLM-synthesized answers with citation confidence labels. The MVP targets a solo engineer building over 6–10 weeks, deploying on a single VM via Docker Compose.

---

## Glossary

- **Platform**: The Historical Intelligence & RAG Platform system as a whole.
- **Ingestion_Pipeline**: The subsystem responsible for discovering, fetching, cleaning, chunking, and indexing documents from the Internet Archive.
- **Wayback_Pipeline**: The subsystem responsible for ingesting and indexing archived website snapshots via the Wayback Machine CDX and Memento APIs.
- **Retrieval_Engine**: The subsystem that processes user queries and returns ranked, filtered document chunks.
- **Answer_Synthesizer**: The subsystem that takes ranked evidence chunks and produces an LLM-generated answer with structured citations.
- **Citation_System**: The module responsible for labeling each answer claim as DIRECTLY_VERIFIED, INFERRED, or UNKNOWN.
- **Evaluation_Harness**: The offline subsystem that benchmarks retrieval configurations against a hand-labeled query set.
- **UI**: The React/Next.js web frontend including the Research Chat, Source Explorer, and Timeline views.
- **IA**: Internet Archive — the external data source at archive.org.
- **CDX_Cache**: The PostgreSQL table `website_snapshots` storing CDX API responses to avoid live per-request CDX queries.
- **Object_Cache**: Local filesystem cache (Docker volume `ia_cache_data`, mounted at `/cache` inside the container) that stores raw source files fetched from IA. MinIO was the original choice but was archived and abandoned in early 2026 — the filesystem cache is equivalent for MVP, and the interface can be swapped to S3/R2 later without changing fetch logic.
- **BM25_Index**: The OpenSearch full-text index providing BM25 keyword retrieval over document chunks.
- **Vector_Index**: The Qdrant vector database storing BGE-M3 embeddings for semantic retrieval over document chunks.
- **RRF**: Reciprocal Rank Fusion — the score fusion algorithm combining multiple ranked candidate lists.
- **Reranker**: The BGE cross-encoder model that re-scores fused candidate chunks against the original query.
- **Source**: A single IA item (book, paper, gov doc, or website snapshot set) represented in the `sources` table.
- **Chunk**: A text segment of approximately 400–600 tokens derived from a Source, stored in the `chunks` table.
- **Snapshot**: A single Wayback Machine capture of a URL, stored in the `website_snapshots` table.
- **Capture_Timestamp**: The timestamp recorded by the Wayback Machine when a URL was archived — distinct from a publication date.
- **PD**: Public Domain — works for which full OCR text is accessible from IA (typically US works pre-1928 or explicitly marked open access).
- **Metadata_Only_Source**: A Source whose full text is unavailable (in-copyright) and for which only metadata is stored.
- **Job_Queue**: The async task queue (arq or Celery) used to execute ingestion jobs without blocking request threads.
- **Evidence_Block**: A structured object linking an answer segment to one or more Chunks with a confidence label.
- **LLM**: Large Language Model — the external model used for query understanding and answer synthesis.
- **BGE-M3**: The embedding model used to generate chunk and query vector representations.

---

## Requirements

### Requirement 1: Repository and Environment Setup

**User Story:** As a developer, I want a reproducible local development environment, so that I can iterate quickly without environment-specific failures.

#### Acceptance Criteria

1. THE Platform SHALL provide a Docker Compose file that starts `postgres`, `opensearch`, and `qdrant` services with a single `docker compose up` command.
2. WHEN the Docker Compose stack starts, THE Platform SHALL expose PostgreSQL on port 5432, OpenSearch on port 9200, and Qdrant on port 6333.
3. THE Platform SHALL define all Python dependencies in a `pyproject.toml` or `requirements.txt` file with pinned version numbers.
4. WHEN a developer runs the dependency install command, THE Platform SHALL install all dependencies without version conflict errors.
5. THE Platform SHALL include a `.env.example` file listing all required environment variables (database URLs, object storage credentials, LLM API keys).
6. WHEN the application starts with a valid `.env` file, THE Platform SHALL connect to all three backing services and log a successful connection message for each.

---

### Requirement 2: Internet Archive Discovery Adapter

**User Story:** As a developer, I want a discovery adapter that queries the IA Advanced Search API, so that I can populate the source catalog with real IA identifiers and metadata.

#### Acceptance Criteria

1. THE Ingestion_Pipeline SHALL expose a `discover(query, date_range, media_type) -> list[SourceMetadata]` function that wraps the IA Advanced Search API.
2. WHEN the IA Advanced Search API returns a paginated response, THE Ingestion_Pipeline SHALL follow all result pages until the full result set is retrieved, respecting the 10,000-result paging cap.
3. WHEN a discovery result is returned, THE Ingestion_Pipeline SHALL persist each item's `ia_identifier`, `title`, `author`, `publisher`, `pub_date`, `language`, `subject[]`, `collection`, and `ia_url` to the `sources` table immediately, before any fetch or indexing step.
4. WHEN the IA Advanced Search API returns an HTTP error or a network timeout, THE Ingestion_Pipeline SHALL retry the request with exponential backoff up to 3 attempts before logging the failure and continuing with the remaining items.
5. WHEN a `discover` call is re-run for a query that has already been discovered, THE Ingestion_Pipeline SHALL upsert source records by `ia_identifier` rather than creating duplicate rows.

---

### Requirement 3: Full-Text Fetch Adapter with Object Cache

**User Story:** As a developer, I want a fetch adapter that retrieves OCR text from IA and caches it locally, so that repeated pipeline runs do not re-download the same files from IA.

#### Acceptance Criteria

1. THE Ingestion_Pipeline SHALL expose a `fetch_fulltext(identifier) -> str | None` function that retrieves the `_djvu.txt` OCR file for a given IA identifier via the IA Metadata API.
2. WHEN the `_djvu.txt` file is unavailable and a `_hocr.html` file is present, THE Ingestion_Pipeline SHALL fall back to fetching `_hocr.html` to extract raw text.
3. WHEN a raw OCR file is successfully fetched, THE Ingestion_Pipeline SHALL write the file to the Object_Cache keyed by `ia_identifier` before returning the text content.
4. WHEN `fetch_fulltext` is called for an `ia_identifier` that already exists in the Object_Cache, THE Ingestion_Pipeline SHALL read from the Object_Cache and SHALL NOT make a network request to IA.
5. WHEN neither `_djvu.txt` nor `_hocr.html` is available for an identifier (in-copyright or missing OCR), THE Ingestion_Pipeline SHALL return `None`, update the corresponding `sources` row to set `source_type = 'metadata_only'`, and SHALL NOT raise an exception.
6. WHEN the IA file download fails with an HTTP 4xx or 5xx error, THE Ingestion_Pipeline SHALL retry the download up to 3 times with exponential backoff before marking the source as `fetch_failed`.

---

### Requirement 4: Text Cleaning

**User Story:** As a developer, I want a text cleaning step that normalizes OCR output, so that downstream chunking and indexing operate on consistent text without corrupting citation fidelity.

#### Acceptance Criteria

1. WHEN raw OCR text is processed by the cleaning step, THE Ingestion_Pipeline SHALL remove page-break artifacts, running headers, and running footers while preserving the page boundary marker for each page.
2. WHEN OCR line-break hyphenation is detected (a word split across a line break with a hyphen), THE Ingestion_Pipeline SHALL rejoin the word parts into a single token.
3. THE Ingestion_Pipeline SHALL preserve the inline page number anchor (derived from form-feed characters in `_djvu.txt`) for every page boundary after cleaning, so that downstream chunks can reference the correct page number.
4. WHEN cleaned text is produced, THE Ingestion_Pipeline SHALL NOT alter or paraphrase OCR-produced word tokens — cleaning SHALL be limited to structural normalization, not content substitution.

---

### Requirement 5: Paragraph-Aware Chunking

**User Story:** As a developer, I want a paragraph-aware chunker that produces page-accurate chunks, so that every chunk can be traced back to a specific page in the source document.

#### Acceptance Criteria

1. WHEN cleaned text is chunked, THE Ingestion_Pipeline SHALL produce chunks of approximately 400–600 tokens each, with a 15% token overlap between adjacent chunks.
2. WHEN a chunk crosses a paragraph boundary, THE Ingestion_Pipeline SHALL prefer splitting at the paragraph boundary rather than mid-sentence, provided the resulting chunk size remains within the 400–600 token range.
3. WHEN a chunk is created, THE Ingestion_Pipeline SHALL record the `source_id`, `page_or_section`, and `char_range` (start and end character offset in the cleaned text) as chunk metadata.
4. WHEN a chunk spans multiple pages, THE Ingestion_Pipeline SHALL record the page number of the first token of the chunk in the `page_or_section` field.
5. FOR ALL chunks produced from a single source, the union of all `char_range` intervals SHALL cover the full character span of the cleaned text with no uncovered gap larger than the overlap window.

---

### Requirement 6: BM25 Indexing in OpenSearch

**User Story:** As a developer, I want all chunks indexed in OpenSearch for BM25 keyword retrieval, so that keyword-heavy queries can retrieve exact-match and term-frequency-ranked results.

#### Acceptance Criteria

1. THE Ingestion_Pipeline SHALL create an OpenSearch index with a `text` field configured for full-text BM25 analysis and keyword fields for `date`, `source_type`, `collection`, and `ia_identifier`.
2. WHEN chunks are produced by the chunker, THE Ingestion_Pipeline SHALL bulk-index all chunks into the BM25_Index within the same ingestion run.
3. WHEN a BM25 query is issued for a term that appears in an indexed chunk, THE BM25_Index SHALL return that chunk within the top 50 results.
4. WHEN a source is re-ingested with updated chunks (e.g., after a cleaning fix), THE Ingestion_Pipeline SHALL delete the existing chunk documents for that `ia_identifier` from the BM25_Index before re-indexing.
5. WHEN the OpenSearch bulk indexing request fails, THE Ingestion_Pipeline SHALL log the failed chunk IDs and retry the batch before marking the source as `index_failed`.

---

### Requirement 7: Vector Embeddings and Qdrant Indexing

**User Story:** As a developer, I want all chunks embedded with BGE-M3 and stored in Qdrant, so that semantic similarity queries can retrieve thematically relevant chunks even without exact keyword overlap.

#### Acceptance Criteria

1. THE Ingestion_Pipeline SHALL generate a BGE-M3 embedding vector for every chunk using the `sentence-transformers` library or a compatible hosted embedding API.
2. WHEN a chunk embedding is generated, THE Ingestion_Pipeline SHALL insert the embedding into the Vector_Index with a payload containing `source_id`, `ia_identifier`, `date`, `source_type`, `collection`, and `capture_timestamp` (NULL for non-web sources).
3. WHEN a batch of embeddings is inserted into Qdrant, THE Ingestion_Pipeline SHALL store the returned Qdrant point ID as the `embedding_id` in the `chunks` table.
4. WHEN a vector similarity query is issued with an embedding of a semantically related query, THE Vector_Index SHALL return at least one chunk from the expected source document within the top 50 results.
5. WHEN a source is re-ingested, THE Ingestion_Pipeline SHALL delete existing Qdrant points for all chunks belonging to that `ia_identifier` before inserting new embeddings.

---

### Requirement 8: CDX API Ingestion with Caching (Wayback Pipeline)

**User Story:** As a developer, I want a CDX ingestion step that caches snapshot metadata in PostgreSQL, so that snapshot statistics can be served without issuing live CDX API calls per user request.

#### Acceptance Criteria

1. THE Wayback_Pipeline SHALL expose a `get_snapshots(domain) -> list[SnapshotRecord]` function that queries the Wayback CDX API for all snapshots of a given domain and stores results in the `website_snapshots` table.
2. WHEN the CDX API is queried, THE Wayback_Pipeline SHALL issue at most 1 request per second to respect the CDX rate limit of approximately 60 requests per minute.
3. WHEN the CDX API returns an HTTP 429 response, THE Wayback_Pipeline SHALL apply exponential backoff starting at 2 seconds before retrying.
4. WHEN `get_snapshots` is called for a domain that already has cached snapshot records with a `fetched_at` timestamp within the last 24 hours, THE Wayback_Pipeline SHALL return the cached records and SHALL NOT query the CDX API again.
5. WHEN snapshot records are stored in the `website_snapshots` table, THE Wayback_Pipeline SHALL record `domain`, `url`, `snapshot_timestamp`, `status_code`, `digest`, and `fetched_flag = false` for each snapshot.
6. WHEN the Platform computes snapshot statistics (earliest snapshot, latest snapshot, count, per-year histogram, active-year gaps) for a domain, THE Wayback_Pipeline SHALL derive these statistics from the cached `website_snapshots` records, not from live CDX API calls.
7. THE Platform SHALL NOT issue CDX API requests in response to a user query — all CDX data SHALL be pre-cached during ingestion.

---

### Requirement 9: On-Demand Wayback Snapshot Fetch (Wayback Pipeline)

**User Story:** As a developer, I want on-demand HTML fetching for specific Wayback snapshots, so that website content can be queried without pre-fetching every snapshot.

#### Acceptance Criteria

1. WHEN a user submits a content query targeting a specific domain and time period, THE Wayback_Pipeline SHALL fetch the HTML for relevant snapshots on demand via the Memento API at `web.archive.org/web/{timestamp}/{url}`.
2. WHEN a Wayback HTML snapshot is fetched, THE Wayback_Pipeline SHALL extract the main text content, run it through the same cleaning, chunking, and embedding pipeline as document sources, and tag each chunk with `capture_timestamp` equal to the Wayback snapshot timestamp.
3. WHEN a snapshot is successfully fetched and indexed, THE Wayback_Pipeline SHALL set `fetched_flag = true` on the corresponding `website_snapshots` row.
4. WHEN a snapshot for a given `(url, snapshot_timestamp)` has already been fetched and indexed (`fetched_flag = true`), THE Wayback_Pipeline SHALL use the existing chunk records and SHALL NOT re-fetch the snapshot HTML.
5. WHEN Wayback snapshot chunks are stored, THE Ingestion_Pipeline SHALL record `capture_timestamp` in the `chunks` table and SHALL NOT populate a `pub_date` field for website content.

---

### Requirement 10: Metadata-Only Source Handling

**User Story:** As a developer, I want in-copyright and fetch-failed sources to be stored as metadata-only records, so that the Platform degrades gracefully without silently excluding sources from the catalog.

#### Acceptance Criteria

1. WHEN a source cannot provide full text (in-copyright or missing OCR file), THE Ingestion_Pipeline SHALL store the source in the `sources` table with `source_type = 'metadata_only'` and SHALL NOT attempt to create chunks for that source.
2. WHEN a metadata-only source is returned in a query result, THE UI SHALL display a label indicating that full text is unavailable for this item.
3. THE Retrieval_Engine SHALL exclude `metadata_only` sources from BM25 and vector retrieval candidate sets.

---

### Requirement 11: Query Understanding

**User Story:** As a researcher, I want the Platform to interpret my natural-language query before retrieval, so that date ranges, source types, and topic focus are correctly applied to the search.

#### Acceptance Criteria

1. WHEN a user submits a query, THE Retrieval_Engine SHALL issue an LLM call to extract a structured query object containing: topic keywords, inferred date range (start_year, end_year or null), source-type hint (books, papers, websites, or null), and whether the query implies a temporal comparison.
2. WHEN the LLM query understanding step produces a date range, THE Retrieval_Engine SHALL use that date range as a hard filter applied before retrieval fusion.
3. WHEN the LLM query understanding step fails or times out, THE Retrieval_Engine SHALL fall back to running the raw user query string through retrieval without extracted filters, and SHALL log the failure.
4. WHEN query understanding produces a source-type hint, THE Retrieval_Engine SHALL pass the hint as a metadata filter to both the BM25_Index and Vector_Index queries.

---

### Requirement 12: Pre-Fusion Metadata and Temporal Filtering

**User Story:** As a developer, I want metadata and temporal filters applied before candidate fusion, so that the top-K budget is not wasted on out-of-scope results.

#### Acceptance Criteria

1. WHEN a date range filter is active, THE Retrieval_Engine SHALL apply the filter to BM25 and vector candidate queries before RRF fusion, restricting both candidate sets to chunks whose source `pub_date` (or `capture_timestamp` for web sources) falls within the specified range.
2. WHEN a source-type filter is active, THE Retrieval_Engine SHALL restrict both BM25 and vector candidate sets to chunks whose `source_type` matches the filter value before fusion.
3. WHEN a collection filter is active, THE Retrieval_Engine SHALL restrict both candidate sets to chunks belonging to the specified IA collection before fusion.
4. WHEN no filters are active, THE Retrieval_Engine SHALL query both BM25_Index and Vector_Index without date, type, or collection restrictions.

---

### Requirement 13: Parallel BM25 and Vector Retrieval

**User Story:** As a developer, I want parallel execution of BM25 and vector retrieval, so that query latency is bounded by the slower of the two, not their sum.

#### Acceptance Criteria

1. WHEN a query is processed, THE Retrieval_Engine SHALL execute the BM25 query against the BM25_Index and the vector similarity query against the Vector_Index concurrently.
2. WHEN the BM25 query completes, THE Retrieval_Engine SHALL return the top 50 BM25 candidate chunks with their rank positions.
3. WHEN the vector query completes, THE Retrieval_Engine SHALL return the top 50 vector candidate chunks with their rank positions.
4. WHEN either the BM25 or vector query fails, THE Retrieval_Engine SHALL proceed with the results from the successful query alone and log the failure, rather than returning an error to the user.

---

### Requirement 14: Reciprocal Rank Fusion

**User Story:** As a developer, I want RRF to merge the BM25 and vector candidate lists, so that documents ranked highly by either method receive a boosted combined score.

#### Acceptance Criteria

1. WHEN BM25 and vector candidate lists are available, THE Retrieval_Engine SHALL compute an RRF score for each candidate chunk using the formula: `score(chunk) = sum over each list of 1 / (60 + rank_in_list)`, where `k = 60`.
2. WHEN a chunk appears in both candidate lists, THE Retrieval_Engine SHALL sum its RRF contributions from both lists.
3. WHEN a chunk appears in only one candidate list, THE Retrieval_Engine SHALL use its contribution from that single list only.
4. WHEN RRF scoring is complete, THE Retrieval_Engine SHALL produce a merged candidate list of the top 30 chunks sorted by descending RRF score.

---

### Requirement 15: Cross-Encoder Reranking

**User Story:** As a developer, I want a BGE cross-encoder reranker applied to the fused candidates, so that the final retrieved set is semantically ranked relative to the specific query.

#### Acceptance Criteria

1. WHEN the RRF-fused candidate list is available, THE Retrieval_Engine SHALL run the BGE cross-encoder reranker model over the top 30 fused candidates against the original user query string.
2. WHEN the reranker produces scores, THE Retrieval_Engine SHALL sort the candidates by descending reranker score and return the top 8 to 12 chunks as the final evidence set.
3. WHEN the reranker model is unavailable or returns an error, THE Retrieval_Engine SHALL fall back to returning the top 8 to 12 chunks from the RRF-fused list without reranking and SHALL log the fallback event.

---

### Requirement 16: Answer Synthesis with Evidence-Grounded Citations

**User Story:** As a researcher, I want the Platform to synthesize answers grounded in retrieved evidence, so that every claim in the answer can be traced back to a specific source document and page.

#### Acceptance Criteria

1. WHEN the final evidence set is assembled, THE Answer_Synthesizer SHALL construct an LLM prompt that includes each evidence chunk with inline metadata: `title`, `author`, `pub_date`, `ia_identifier`, and `page_or_section`.
2. WHEN the LLM prompt is issued, THE Answer_Synthesizer SHALL instruct the LLM to answer only from the provided evidence chunks and to tag each claim with a citation reference.
3. WHEN the LLM response is received, THE Answer_Synthesizer SHALL parse the response into a structured JSON object with the schema: `{answer_segments: [{text: str, citation_type: "DIRECTLY_VERIFIED" | "INFERRED" | "UNKNOWN", source_ids: [str]}]}`.
4. WHEN a claim in the answer is drawn directly from a single evidence chunk, THE Answer_Synthesizer SHALL label that claim as `DIRECTLY_VERIFIED` and include the chunk's `source_id` and page number.
5. WHEN a claim in the answer is synthesized across multiple evidence chunks without direct quotation, THE Answer_Synthesizer SHALL label that claim as `INFERRED` and include all contributing source IDs.
6. WHEN the evidence set does not contain sufficient information to support a claim, THE Answer_Synthesizer SHALL label that segment as `UNKNOWN` rather than hallucinating an answer.
7. WHEN the structured JSON parse fails, THE Answer_Synthesizer SHALL log the raw LLM output and return an error response indicating synthesis failed, rather than returning malformed citation data to the UI.

---

### Requirement 17: Citation Confidence Labeling and Persistence

**User Story:** As a developer, I want citation confidence labels stored in the database, so that past answers can be audited and citation correctness can be evaluated offline.

#### Acceptance Criteria

1. WHEN an answer is generated, THE Citation_System SHALL persist one row per answer segment in the `evidence_citations` table with `answer_id`, `chunk_id`, and `confidence_label` set to one of `directly_verified`, `inferred`, or `unknown`.
2. WHEN a `confidence_label` is persisted, THE Citation_System SHALL validate that the value is one of the three permitted labels and SHALL reject any other value with a validation error.
3. THE Citation_System SHALL store at least one `evidence_citations` row for every non-UNKNOWN answer segment before the answer is returned to the UI.

---

### Requirement 18: Capture Timestamp vs. Publication Date Distinction

**User Story:** As a researcher, I want the Platform to clearly distinguish between a website's first archive date and its launch date, so that I do not draw incorrect historical conclusions about when a site went live.

#### Acceptance Criteria

1. THE Platform SHALL store `capture_timestamp` and `pub_date` as separate fields in the data model and SHALL NOT populate `pub_date` for website snapshot chunks.
2. WHEN the UI displays the earliest archived date for a website, THE UI SHALL render the label "Earliest Archived Snapshot" and SHALL NOT use the phrase "website launched" or any equivalent.
3. WHEN the Answer_Synthesizer generates an answer about a website's history, THE Answer_Synthesizer SHALL instruct the LLM via a literal string template to use only "first archived" or "earliest snapshot" language — never "launched" — for website temporal references.
4. WHEN the LLM response contains the word "launched" in reference to a website's archive date, THE Answer_Synthesizer SHALL flag the response for a UI warning indicating the claim may conflate archive date with launch date.

---

### Requirement 19: Object Cache for IA Source Files

**User Story:** As a developer, I want all raw IA source files cached in object storage, so that a temporary IA outage does not break the ingestion pipeline on re-runs.

#### Acceptance Criteria

1. WHEN the Ingestion_Pipeline fetches a raw file from IA (djvu.txt, hocr.html, or PDF), THE Ingestion_Pipeline SHALL write the file to the Object_Cache before processing it.
2. WHEN a file fetch is requested and the file already exists in the Object_Cache, THE Ingestion_Pipeline SHALL read from the Object_Cache and SHALL NOT contact IA.
3. WHEN the Object_Cache is unavailable, THE Ingestion_Pipeline SHALL fall back to fetching directly from IA and SHALL log a cache-miss warning.
4. WHEN the Object_Cache write fails after a successful IA download, THE Ingestion_Pipeline SHALL proceed with the in-memory content for the current run and log the cache write failure without aborting the ingestion.

---

### Requirement 20: Asynchronous Ingestion Job Queue

**User Story:** As a developer, I want ingestion jobs processed asynchronously via a job queue, so that long-running I/O-bound ingestion does not block API request threads.

#### Acceptance Criteria

1. THE Platform SHALL provide an async job queue (using arq or Celery) that accepts ingestion task payloads specifying `query`, `date_range`, and `source_type`.
2. WHEN an ingestion job is enqueued, THE Job_Queue SHALL execute the full ingestion pipeline (discover → fetch → clean → chunk → embed → index) as a background task.
3. WHEN an ingestion job completes successfully, THE Job_Queue SHALL update the job status to `completed` with a timestamp and a count of sources and chunks ingested.
4. WHEN an ingestion job fails at any pipeline step, THE Job_Queue SHALL mark the job status as `failed`, record the error message and the step at which failure occurred, and SHALL NOT silently discard the failure.
5. WHEN an ingestion job is in progress, THE Platform SHALL expose a status endpoint that returns the current job status, progress count (sources processed vs total), and any partial errors.

---

### Requirement 21: Evaluation Harness — Query Labeling and Config Comparison

**User Story:** As a developer, I want an offline evaluation harness that benchmarks five retrieval configurations against a labeled query set, so that I have objective evidence that the full pipeline outperforms simpler baselines.

#### Acceptance Criteria

1. THE Evaluation_Harness SHALL support a labeled query set of 30 to 50 queries, each with at least one expected relevant chunk ID, covering at minimum four query types: book lookup, date-range filtering, website history, and cross-decade comparison.
2. THE Evaluation_Harness SHALL run each query against all five retrieval configurations: (1) vector-only, (2) BM25-only, (3) vector + BM25 simple merge, (4) vector + BM25 + RRF, and (5) vector + BM25 + RRF + reranker.
3. WHEN a retrieval configuration is evaluated against the labeled query set, THE Evaluation_Harness SHALL compute Recall@10, Precision@10, Mean Reciprocal Rank (MRR), and nDCG@10 for that configuration.
4. WHEN all five configurations have been evaluated, THE Evaluation_Harness SHALL produce a comparison table showing all four metrics for each configuration.
5. THE Evaluation_Harness SHALL persist evaluation run results (config name, metrics, timestamp) to a database table so that results from different runs can be compared over time.

---

### Requirement 22: Evaluation Harness — Faithfulness and Citation Correctness

**User Story:** As a developer, I want automated faithfulness and citation-correctness checks, so that I can detect when the LLM generates claims not supported by cited chunks.

#### Acceptance Criteria

1. THE Evaluation_Harness SHALL run an LLM-as-judge pass over each synthesized answer, checking whether each cited chunk actually supports its attributed claim.
2. WHEN the LLM judge determines a cited chunk does not support its claim, THE Evaluation_Harness SHALL record the answer ID, claim text, chunk ID, and a "not_supported" verdict in the evaluation results.
3. WHEN the LLM judge determines a cited chunk supports its claim, THE Evaluation_Harness SHALL record a "supported" verdict for that pair.
4. WHEN the faithfulness evaluation pass is complete, THE Evaluation_Harness SHALL compute a citation correctness rate as the ratio of supported verdicts to total evaluated claim-chunk pairs and output this metric alongside the retrieval metrics.
5. WHEN the citation correctness rate for the full pipeline (config 5) is below 0.8, THE Evaluation_Harness SHALL output a warning indicating that answer synthesis quality requires investigation.

---

### Requirement 23: Research Chat Interface

**User Story:** As a researcher, I want a conversational chat interface that returns cited answers, so that I can explore historical topics and immediately see which sources support each claim.

#### Acceptance Criteria

1. THE UI SHALL provide a chat input field that accepts natural-language queries and submits them to the Platform's query endpoint.
2. WHEN an answer is returned, THE UI SHALL render each answer segment as text with inline citation chips that display the source title, author, publication year, and confidence label (DIRECTLY VERIFIED, INFERRED, or UNKNOWN).
3. WHEN a user clicks a citation chip, THE UI SHALL expand or navigate to a detail view showing the cited chunk text, the source metadata (title, author, pub_date, ia_url), and the page or section reference.
4. WHEN a query is in progress, THE UI SHALL display a loading indicator and SHALL NOT submit a duplicate query until the current query completes or times out.
5. WHEN an answer segment is labeled UNKNOWN, THE UI SHALL render that segment with a distinct visual style (e.g., italics or a warning color) to indicate insufficient evidence.
6. WHEN a citation references a website snapshot chunk, THE UI SHALL display the `capture_timestamp` with the label "Archived on" and SHALL NOT display a publication date for that chunk.

---

### Requirement 24: Source Explorer

**User Story:** As a researcher, I want a source explorer that lets me browse and filter the ingested source catalog, so that I can understand what material is available before forming queries.

#### Acceptance Criteria

1. THE UI SHALL provide a Source Explorer view that lists all sources in the `sources` table with their `title`, `author`, `pub_date`, `source_type`, `collection`, and `ia_url`.
2. WHEN a user applies a filter by `source_type`, `collection`, date range, or language, THE UI SHALL update the source list to show only matching sources.
3. WHEN a user selects a source, THE UI SHALL display the full source metadata and, for non-metadata-only sources, the count of indexed chunks.
4. WHEN a source has `source_type = 'metadata_only'`, THE UI SHALL display a "Full text unavailable" badge on that source entry.
5. THE UI SHALL support pagination of source results, displaying no more than 50 sources per page.

---

### Requirement 25: Timeline View

**User Story:** As a researcher, I want a timeline bar chart showing source distribution over time, so that I can understand the temporal density of available evidence for a given query.

#### Acceptance Criteria

1. THE UI SHALL provide a Timeline view that renders a bar chart (using Plotly or D3) of source count grouped by year.
2. WHEN a query has been submitted, THE UI SHALL filter the Timeline to show only the sources retrieved for that query, not the entire corpus.
3. WHEN a user applies a date range filter in the Timeline, THE UI SHALL propagate that filter to the Source Explorer and the active query context.
4. WHEN the Timeline is rendered for a query over website sources, THE UI SHALL group bars by `capture_timestamp` year and label the chart axis as "Year Archived", not "Year Published".
5. WHEN no sources fall within a given year in the filtered result set, THE UI SHALL render a zero-height bar (or gap) for that year rather than omitting it, so temporal gaps in coverage are visible.

---

### Requirement 26: Source Copyright and Access Scope Enforcement

**User Story:** As a developer, I want the ingestion pipeline to enforce public-domain and open-access scoping, so that the Platform never indexes full text from in-copyright sources without authorization.

#### Acceptance Criteria

1. WHEN the Ingestion_Pipeline evaluates a source's access scope, THE Ingestion_Pipeline SHALL check the IA `licenseurl` or `rights` metadata field first: IF the field contains a Creative Commons URL or the string "publicdomain" (case-insensitive), THE Ingestion_Pipeline SHALL allow full text fetch and set `is_open_access = true`; IF the field contains "rights reserved" or "in-copyright", THE Ingestion_Pipeline SHALL mark the source as `metadata_only`.
2. WHEN the IA rights metadata field is absent or empty, THE Ingestion_Pipeline SHALL check whether `collection` is present in the `OPEN_ACCESS_COLLECTIONS` set loaded from `app/ingestion/open_access_collections.json`; IF present, THE Ingestion_Pipeline SHALL allow full text fetch and set `is_open_access = true`.
3. WHEN neither the rights metadata nor the collection check grants access, THE Ingestion_Pipeline SHALL apply a date heuristic using `pd_cutoff_year()` computed as `current_year - 96` at runtime — never a hardcoded year; IF `pub_date.year < pd_cutoff_year()`, THE Ingestion_Pipeline SHALL allow full text fetch.
4. WHEN `pub_date` is NULL, empty, or cannot be parsed (including fuzzy IA date strings such as `"19uu"` or `"circa 1920"`), THE Ingestion_Pipeline SHALL mark the source as `metadata_only`, set `is_open_access = false`, and SHALL log an `access-scope-undetermined` warning that includes the raw date string.
5. WHEN `pub_date.year >= pd_cutoff_year()` and no rights metadata or collection override applies, THE Ingestion_Pipeline SHALL mark the source as `metadata_only` and SHALL NOT fetch or index the full text.
6. THE Ingestion_Pipeline SHALL set the `sources.is_open_access` field based on the outcome of the access scope check; this field SHALL NOT be set anywhere else in the pipeline.
7. THE `OPEN_ACCESS_COLLECTIONS` set SHALL be loaded from `app/ingestion/open_access_collections.json` at application startup, logged at INFO level, and used as the sole definition of known open-access collections — no collection names SHALL be hardcoded in application logic.

---

### Requirement 27: API Endpoint Design

**User Story:** As a frontend developer, I want a well-defined FastAPI backend with typed endpoints, so that the UI can reliably consume query results, source metadata, and ingestion status.

#### Acceptance Criteria

1. THE Platform SHALL expose a `POST /query` endpoint that accepts `{query: str, filters: {date_range, source_type, collection}}` and returns the structured answer JSON defined in Requirement 16.
2. THE Platform SHALL expose a `GET /sources` endpoint that accepts filter query parameters (`source_type`, `collection`, `date_from`, `date_to`, `language`, `page`, `page_size`) and returns a paginated list of source records.
3. THE Platform SHALL expose a `GET /sources/{ia_identifier}` endpoint that returns the full metadata and chunk count for a single source.
4. THE Platform SHALL expose a `POST /ingest` endpoint that enqueues an ingestion job and returns a `job_id`.
5. THE Platform SHALL expose a `GET /ingest/{job_id}/status` endpoint that returns the current job status, progress, and any errors.
6. THE Platform SHALL expose a `GET /snapshots/{domain}` endpoint that returns cached snapshot statistics (earliest, latest, count, per-year histogram) for a domain without querying the CDX API live.
7. WHEN any API endpoint receives a request with invalid or missing required parameters, THE Platform SHALL return an HTTP 422 response with a structured error body identifying the invalid field.

---

### Requirement 28: Deployment via Docker Compose

**User Story:** As a developer, I want the complete Platform stack deployable on a single VM via Docker Compose, so that I can demonstrate the system without Kubernetes overhead.

#### Acceptance Criteria

1. THE Platform SHALL provide a `docker-compose.yml` that defines services for the FastAPI application, PostgreSQL, OpenSearch, Qdrant, MinIO (object storage), and the Job_Queue worker.
2. WHEN `docker compose up` is run on a clean host with Docker installed, THE Platform SHALL start all services and reach a healthy state within 3 minutes.
3. WHEN the FastAPI application container starts, THE Platform SHALL run database migrations automatically before accepting requests.
4. WHEN a service in the Compose stack fails its health check, THE Platform SHALL not start the application container until all backing service health checks pass.
5. THE Platform SHALL define resource limits (memory and CPU) for the OpenSearch and Qdrant containers in the Compose file to prevent a single service from consuming all VM resources.

---

### Requirement 29: Parsers and Serializers — Round-Trip Integrity

**User Story:** As a developer, I want all data serialization and deserialization steps to be round-trip safe, so that data is not silently corrupted as it passes between pipeline stages or is stored and retrieved.

#### Acceptance Criteria

1. THE Ingestion_Pipeline SHALL expose a `serialize_chunk(chunk: Chunk) -> dict` function and a `deserialize_chunk(data: dict) -> Chunk` function for the chunk data model.
2. THE Ingestion_Pipeline SHALL expose a `format_answer(answer: AnswerResponse) -> str` function and a `parse_answer(raw: str) -> AnswerResponse` function for the LLM answer JSON format.
3. FOR ALL valid Chunk objects, serializing then deserializing SHALL produce a Chunk object equal to the original (round-trip property).
4. FOR ALL valid AnswerResponse objects, formatting then parsing SHALL produce an AnswerResponse equal to the original (round-trip property).
5. WHEN a `deserialize_chunk` call receives malformed input data, THE Ingestion_Pipeline SHALL raise a typed `ChunkDeserializationError` with a message identifying the offending field.
6. WHEN a `parse_answer` call receives malformed JSON, THE Answer_Synthesizer SHALL raise a typed `AnswerParseError` rather than propagating a generic JSON parse exception.

---

### Requirement 30: System Observability and Logging

**User Story:** As a developer, I want structured logs and key operational metrics emitted by the Platform, so that I can diagnose failures and monitor pipeline health.

#### Acceptance Criteria

1. THE Platform SHALL emit structured JSON logs for all ingestion pipeline steps, including step name, `ia_identifier`, duration in milliseconds, and outcome (success, skipped, failed).
2. WHEN a retrieval query is processed, THE Retrieval_Engine SHALL log the query ID, extracted filters, BM25 candidate count, vector candidate count, post-RRF count, post-rerank count, and total query latency in milliseconds.
3. WHEN an LLM call (query understanding or answer synthesis) is issued, THE Platform SHALL log the call type, model name, token counts (prompt and completion), latency in milliseconds, and outcome.
4. WHEN any pipeline step raises an unhandled exception, THE Platform SHALL log the full exception traceback at ERROR level and SHALL NOT swallow the exception silently.
5. THE Platform SHALL expose a `GET /health` endpoint that returns the connectivity status of PostgreSQL, OpenSearch, Qdrant, and the Object_Cache.
