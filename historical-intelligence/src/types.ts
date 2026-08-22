export type CollectionType = 'DTIC' | 'ERIC' | 'Americana' | 'Wayback';

export type SourceType = 'Research Paper' | 'Book' | 'Government Document' | 'Website';

export type SourceStatus = 'indexed' | 'metadata_only' | 'fetch_failed';

export type CitationType = 'directly_verified' | 'inferred' | 'unknown';

export interface SourceDocument {
  id: string;
  ia_identifier: string;
  title: string;
  author: string;
  year: number;
  pub_date?: string;
  capture_timestamp?: string;
  collection: CollectionType;
  source_type: SourceType;
  chunk_count: number;
  status: SourceStatus;
  publisher?: string;
  language: string;
  subjects: string[];
  ia_url: string;
  abstract?: string;
}

export interface RetrievedChunk {
  id: string;
  source_id: string;
  source_title: string;
  author?: string;
  year?: number;
  pub_date?: string;
  capture_timestamp?: string;
  domain?: string;
  collection: CollectionType;
  source_type: SourceType;
  page_number?: number;
  snippet: string;
  ia_url: string;
  similarity_score?: number;
  citation_type?: CitationType;
}

export interface AnswerSegment {
  text: string;
  citation_index?: number;
  citation_type: CitationType;
  chunk_ids: string[];
}

export interface AnswerResponse {
  query: string;
  answer: string;
  answer_segments: AnswerSegment[];
  retrieved_chunks: RetrievedChunk[];
  corpus_stats: {
    total_sources: number;
    total_chunks: number;
  };
  citation_distribution: {
    verified: number;
    inferred: number;
    unknown: number;
  };
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  statusUpdates?: string[];
  isStreaming?: boolean;
  isLoading?: boolean;
  error?: string;
  isNoChunksFound?: boolean;
  answerResponse?: AnswerResponse;
  timestamp: string;
  feedback?: 'up' | 'down';
  sourceFilter?: {
    domain?: string;
    source_id?: string;
    source_title?: string;
    date_from?: number;
    date_to?: number;
  };
}

export interface SnapshotData {
  domain: string;
  earliest_snapshot: string;
  latest_snapshot: string;
  total_snapshots: number;
  snapshots_per_year: Record<number, number>;
  gap_years: string[];
  summary?: string;
  top_topics?: string[];
}

export interface IngestJob {
  job_id: string;
  domain: string;
  status: 'queued' | 'crawling' | 'extracting_memento' | 'indexing_chunks' | 'completed' | 'failed';
  progress: number;
  message: string;
  chunks_found?: number;
}

export interface SourceFilterState {
  searchQuery: string;
  sourceType: string;
  collection: string;
  dateFrom: string;
  dateTo: string;
  language: string;
}

export interface AppSettings {
  showCitationConfidence: boolean;
  streamAnswers: boolean;
  backendUrl: string;
  useFallbackSimulation: boolean;
}
