import React, { useState, useEffect, useMemo } from 'react';
import {
  Search,
  Filter,
  BookOpen,
  ExternalLink,
  MessageSquare,
  ChevronLeft,
  ChevronRight,
  Layers,
  X,
  FileText,
  Bookmark
} from 'lucide-react';
import { SourceDocument, SourceFilterState } from '../types';
import { CORPUS_METRICS } from '../data/corpusData';
import { HistoricalApiService } from '../services/api';

interface SourceExplorerViewProps {
  onAskAboutSource: (source: SourceDocument) => void;
  onSelectSourceId?: (sourceId: string) => void;
}

export const SourceExplorerView: React.FC<SourceExplorerViewProps> = ({
  onAskAboutSource
}) => {
  const [filters, setFilters] = useState<SourceFilterState>({
    searchQuery: '',
    sourceType: 'All',
    collection: 'All',
    dateFrom: '',
    dateTo: '',
    language: 'All'
  });

  const [sources, setSources] = useState<SourceDocument[]>([]);
  const [totalSources, setTotalSources] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 12;
  const [selectedSource, setSelectedSource] = useState<SourceDocument | null>(null);

  useEffect(() => {
    let isMounted = true;
    HistoricalApiService.getSources(filters, page, pageSize).then(res => {
      if (isMounted) {
        setSources(res.sources);
        setTotalSources(res.total);
      }
    });
    return () => {
      isMounted = false;
    };
  }, [filters, page]);

  const handleFilterChange = (key: keyof SourceFilterState, val: string) => {
    setFilters(prev => ({ ...prev, [key]: val }));
    setPage(1);
  };

  const clearFilters = () => {
    setFilters({
      searchQuery: '',
      sourceType: 'All',
      collection: 'All',
      dateFrom: '',
      dateTo: '',
      language: 'All'
    });
    setPage(1);
  };

  const getCollectionBadgeColor = (collection: string) => {
    switch (collection) {
      case 'DTIC':
        return 'bg-[#4a5a6b] text-[#fffdf7]';
      case 'ERIC':
        return 'bg-[#3f6b3f] text-[#fffdf7]';
      case 'Americana':
        return 'bg-[#8b3a1f] text-[#fffdf7]';
      default:
        return 'bg-[#6b6252] text-[#fffdf7]';
    }
  };

  const totalPages = Math.max(1, Math.ceil(totalSources / pageSize));
  const startItem = (page - 1) * pageSize + 1;
  const endItem = Math.min(page * pageSize, totalSources);

  return (
    <div className="flex-1 flex flex-col h-[calc(100vh-3.5rem)] overflow-y-auto bg-[#f5f0e6] p-4 sm:p-6 select-none">
      <div className="max-w-6xl mx-auto w-full space-y-6">
        {/* Top Summary Bar */}
        <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-5 shadow-2xs">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-[#d8cfb8] pb-4">
            <div>
              <div className="flex items-center gap-2">
                <BookOpen className="w-5 h-5 text-[#8b3a1f]" />
                <h2 className="font-serif-heading text-xl font-bold text-[#2b2620]">
                  Full Archival Source Explorer
                </h2>
              </div>
              <p className="text-xs text-[#6b6252] mt-1 font-serif">
                Browse catalog records across DTIC technical papers, ERIC educational AI monographs, and Americana book archives.
              </p>
            </div>

            {/* Metric badge */}
            <div className="flex items-center gap-2 bg-[#f5f0e6] px-3.5 py-2 rounded-lg border border-[#d8cfb8]">
              <Layers className="w-4 h-4 text-[#8b3a1f]" />
              <div className="text-xs font-mono text-[#2b2620]">
                <span className="font-bold">{CORPUS_METRICS.totalChunks.toLocaleString()} chunks</span> across{' '}
                <span className="font-bold">{CORPUS_METRICS.totalSources} primary volumes</span>
              </div>
            </div>
          </div>

          {/* Filters Row */}
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5 text-xs">
            {/* Search Input */}
            <div className="lg:col-span-2 relative">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[#6b6252]" />
              <input
                type="text"
                placeholder="Search titles, authors, subjects..."
                value={filters.searchQuery}
                onChange={e => handleFilterChange('searchQuery', e.target.value)}
                className="w-full pl-8 pr-7 py-2 bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg text-[#2b2620] placeholder-[#6b6252]/70 focus:outline-none focus:border-[#8b3a1f]"
              />
              {filters.searchQuery && (
                <button
                  onClick={() => handleFilterChange('searchQuery', '')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#6b6252]"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Collection Filter */}
            <div>
              <select
                value={filters.collection}
                onChange={e => handleFilterChange('collection', e.target.value)}
                className="w-full py-2 px-2.5 bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg text-[#2b2620]"
              >
                <option value="All">All Collections (44)</option>
                <option value="DTIC">DTIC Defense (18)</option>
                <option value="ERIC">ERIC Education (14)</option>
                <option value="Americana">Americana (12)</option>
              </select>
            </div>

            {/* Source Type Filter */}
            <div>
              <select
                value={filters.sourceType}
                onChange={e => handleFilterChange('sourceType', e.target.value)}
                className="w-full py-2 px-2.5 bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg text-[#2b2620]"
              >
                <option value="All">All Source Types</option>
                <option value="Research Paper">Research Papers</option>
                <option value="Book">Monographs & Books</option>
                <option value="Government Document">Government Reports</option>
              </select>
            </div>

            {/* Date Range inputs */}
            <div className="flex items-center gap-1">
              <input
                type="number"
                placeholder="1970"
                min={1970}
                max={1998}
                value={filters.dateFrom}
                onChange={e => handleFilterChange('dateFrom', e.target.value)}
                className="w-1/2 py-2 px-2 bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg text-[#2b2620] text-center font-mono"
              />
              <span className="text-[#6b6252]">–</span>
              <input
                type="number"
                placeholder="1998"
                min={1970}
                max={1998}
                value={filters.dateTo}
                onChange={e => handleFilterChange('dateTo', e.target.value)}
                className="w-1/2 py-2 px-2 bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg text-[#2b2620] text-center font-mono"
              />
            </div>
          </div>
        </div>

        {/* Source Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {sources.map(src => (
            <div
              key={src.id}
              onClick={() => setSelectedSource(src)}
              className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-4 shadow-2xs hover:shadow-md hover:border-[#8b3a1f]/60 hover:-translate-y-0.5 transition-all duration-200 cursor-pointer flex flex-col justify-between group"
            >
              <div>
                {/* Header tags */}
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span
                    className={`font-mono text-[9px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded ${getCollectionBadgeColor(
                      src.collection
                    )}`}
                  >
                    {src.collection}
                  </span>

                  <div className="flex items-center gap-1.5 font-mono text-[10px] text-[#6b6252]">
                    <span>{src.year}</span>
                    <span>•</span>
                    <span>{src.chunk_count} chunks</span>
                  </div>
                </div>

                {/* Status Badges */}
                {(src.status === 'metadata_only' || src.status === 'fetch_failed') && (
                  <div className="mb-2">
                    {src.status === 'metadata_only' && (
                      <span className="bg-[#8c8273]/20 text-[#6b6252] px-2 py-0.5 rounded text-[10px] font-mono">
                        Metadata only (In-copyright / No OCR)
                      </span>
                    )}
                    {src.status === 'fetch_failed' && (
                      <span className="bg-[#a13a2f]/15 text-[#a13a2f] px-2 py-0.5 rounded text-[10px] font-mono">
                        Fetch failed
                      </span>
                    )}
                  </div>
                )}

                {/* Title */}
                <h3 className="font-serif-heading font-semibold text-sm text-[#2b2620] group-hover:text-[#8b3a1f] transition-colors leading-snug line-clamp-2 mb-1">
                  {src.title}
                </h3>

                {/* Author */}
                <p className="text-xs text-[#6b6252] truncate mb-2 font-serif">
                  {src.author}
                </p>

                {/* Abstract Preview */}
                {src.abstract && (
                  <p className="text-[11px] text-[#2b2620]/80 italic line-clamp-3 leading-relaxed bg-[#f5f0e6]/40 p-2 rounded border border-[#d8cfb8]/40 mb-3">
                    "{src.abstract}"
                  </p>
                )}

                {/* Subject Tags */}
                <div className="flex flex-wrap gap-1 mb-2">
                  {src.subjects.slice(0, 3).map((sub, i) => (
                    <span
                      key={i}
                      className="bg-[#f5f0e6] text-[#6b6252] border border-[#d8cfb8] px-1.5 py-0.5 rounded text-[9px]"
                    >
                      {sub}
                    </span>
                  ))}
                  {src.subjects.length > 3 && (
                    <span className="text-[9px] text-[#6b6252] font-mono self-center">
                      +{src.subjects.length - 3}
                    </span>
                  )}
                </div>
              </div>

              {/* Actions Footer */}
              <div className="pt-2.5 mt-2 border-t border-[#d8cfb8]/60 flex items-center justify-between text-xs">
                <button
                  onClick={e => {
                    e.stopPropagation();
                    onAskAboutSource(src);
                  }}
                  className="flex items-center gap-1 text-[11px] text-[#8b3a1f] font-semibold hover:underline"
                >
                  <MessageSquare className="w-3 h-3" />
                  <span>Ask in Chat</span>
                </button>

                {src.ia_url && (
                  <a
                    href={src.ia_url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={e => e.stopPropagation()}
                    className="flex items-center gap-1 text-[10px] text-[#6b6252] hover:text-[#8b3a1f] transition-colors"
                  >
                    <span>Archive.org</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Pagination Bar */}
        <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-3.5 flex items-center justify-between text-xs text-[#6b6252] shadow-2xs">
          <span className="font-mono text-[11px]">
            Showing {totalSources === 0 ? 0 : `${startItem}-${endItem}`} of {totalSources} primary volumes
          </span>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-2 py-1 rounded border border-[#d8cfb8] disabled:opacity-30 hover:bg-[#f5f0e6] text-[#2b2620] flex items-center gap-1"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>Previous</span>
            </button>
            <span className="font-mono text-[11px] px-2">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-2 py-1 rounded border border-[#d8cfb8] disabled:opacity-30 hover:bg-[#f5f0e6] text-[#2b2620] flex items-center gap-1"
            >
              <span>Next</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Selected Source Modal / Deep Inspector */}
      {selectedSource && (
        <div className="fixed inset-0 z-50 bg-[#2b2620]/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4 max-h-[85vh] overflow-y-auto">
            <div className="flex items-start justify-between gap-3 border-b border-[#d8cfb8] pb-3">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`font-mono text-[9px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded ${getCollectionBadgeColor(
                      selectedSource.collection
                    )}`}
                  >
                    {selectedSource.collection}
                  </span>
                  <span className="font-mono text-xs text-[#6b6252]">{selectedSource.year}</span>
                  <span className="font-mono text-xs text-[#6b6252]">
                    • {selectedSource.chunk_count} indexed chunks
                  </span>
                </div>
                <h3 className="font-serif-heading font-bold text-lg text-[#2b2620] leading-snug">
                  {selectedSource.title}
                </h3>
              </div>
              <button
                onClick={() => setSelectedSource(null)}
                className="p-1 rounded-md text-[#6b6252] hover:text-[#2b2620] hover:bg-[#f5f0e6]"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="text-xs space-y-3 text-[#2b2620]">
              <div>
                <span className="font-semibold text-[#6b6252] uppercase text-[10px] block">
                  Author(s):
                </span>
                <p className="font-serif text-sm text-[#2b2620]">{selectedSource.author}</p>
              </div>

              {selectedSource.publisher && (
                <div>
                  <span className="font-semibold text-[#6b6252] uppercase text-[10px] block">
                    Publisher / Laboratory:
                  </span>
                  <p className="font-serif">{selectedSource.publisher}</p>
                </div>
              )}

              {selectedSource.abstract && (
                <div>
                  <span className="font-semibold text-[#6b6252] uppercase text-[10px] block">
                    Archival Abstract:
                  </span>
                  <p className="font-serif text-xs leading-relaxed italic bg-[#f5f0e6] p-3 rounded-lg border border-[#d8cfb8]">
                    "{selectedSource.abstract}"
                  </p>
                </div>
              )}

              <div>
                <span className="font-semibold text-[#6b6252] uppercase text-[10px] block">
                  Thematic Classifications:
                </span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {selectedSource.subjects.map((sub, i) => (
                    <span
                      key={i}
                      className="bg-[#f5f0e6] text-[#2b2620] border border-[#d8cfb8] px-2 py-0.5 rounded text-[11px]"
                    >
                      {sub}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="pt-4 border-t border-[#d8cfb8] flex items-center justify-between">
              <button
                onClick={() => {
                  onAskAboutSource(selectedSource);
                  setSelectedSource(null);
                }}
                className="px-4 py-2 bg-[#8b3a1f] text-[#fffdf7] rounded-lg text-xs font-semibold hover:bg-[#6f2e17] transition-colors shadow-2xs flex items-center gap-1.5"
              >
                <MessageSquare className="w-3.5 h-3.5" />
                <span>Ask about this source in Chat</span>
              </button>

              {selectedSource.ia_url && (
                <a
                  href={selectedSource.ia_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-xs text-[#8b3a1f] hover:underline font-medium"
                >
                  <span>Open on Internet Archive</span>
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
