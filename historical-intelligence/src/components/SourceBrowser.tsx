import React, { useState, useEffect, useMemo } from 'react';
import {
  Search,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  BookOpen,
  Filter,
  MessageSquare,
  X,
  AlertCircle
} from 'lucide-react';
import { SourceDocument, SourceFilterState } from '../types';
import { HistoricalApiService } from '../services/api';

interface SourceBrowserProps {
  isOpen: boolean;
  onToggleOpen: () => void;
  onAskAboutSource: (source: SourceDocument) => void;
  selectedSourceId?: string | null;
  onSelectSource?: (sourceId: string | null) => void;
}

export const SourceBrowser: React.FC<SourceBrowserProps> = ({
  isOpen,
  onToggleOpen,
  onAskAboutSource,
  selectedSourceId,
  onSelectSource
}) => {
  const [filters, setFilters] = useState<SourceFilterState>({
    searchQuery: '',
    sourceType: 'All',
    collection: 'All',
    dateFrom: '',
    dateTo: '',
    language: 'All'
  });

  const [showFilters, setShowFilters] = useState(false);
  const [sources, setSources] = useState<SourceDocument[]>([]);
  const [totalSources, setTotalSources] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const [expandedSourceId, setExpandedSourceId] = useState<string | null>(null);

  // Sync expanded source when selectedSourceId changes
  useEffect(() => {
    if (selectedSourceId) {
      setExpandedSourceId(selectedSourceId);
      // If closed, open panel so user sees the focused source
      if (!isOpen) {
        onToggleOpen();
      }
    }
  }, [selectedSourceId]);

  // Fetch sources whenever filters or page change
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

  const hasActiveFilters = useMemo(() => {
    return (
      filters.searchQuery !== '' ||
      filters.sourceType !== 'All' ||
      filters.collection !== 'All' ||
      filters.dateFrom !== '' ||
      filters.dateTo !== '' ||
      filters.language !== 'All'
    );
  }, [filters]);

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

  if (!isOpen) {
    return (
      <div className="hidden lg:flex flex-col items-center justify-start py-4 w-11 bg-[#fffdf7] border-r border-[#d8cfb8] shrink-0">
        <button
          id="open-source-browser-btn"
          onClick={onToggleOpen}
          title="Open Indexed Corpus Browser"
          className="p-2 rounded-md hover:bg-[#f5f0e6] text-[#6b6252] hover:text-[#8b3a1f] transition-colors"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
        <div className="writing-vertical text-xs font-serif-heading text-[#6b6252] tracking-wider mt-6 select-none opacity-80">
          INDEXED CORPUS
        </div>
      </div>
    );
  }

  const totalPages = Math.max(1, Math.ceil(totalSources / pageSize));
  const startItem = (page - 1) * pageSize + 1;
  const endItem = Math.min(page * pageSize, totalSources);

  return (
    <aside className="w-full lg:w-[32%] xl:w-[30%] min-w-[280px] max-w-[420px] bg-[#fffdf7] border-r border-[#d8cfb8] flex flex-col h-[calc(100vh-3.5rem)] shrink-0 select-none">
      {/* Header */}
      <div className="p-3.5 border-b border-[#d8cfb8] bg-[#fffdf7] sticky top-0 z-10">
        <div className="flex items-center justify-between gap-2 mb-2.5">
          <div className="flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-[#8b3a1f]" />
            <h2 className="font-serif-heading font-semibold text-sm text-[#2b2620] tracking-tight">
              Indexed Corpus
            </h2>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={`p-1.5 rounded-md text-xs flex items-center gap-1 border transition-colors ${
                hasActiveFilters || showFilters
                  ? 'bg-[#8b3a1f]/10 text-[#8b3a1f] border-[#8b3a1f]/30 font-medium'
                  : 'text-[#6b6252] border-[#d8cfb8] hover:bg-[#f5f0e6]'
              }`}
              title="Toggle Filters"
            >
              <Filter className="w-3.5 h-3.5" />
              <span className="text-[11px] hidden sm:inline">Filters</span>
              {hasActiveFilters && (
                <span className="w-1.5 h-1.5 rounded-full bg-[#8b3a1f]" />
              )}
            </button>
            <button
              onClick={onToggleOpen}
              title="Collapse Panel"
              className="p-1.5 rounded-md hover:bg-[#f5f0e6] text-[#6b6252] hover:text-[#2b2620] transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Search Bar */}
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[#6b6252]" />
          <input
            id="source-search-input"
            type="text"
            placeholder="Search author, title, topic..."
            value={filters.searchQuery}
            onChange={e => handleFilterChange('searchQuery', e.target.value)}
            className="w-full pl-8 pr-7 py-1.5 text-xs bg-[#f5f0e6] border border-[#d8cfb8] rounded-md text-[#2b2620] placeholder-[#6b6252]/70 focus:outline-none focus:border-[#8b3a1f] transition-colors"
          />
          {filters.searchQuery && (
            <button
              onClick={() => handleFilterChange('searchQuery', '')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[#6b6252] hover:text-[#2b2620]"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Expandable Filter Box */}
        {showFilters && (
          <div className="mt-2.5 pt-2.5 border-t border-[#d8cfb8] text-xs space-y-2 bg-[#f5f0e6]/50 p-2 rounded-md border">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-[10px] uppercase font-semibold text-[#6b6252] mb-1">
                  Collection
                </label>
                <select
                  value={filters.collection}
                  onChange={e => handleFilterChange('collection', e.target.value)}
                  className="w-full text-xs bg-[#fffdf7] border border-[#d8cfb8] rounded px-1.5 py-1 text-[#2b2620]"
                >
                  <option value="All">All Collections</option>
                  <option value="DTIC">DTIC (Defense)</option>
                  <option value="ERIC">ERIC (Education)</option>
                  <option value="Americana">Americana</option>
                </select>
              </div>

              <div>
                <label className="block text-[10px] uppercase font-semibold text-[#6b6252] mb-1">
                  Source Type
                </label>
                <select
                  value={filters.sourceType}
                  onChange={e => handleFilterChange('sourceType', e.target.value)}
                  className="w-full text-xs bg-[#fffdf7] border border-[#d8cfb8] rounded px-1.5 py-1 text-[#2b2620]"
                >
                  <option value="All">All Types</option>
                  <option value="Research Paper">Research Paper</option>
                  <option value="Book">Book</option>
                  <option value="Government Document">Government Document</option>
                </select>
              </div>
            </div>

            {/* Date Range inputs */}
            <div>
              <label className="block text-[10px] uppercase font-semibold text-[#6b6252] mb-1">
                Year Range (1970–1998)
              </label>
              <div className="flex items-center gap-1.5">
                <input
                  type="number"
                  placeholder="From (1970)"
                  min={1970}
                  max={1998}
                  value={filters.dateFrom}
                  onChange={e => handleFilterChange('dateFrom', e.target.value)}
                  className="w-1/2 text-xs bg-[#fffdf7] border border-[#d8cfb8] rounded px-2 py-1 text-[#2b2620]"
                />
                <span className="text-[#6b6252] text-xs">–</span>
                <input
                  type="number"
                  placeholder="To (1998)"
                  min={1970}
                  max={1998}
                  value={filters.dateTo}
                  onChange={e => handleFilterChange('dateTo', e.target.value)}
                  className="w-1/2 text-xs bg-[#fffdf7] border border-[#d8cfb8] rounded px-2 py-1 text-[#2b2620]"
                />
              </div>
            </div>

            {/* Language filter */}
            <div className="flex items-center justify-between pt-1">
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] uppercase font-semibold text-[#6b6252]">Language:</span>
                <select
                  value={filters.language}
                  onChange={e => handleFilterChange('language', e.target.value)}
                  className="text-xs bg-[#fffdf7] border border-[#d8cfb8] rounded px-1.5 py-0.5 text-[#2b2620]"
                >
                  <option value="All">All</option>
                  <option value="English">English</option>
                </select>
              </div>

              {hasActiveFilters && (
                <button
                  onClick={clearFilters}
                  className="text-[10px] text-[#8b3a1f] hover:underline font-medium"
                >
                  Reset filters
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Source List */}
      <div className="flex-1 overflow-y-auto divide-y divide-[#d8cfb8]/50 p-2 space-y-1.5">
        {sources.length === 0 ? (
          <div className="p-6 text-center text-xs text-[#6b6252]">
            <AlertCircle className="w-6 h-6 text-[#6b6252] mx-auto mb-2 opacity-50" />
            No historical sources match your active filters.
            <div className="mt-2">
              <button
                onClick={clearFilters}
                className="text-[#8b3a1f] underline text-xs font-medium"
              >
                Clear all filters
              </button>
            </div>
          </div>
        ) : (
          sources.map(src => {
            const isExpanded = expandedSourceId === src.id;
            const isSelected = selectedSourceId === src.id;

            return (
              <div
                key={src.id}
                id={`source-card-${src.id}`}
                className={`p-2.5 rounded-lg border transition-all duration-150 ${
                  isSelected
                    ? 'bg-[#fffdf7] border-[#8b3a1f] ring-1 ring-[#8b3a1f]/30 shadow-xs'
                    : 'bg-[#fffdf7] border-[#d8cfb8]/70 hover:border-[#d8cfb8] hover:bg-[#f5f0e6]/40'
                }`}
              >
                {/* Clickable Header Row */}
                <div
                  onClick={() => {
                    const nextId = isExpanded ? null : src.id;
                    setExpandedSourceId(nextId);
                    onSelectSource?.(nextId);
                  }}
                  className="cursor-pointer"
                >
                  {/* Badges and year */}
                  <div className="flex items-center justify-between gap-1.5 mb-1 text-[10px]">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`font-mono font-semibold px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wider ${getCollectionBadgeColor(
                          src.collection
                        )}`}
                      >
                        {src.collection}
                      </span>
                      <span className="font-mono text-[#6b6252]">{src.year}</span>
                    </div>

                    {/* Status Badges */}
                    <div className="flex items-center gap-1">
                      {src.status === 'metadata_only' && (
                        <span
                          title="No full text indexed due to archival copyright or absence of OCR"
                          className="bg-[#8c8273]/20 text-[#6b6252] px-1.5 py-0.5 rounded text-[9px] font-mono"
                        >
                          Metadata only
                        </span>
                      )}
                      {src.status === 'fetch_failed' && (
                        <span
                          title="Ingestion pipeline encountered retrieval fault"
                          className="bg-[#a13a2f]/15 text-[#a13a2f] px-1.5 py-0.5 rounded text-[9px] font-mono"
                        >
                          Fetch failed
                        </span>
                      )}
                      <span className="text-[10px] text-[#6b6252] font-mono">
                        {src.chunk_count} chunks
                      </span>
                    </div>
                  </div>

                  {/* Title (2 lines clamp) */}
                  <h3 className="font-serif-heading font-semibold text-xs text-[#2b2620] line-clamp-2 leading-snug hover:text-[#8b3a1f] transition-colors">
                    {src.title}
                  </h3>

                  {/* Author */}
                  <p className="text-[11px] text-[#6b6252] truncate mt-0.5">
                    {src.author}
                  </p>
                </div>

                {/* Expanded Details */}
                {isExpanded && (
                  <div className="mt-2.5 pt-2 border-t border-[#d8cfb8]/60 text-xs space-y-2 bg-[#f5f0e6]/40 p-2 rounded">
                    {src.publisher && (
                      <div>
                        <span className="text-[10px] font-semibold text-[#6b6252] uppercase">
                          Publisher / Lab:
                        </span>
                        <p className="text-[11px] text-[#2b2620]">{src.publisher}</p>
                      </div>
                    )}

                    {src.abstract && (
                      <div>
                        <span className="text-[10px] font-semibold text-[#6b6252] uppercase">
                          Archival Abstract:
                        </span>
                        <p className="text-[11px] text-[#2b2620]/90 leading-relaxed italic">
                          "{src.abstract}"
                        </p>
                      </div>
                    )}

                    {/* Subjects tags */}
                    <div>
                      <span className="text-[10px] font-semibold text-[#6b6252] uppercase">
                        Classifications:
                      </span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {src.subjects.map((sub, i) => (
                          <span
                            key={i}
                            className="bg-[#fffdf7] text-[#6b6252] border border-[#d8cfb8] px-1.5 py-0.5 rounded text-[10px]"
                          >
                            {sub}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center justify-between gap-2 pt-1.5 mt-1 border-t border-[#d8cfb8]/40">
                      <button
                        onClick={() => onAskAboutSource(src)}
                        className="flex items-center gap-1 px-2 py-1 bg-[#8b3a1f] text-[#fffdf7] rounded text-[11px] font-medium hover:bg-[#6f2e17] transition-colors shadow-2xs"
                      >
                        <MessageSquare className="w-3 h-3" />
                        <span>Ask about this source</span>
                      </button>

                      {src.ia_url && (
                        <a
                          href={src.ia_url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-center gap-1 text-[11px] text-[#8b3a1f] hover:underline"
                        >
                          <span>Internet Archive</span>
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Pagination Footer */}
      <div className="p-2.5 border-t border-[#d8cfb8] bg-[#fffdf7] flex items-center justify-between text-xs text-[#6b6252]">
        <span className="font-mono text-[11px]">
          Showing {totalSources === 0 ? 0 : `${startItem}-${endItem}`} of {totalSources} sources
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="p-1 rounded border border-[#d8cfb8] disabled:opacity-30 hover:bg-[#f5f0e6] text-[#2b2620]"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
          <span className="font-mono text-[11px] px-1">
            {page}/{totalPages}
          </span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="p-1 rounded border border-[#d8cfb8] disabled:opacity-30 hover:bg-[#f5f0e6] text-[#2b2620]"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
};
