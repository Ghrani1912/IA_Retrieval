# Historical Intelligence & RAG Platform

> AI-powered historical information retrieval and reasoning on the Internet Archive.

Ask questions about historical AI research, government documents, and education papers — get synthesized answers with verified citations from primary sources spanning 1970–1998.

![Architecture](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Frontend](https://img.shields.io/badge/React_19-61DAFB?style=flat&logo=react&logoColor=black)
![Search](https://img.shields.io/badge/OpenSearch-005EB8?style=flat&logo=opensearch&logoColor=white)
![Vector DB](https://img.shields.io/badge/Qdrant-DC382C?style=flat&logo=qdrant&logoColor=white)

---

## What It Does

This platform ingests public-domain documents from the Internet Archive, indexes them for hybrid search (keyword + semantic), and uses an LLM to synthesize answers with citations — all grounded in the indexed corpus.

### Core Capabilities

- **Hybrid Retrieval** — BM25 keyword search + dense vector search fused with Reciprocal Rank Fusion, then re-scored with a cross-encoder reranker (BGE-reranker-v2-m3)
- **Blended Reranking** — 70% RRF fusion score + 30% cross-encoder score, balancing lexical precision with semantic understanding
- **LLM Synthesis** — Answers generated from retrieved evidence chunks only, with per-claim citation verification (DIRECTLY_VERIFIED / SUPPORTED / INFERRED / UNKNOWN)
- **On-Demand Ingestion** — When retrieval finds thin results, the system automatically searches IA for relevant papers, ingests them in the background, and indexes them for future queries
- **Wayback Machine Integration** — Query website snapshot history via CDX API cache, browse capture timelines, and fetch on-demand web content for specific domains
- **Multi-Source Corpus** — 10,671+ chunks across DTIC (defense research), ERIC (education), and Americana (encyclopedias)
- **Streaming Responses** — Real-time token-by-token answer generation via Server-Sent Events

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                          │
│  ChatView · SourceBrowser · WebsiteTimeMachine · TimelineView  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ SSE / REST
┌───────────────────────────▼─────────────────────────────────────┐
│                     FastAPI Backend (port 8000)                 │
│                                                                 │
│  POST /query          POST /query/stream     GET /health       │
│  POST /ingest         GET /snapshots/{domain} GET /corpus/stats│
│  GET /sources         GET /sources/{id}/chunks                 │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Retrieval   │  │   Synthesis  │  │    Ingestion         │   │
│  │  Pipeline    │  │   Pipeline   │  │    Pipeline          │   │
│  │             │  │              │  │                      │   │
│  │ BM25+Vector │  │ Groq/Gemini  │  │ discover → fetch →  │   │
│  │ → RRF Fuse  │  │ LLM synthesis│  │ clean → chunk →     │   │
│  │ → Rerank    │  │ + streaming  │  │ embed → index       │   │
│  └──────┬──────┘  └──────────────┘  └──────────────────────┘   │
│         │                                                       │
└─────────┼───────────────────────────────────────────────────────┘
          │
┌─────────▼───────────────────────────────────────────────────────┐
│                     Data Layer                                  │
│                                                                 │
│  ┌──────────┐  ┌────────────┐  ┌────────┐  ┌──────────────┐    │
│  │ Postgres  │  │ OpenSearch │  │ Qdrant │  │    Redis     │    │
│  │ (source   │  │ (BM25      │  │(vector │  │   (job queue │    │
│  │  metadata,│  │  keyword   │  │ embed  │  │   for arq    │    │
│  │  chunks,  │  │  search)   │  │ search)│  │   worker)    │    │
│  │  eval)    │  │            │  │        │  │              │    │
│  └──────────┘  └────────────┘  └────────┘  └──────────────┘    │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Internet Archive API + CDX Cache            │   │
│  │     discover() · fetch_fulltext() · snapshot metadata    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker Desktop (for Postgres, OpenSearch, Qdrant, Redis)
- NVIDIA GPU with CUDA (optional, for faster embedding/reranking)
- LLM API key (OpenAI or Groq)

### 1. Start Infrastructure

```bash
docker compose up -d postgres opensearch qdrant redis
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your LLM API key:
# LLM_API_KEY=your-key-here
# LLM_MODEL=gpt-4o-mini
# LLM_BASE_URL=https://api.openai.com/v1
```

### 3. Install Python Dependencies

```bash
pip install -e ".[dev]"
```

### 4. Run Database Migrations

```bash
alembic upgrade head
```

### 5. Start the Backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Start the Frontend

```bash
cd historical-intelligence
npm install
npm run dev
```

The app is now running at `http://localhost:3000`.

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Service connectivity check (Postgres, OpenSearch, Qdrant, Redis) |
| `/corpus/stats` | GET | Live corpus statistics (source count, chunk count, collection breakdown) |
| `/query` | POST | Full retrieval + synthesis pipeline (non-streaming) |
| `/query/stream` | POST | Streaming retrieval + synthesis via SSE |
| `/sources` | GET | List all ingested sources |
| `/sources/{id}/chunks` | GET | Chunks for a specific source |
| `/ingest` | POST | Trigger document ingestion (papers or website) |
| `/ingest/{job_id}/status` | GET | Check ingestion job progress |
| `/snapshots/{domain}` | GET | Wayback Machine snapshot statistics |
| `/snapshots/ingested-domains` | GET | List all domains with cached snapshots |

### Example Query

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are semantic networks used for in AI?", "filters": {}}'
```

### Example Streaming Query

```bash
curl -N -X POST http://localhost:8000/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "How does MYCIN expert system work?", "filters": {}}'
```

### Example Wayback Query

```bash
# Get snapshot stats for a domain
curl http://localhost:8000/snapshots/ai.mit.edu

# Query with domain context
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What did ai.mit.edu look like historically?", "filters": {"domain": "ai.mit.edu"}}'
```

---

## Retrieval Pipeline

The retrieval pipeline follows this sequence for every query:

```
User Query
    │
    ▼
Query Understanding (LLM extracts keywords, date range, domain)
    │
    ▼
┌─────────────────────────────────────┐
│  Parallel Retrieval                 │
│  ┌──────────┐    ┌──────────────┐   │
│  │ BM25     │    │ Vector (BGE  │   │
│  │ (OpenSrch│    │  M3 embed +  │   │
│  │ keyword) │    │  Qdrant)     │   │
│  └────┬─────┘    └──────┬───────┘   │
│       └────────┬────────┘           │
│                ▼                    │
│     Reciprocal Rank Fusion (RRF)    │
│     top-30 candidates               │
└─────────────────────────────────────┘
    │
    ▼
Cross-Encoder Reranking (BGE-reranker-v2-m3)
Blended score = 0.3 × reranker + 0.7 × normalized_RRF
    │
    ▼
Top-10 Evidence Chunks → LLM Synthesis
    │
    ▼
Answer with per-claim citations + citation verification distribution
```

### Why Blended Reranking?

Pure cross-encoder reranking (alpha=1.0) can promote encyclopedic/keyword-dense content over specific technical papers. Pure RRF (alpha=0.0) misses semantic relevance. The alpha=0.3 blend was chosen through systematic evaluation (9 configs × 45 queries) for robustness on edge queries.

---

## Corpus

| Collection | Description | Sources | Chunks |
|---|---|---|---|
| DTIC Archive | Defense Technical Information Center — government-funded AI/CS research papers (1970s–2000s) | ~2,660 | ~5,466 |
| ERIC Archive | Education Resources Information Center — education technology and CS education research | ~747 | ~3,908 |
| Americana | Encyclopedia Americana + Handbook of AI — broad AI topic coverage | ~5 | ~1,296 |
| **Total** | | **~3,412** | **~10,671** |

### On-Demand Ingestion

When a query returns thin results (< 3 unique sources), the system automatically:
1. Searches IA for DTIC papers matching the query
2. Fetches full text, cleans OCR noise, chunks, embeds, and indexes
3. Returns whatever it has immediately (no user wait)
4. Subsequent queries find the freshly ingested content

---

## Evaluation

The retrieval pipeline is benchmarked against a 45-query labeled set with multi-label ground truth (407 correct chunk IDs across 21 queries).

### Results (9-Config Comparison)

| Config | Recall@10 | Precision@10 | MRR | nDCG@10 |
|---|---|---|---|---|
| **blended_03 (production)** | **0.3335** | **0.2867** | **0.6121** | **0.3735** |
| rrf | 0.3273 | 0.2756 | 0.5826 | 0.3564 |
| blended_05 | 0.3443 | 0.3089 | 0.7477 | 0.4313 |
| vector_only | 0.3151 | 0.2867 | 0.6104 | 0.3634 |
| bm25_only | 0.2559 | 0.2311 | 0.5930 | 0.3108 |

**blended_03 chosen for robustness** — 82% tie rate with blended_05, wins on complex multi-agent queries, avoids over-reliance on cross-encoder scores.

### Running the Eval

```bash
# Full eval (all configs, ~20 min with GPU)
python -m app.eval.run_eval --configs all --skip-judge

# Single config
python -m app.eval.run_eval --configs blended_03

# With LLM faithfulness judge (requires API key)
python -m app.eval.run_eval --configs full_pipeline
```

---

## Frontend

Built with React 19 + Tailwind CSS + Vite. The frontend provides:

| View | Description |
|---|---|
| **ChatView** | Conversational Q&A with streaming responses, citation verification bars, and evidence cards |
| **SourceBrowser** | Browse all ingested sources by collection, view individual chunks |
| **WebsiteTimeMachine** | Enter a domain → see Wayback Machine snapshot timeline, capture frequency chart |
| **TimelineView** | Visualize document distribution across time periods |
| **TopBar** | Live corpus stats, collection filter, date range filter |

### Frontend Development

```bash
cd historical-intelligence
npm run dev       # Vite dev server on port 3000
npm run build     # Production build
npm run lint      # TypeScript type check
```

---

## Project Structure

```
IA/
├── app/
│   ├── api/routes/          # FastAPI route handlers
│   │   ├── query.py         # POST /query, POST /query/stream
│   │   ├── ingest.py        # POST /ingest, job status
│   │   ├── snapshots.py     # GET /snapshots/{domain}
│   │   ├── sources.py       # GET /sources
│   │   ├── corpus.py        # GET /corpus/stats
│   │   └── health.py        # GET /health
│   ├── ingestion/           # Document ingestion pipeline
│   │   ├── discover.py      # IA search (discover sources)
│   │   ├── fetch.py         # Full-text download from IA
│   │   ├── cleaner.py       # OCR cleanup, junk page detection
│   │   ├── chunker.py       # Text chunking with overlap
│   │   ├── embed.py         # BGE-M3 embedding generation
│   │   ├── index_bm25.py    # OpenSearch indexing
│   │   ├── index_vectors.py # Qdrant vector indexing
│   │   ├── copyright.py     # Copyright/access checks
│   │   ├── ondemand.py      # On-demand background ingestion
│   │   └── object_cache.py  # Local filesystem object cache
│   ├── retrieval/           # Search & ranking pipeline
│   │   ├── query_understanding.py  # LLM query parsing
│   │   ├── retrieve.py      # BM25 + vector retrieval
│   │   ├── rrf.py           # Reciprocal Rank Fusion
│   │   ├── reranker.py      # Cross-encoder reranking + blending
│   │   └── filters.py       # Date/collection/domain filters
│   ├── synthesis/           # LLM answer generation
│   │   └── synthesizer.py   # Groq/OpenAI synthesis + streaming
│   ├── wayback/             # Wayback Machine integration
│   │   ├── cdx.py           # CDX API client + cache
│   │   ├── ondemand.py      # On-demand website content fetch
│   │   ├── stats.py         # Snapshot statistics
│   │   └── metadata_answer.py  # Direct metadata Q&A
│   ├── eval/                # Evaluation harness
│   │   ├── run_eval.py      # CLI entry point
│   │   ├── configs.py       # 8 retrieval configurations
│   │   ├── metrics.py       # Recall/Precision/MRR/nDCG
│   │   ├── judge.py         # LLM-as-judge faithfulness
│   │   └── queries.json     # 45 labeled test queries
│   ├── jobs/                # Background task processing
│   │   └── worker.py        # arq worker for ingestion jobs
│   ├── models/              # Pydantic data models
│   ├── db/                  # Database connection utilities
│   └── config.py            # Settings from environment
├── historical-intelligence/  # React frontend
│   └── src/
│       ├── components/      # UI components
│       │   ├── ChatView.tsx
│       │   ├── SourceBrowser.tsx
│       │   ├── WebsiteTimeMachineView.tsx
│       │   ├── TimelineView.tsx
│       │   ├── EvidenceCards.tsx
│       │   ├── CitationConfidenceBar.tsx
│       │   └── TopBar.tsx
│       ├── services/        # API client
│       └── App.tsx          # Root component
├── alembic/                 # Database migrations
├── scripts/                 # Utility scripts
├── tests/                   # Test suite
├── docker-compose.yml       # Infrastructure services
├── pyproject.toml           # Python project config
└── .env.example             # Environment template
```

---

## Key Design Decisions

### Why Hybrid Search (BM25 + Vector)?

BM25 excels at exact keyword matches ("STRIPS planning", "MYCIN") while vector search catches semantic similarity ("speech understanding architecture" ≈ "speech recognition system"). RRF fusion combines both ranking lists without requiring score normalization.

### Why Blended Reranking (alpha=0.3)?

The cross-encoder reranker sometimes promotes keyword-dense encyclopedia entries over specific technical papers. A 70/30 RRF/reranker blend preserves the retrieval system's diversity while allowing semantic re-ranking to improve first-result quality. This was validated through 9-config evaluation on 45 labeled queries.

### Why On-Demand Ingestion?

A static index of ~10K chunks can't cover every possible query. On-demand ingestion extends coverage dynamically — when results are thin, the system fetches relevant papers from IA in the background. Users get an immediate answer from existing content, then can re-query for richer results.

### Why Multi-Label Ground Truth?

A single ground-truth label per query penalizes the system for finding equally valid alternative sources. Multi-label evaluation (adding Americana Handbook of AI chunks as valid answers alongside DTIC/ERIC) produces fairer metrics that reflect real retrieval quality.

---

## License

This project uses only public-domain and freely available content from the Internet Archive. See individual source licenses for specifics.
