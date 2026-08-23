"""Pydantic v2 data models for the Historical RAG Platform."""
from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

class SourceMetadata(BaseModel):
    ia_identifier: str
    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    pub_date: str | None = None          # raw string from IA (may be fuzzy)
    language: str | None = None
    subject: list[str] = Field(default_factory=list)
    collection: str | None = None
    ia_url: str | None = None
    # Rights fields from IA metadata API
    licenseurl: str | None = None
    rights: str | None = None


class CleanedText(BaseModel):
    text: str
    # List of (char_position_of_marker, page_number) tuples
    page_markers: list[tuple[int, int]] = Field(default_factory=list)


class Chunk(BaseModel):
    id: int | None = None
    source_id: int
    text: str
    page_or_section: str | None = None
    embedding_id: str | None = None
    capture_timestamp: datetime.datetime | None = None   # web snapshot chunks only
    char_range_start: int
    char_range_end: int
    token_count: int | None = None

    # Source metadata — populated during hydration so the frontend can display
    # citation cards with title, author, collection, snippet, etc.
    source_title: str | None = None
    author: str | None = None
    collection: str | None = None
    source_type: str | None = None
    ia_url: str | None = None
    year: int | None = None
    pub_date: str | None = None
    page_number: int | None = None
    snippet: str = ""
    ia_identifier: str | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Chunk):
            return NotImplemented
        return self.model_dump() == other.model_dump()


class ChunkWithEmbedding(Chunk):
    embedding: list[float] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

class StructuredQuery(BaseModel):
    raw_query: str
    topic_keywords: list[str] = Field(default_factory=list)
    date_range_start: int | None = None     # year
    date_range_end: int | None = None       # year
    source_type_hint: str | None = None
    is_temporal_comparison: bool = False
    domain: str | None = None  # website domain filter (e.g. "cs.stanford.edu")


class RankedChunk(BaseModel):
    chunk: Chunk
    rank: int
    score: float = 0.0
    source_metadata: SourceMetadata | None = None


# ---------------------------------------------------------------------------
# Answer synthesis
# ---------------------------------------------------------------------------

class AnswerSegment(BaseModel):
    text: str
    citation_type: Literal["DIRECTLY_VERIFIED", "INFERRED", "UNKNOWN"]
    source_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[int] = Field(default_factory=list)
    launched_warning: bool = False  # set when "launched"/"went live" appears for web sources


class CitationDistribution(BaseModel):
    """Percentage breakdown of citation types in an answer."""
    verified: int = 0   # DIRECTLY_VERIFIED segments as %
    inferred: int = 0   # INFERRED segments as %
    unknown: int = 0    # UNKNOWN segments as %


class AnswerResponse(BaseModel):
    answer_id: str
    query: str
    answer_segments: list[AnswerSegment] = Field(default_factory=list)
    retrieved_chunks: list[Chunk] = Field(default_factory=list)
    citation_distribution: CitationDistribution = Field(default_factory=CitationDistribution)

    def compute_citation_distribution(self) -> "AnswerResponse":
        """Compute citation_distribution from answer_segments in-place.

        Called after synthesis to populate the distribution field.
        Returns self for chaining.
        """
        segments = self.answer_segments
        if not segments:
            self.citation_distribution = CitationDistribution(verified=100, inferred=0, unknown=0)
            return self

        total = len(segments)
        verified_count = sum(1 for s in segments if s.citation_type == "DIRECTLY_VERIFIED")
        inferred_count = sum(1 for s in segments if s.citation_type == "INFERRED")
        unknown_count = sum(1 for s in segments if s.citation_type == "UNKNOWN")

        self.citation_distribution = CitationDistribution(
            verified=round((verified_count / total) * 100),
            inferred=round((inferred_count / total) * 100),
            unknown=max(0, 100 - round((verified_count / total) * 100) - round((inferred_count / total) * 100)),
        )
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AnswerResponse):
            return NotImplemented
        return self.model_dump() == other.model_dump()


# ---------------------------------------------------------------------------
# Wayback / CDX
# ---------------------------------------------------------------------------

class SnapshotRecord(BaseModel):
    domain: str
    url: str
    snapshot_timestamp: datetime.datetime
    status_code: int | None = None
    digest: str | None = None
    fetched_flag: bool = False
    fetched_at: datetime.datetime | None = None


class SnapshotStats(BaseModel):
    domain: str
    earliest: datetime.datetime | None = None
    latest: datetime.datetime | None = None
    total_count: int = 0
    per_year: dict[int, int] = Field(default_factory=dict)  # year -> count
    gap_years: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Evaluation harness
# ---------------------------------------------------------------------------

class RetrievalMetrics(BaseModel):
    recall_10: float = 0.0
    precision_10: float = 0.0
    mrr: float = 0.0
    ndcg_10: float = 0.0


class FaithfulnessVerdict(BaseModel):
    answer_id: str
    claim_text: str
    chunk_id: int
    verdict: Literal["supported", "not_supported"]


class LabeledQuery(BaseModel):
    id: str
    query: str
    query_type: Literal[
        "book_lookup", "date_range_filtering", "website_history", "cross_decade_comparison"
    ]
    relevant_chunk_ids: list[int]
    date_range: dict[str, int] | None = None


class RetrievalConfig(BaseModel):
    name: str
    use_bm25: bool = True
    use_vector: bool = True
    use_rrf: bool = True
    use_reranker: bool = True
    top_k: int = 10


class GroundTruth(BaseModel):
    query_id: str
    relevant_chunk_ids: list[int]


class RetrievalResult(BaseModel):
    query_id: str
    retrieved_chunk_ids: list[int]   # ordered by rank


class EvalResults(BaseModel):
    config_name: str
    metrics: RetrievalMetrics
    citation_correctness: float | None = None
    query_count: int = 0
