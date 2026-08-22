import React, { useState, useMemo } from 'react';
import { RetrievedChunk, ChatMessage } from '../types';
import { INITIAL_SOURCES } from '../data/corpusData';
import { Calendar, Filter, RotateCcw, ArrowRight, BookOpen, Layers } from 'lucide-react';

interface TimelineViewProps {
  lastMessageWithChunks?: ChatMessage;
  onFilterByYear: (year: number) => void;
  onApplyDateRange: (from: number, to: number) => void;
  onSelectSource: (sourceId: string) => void;
}

export const TimelineView: React.FC<TimelineViewProps> = ({
  lastMessageWithChunks,
  onFilterByYear,
  onApplyDateRange,
  onSelectSource
}) => {
  const [rangeFrom, setRangeFrom] = useState<number>(1970);
  const [rangeTo, setRangeTo] = useState<number>(1998);
  const [hoveredYear, setHoveredYear] = useState<{
    year: number;
    count: number;
    sources: Array<{ title: string; collection: string; id: string }>;
  } | null>(null);

  // Compute year distribution from active answer's retrieved chunks or fallback to full 44-source corpus
  const { yearDistribution, totalCount, isUsingCorpusFallback, activeQuery } = useMemo(() => {
    const counts: Record<number, Array<{ title: string; collection: string; id: string }>> = {};

    // Initialize all continuous years from 1970 to 1998 (Zero sources MUST show as gaps, never omitted)
    for (let y = 1970; y <= 1998; y++) {
      counts[y] = [];
    }

    if (lastMessageWithChunks?.answerResponse?.retrieved_chunks && lastMessageWithChunks.answerResponse.retrieved_chunks.length > 0) {
      const chunks = lastMessageWithChunks.answerResponse.retrieved_chunks;
      for (const chk of chunks) {
        let yr = chk.year;
        if (!yr && chk.pub_date) {
          yr = parseInt(chk.pub_date.substring(0, 4), 10);
        } else if (!yr && chk.capture_timestamp) {
          yr = parseInt(chk.capture_timestamp.substring(0, 4), 10);
        }

        if (yr && yr >= 1970 && yr <= 1998) {
          counts[yr].push({
            title: chk.source_title,
            collection: chk.collection,
            id: chk.source_id
          });
        }
      }

      const total = chunks.length;
      return {
        yearDistribution: counts,
        totalCount: total,
        isUsingCorpusFallback: false,
        activeQuery: lastMessageWithChunks.text
      };
    }

    // Fallback: Full 44-source corpus
    for (const src of INITIAL_SOURCES) {
      if (src.year >= 1970 && src.year <= 1998) {
        counts[src.year].push({
          title: src.title,
          collection: src.collection,
          id: src.id
        });
      }
    }

    return {
      yearDistribution: counts,
      totalCount: INITIAL_SOURCES.length,
      isUsingCorpusFallback: true,
      activeQuery: null
    };
  }, [lastMessageWithChunks]);

  const maxCount = useMemo(() => {
    let max = 1;
    for (let y = 1970; y <= 1998; y++) {
      if (yearDistribution[y].length > max) {
        max = yearDistribution[y].length;
      }
    }
    return max;
  }, [yearDistribution]);

  const handleApplyBrush = () => {
    if (rangeFrom <= rangeTo) {
      onApplyDateRange(rangeFrom, rangeTo);
    }
  };

  const handleResetBrush = () => {
    setRangeFrom(1970);
    setRangeTo(1998);
    onApplyDateRange(1970, 1998);
  };

  return (
    <div className="flex-1 flex flex-col h-[calc(100vh-3.5rem)] overflow-y-auto bg-[#f5f0e6] p-4 sm:p-6">
      <div className="max-w-5xl mx-auto w-full space-y-6">
        {/* Header & Mode Notice */}
        <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-5 shadow-2xs">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[#d8cfb8] pb-4">
            <div>
              <div className="flex items-center gap-2">
                <Calendar className="w-5 h-5 text-[#8b3a1f]" />
                <h2 className="font-serif-heading text-xl font-bold text-[#2b2620]">
                  Chronological Provenance Timeline
                </h2>
              </div>
              <p className="text-xs text-[#6b6252] mt-1">
                {isUsingCorpusFallback
                  ? 'Showing publication timeline for the full 44-source research corpus (1970–1998).'
                  : `Visualizing temporal evidence distribution for active query: "${activeQuery?.substring(0, 70)}..."`}
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs font-mono bg-[#f5f0e6] px-3 py-1.5 rounded-md border border-[#d8cfb8] text-[#2b2620]">
                {totalCount} {isUsingCorpusFallback ? 'Corpus Volumes' : 'Cited Evidence Chunks'}
              </span>
            </div>
          </div>

          {/* Interactive Date Range Brush / Selector */}
          <div className="mt-4 pt-1 flex flex-col sm:flex-row items-center justify-between gap-4 bg-[#f5f0e6]/60 p-3 rounded-lg border border-[#d8cfb8]/80 text-xs">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-[#8b3a1f]" />
              <span className="font-semibold text-[#2b2620]">Date-Range Brush Selector:</span>
              <span className="font-mono text-[#8b3a1f] font-bold">
                {rangeFrom} — {rangeTo}
              </span>
            </div>

            <div className="flex items-center gap-3 w-full sm:w-auto">
              <div className="flex items-center gap-2 flex-1 sm:flex-initial">
                <input
                  type="range"
                  min={1970}
                  max={1998}
                  value={rangeFrom}
                  onChange={e => setRangeFrom(Math.min(parseInt(e.target.value, 10), rangeTo))}
                  className="accent-[#8b3a1f] w-24 sm:w-28 cursor-pointer"
                />
                <input
                  type="range"
                  min={1970}
                  max={1998}
                  value={rangeTo}
                  onChange={e => setRangeTo(Math.max(parseInt(e.target.value, 10), rangeFrom))}
                  className="accent-[#8b3a1f] w-24 sm:w-28 cursor-pointer"
                />
              </div>

              <div className="flex items-center gap-2">
                <button
                  id="apply-timeline-brush-btn"
                  onClick={handleApplyBrush}
                  className="px-3 py-1 bg-[#8b3a1f] text-[#fffdf7] rounded text-xs font-medium hover:bg-[#6f2e17] transition-colors shadow-2xs flex items-center gap-1"
                >
                  <span>Apply Filter</span>
                  <ArrowRight className="w-3 h-3" />
                </button>
                <button
                  onClick={handleResetBrush}
                  title="Reset date range"
                  className="p-1 text-[#6b6252] hover:text-[#2b2620] rounded border border-[#d8cfb8] bg-[#fffdf7]"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* The Bar Chart Canvas */}
        <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-5 shadow-2xs">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-serif-heading font-semibold text-sm text-[#2b2620]">
              Annual Publication Density (1970 – 1998)
            </h3>
            <span className="text-[11px] text-[#6b6252] font-mono">
              Click any bar to filter Source Explorer to that year
            </span>
          </div>

          {/* Bar chart container */}
          <div className="relative pt-6 pb-2">
            <div className="h-64 flex items-end justify-between gap-1 border-b border-[#d8cfb8] px-1">
              {Array.from({ length: 29 }, (_, i) => 1970 + i).map(year => {
                const sourcesInYear = yearDistribution[year] || [];
                const count = sourcesInYear.length;
                const heightPct = count > 0 ? Math.max(12, Math.round((count / maxCount) * 100)) : 0;
                const isInSelectedRange = year >= rangeFrom && year <= rangeTo;

                return (
                  <div
                    key={year}
                    className="flex-1 flex flex-col items-center h-full justify-end group cursor-pointer relative"
                    onClick={() => onFilterByYear(year)}
                    onMouseEnter={() =>
                      setHoveredYear({
                        year,
                        count,
                        sources: sourcesInYear
                      })
                    }
                    onMouseLeave={() => setHoveredYear(null)}
                  >
                    {/* Bar */}
                    {count > 0 ? (
                      <div
                        style={{ height: `${heightPct}%` }}
                        className={`w-full rounded-t-sm transition-all duration-200 ${
                          isInSelectedRange
                            ? 'bg-[#8b3a1f] group-hover:bg-[#6f2e17] group-hover:brightness-110 shadow-2xs'
                            : 'bg-[#d8cfb8] group-hover:bg-[#b8a98f]'
                        }`}
                      >
                        <span className="sr-only">{year}: {count} sources</span>
                      </div>
                    ) : (
                      /* Explicit gap with hairline marker to satisfy requirement: zero source years never omitted */
                      <div className="w-full h-1 bg-[#e7ded0] group-hover:bg-[#d8cfb8] transition-colors rounded-xs" />
                    )}

                    {/* Rotated year label below */}
                    <span className={`text-[10px] font-mono mt-2 transition-colors ${
                      isInSelectedRange ? 'text-[#2b2620] font-medium' : 'text-[#6b6252]/60'
                    } ${year % 5 === 0 ? 'font-bold text-[#8b3a1f]' : ''}`}>
                      {year % 2 === 0 ? `'${year.toString().slice(-2)}` : ''}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Hover Tooltip Card */}
            {hoveredYear && (
              <div className="mt-4 p-3 bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg text-xs animate-in fade-in duration-100">
                <div className="flex items-center justify-between font-serif-heading font-semibold text-sm text-[#8b3a1f] border-b border-[#d8cfb8] pb-1 mb-2">
                  <span>Year {hoveredYear.year}</span>
                  <span className="font-mono text-xs text-[#2b2620]">
                    {hoveredYear.count} {hoveredYear.count === 1 ? 'Volume' : 'Volumes'}
                  </span>
                </div>
                {hoveredYear.count === 0 ? (
                  <p className="text-[11px] text-[#6b6252] italic">
                    Zero indexed records in active dataset for {hoveredYear.year} (Historical gap).
                  </p>
                ) : (
                  <div className="space-y-1.5 max-h-32 overflow-y-auto">
                    {hoveredYear.sources.map((s, idx) => (
                      <div
                        key={idx}
                        onClick={() => onSelectSource(s.id)}
                        className="flex items-center justify-between text-[11px] p-1 bg-[#fffdf7] rounded border border-[#d8cfb8]/60 hover:border-[#8b3a1f] cursor-pointer"
                      >
                        <span className="font-serif truncate max-w-md text-[#2b2620]">{s.title}</span>
                        <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 bg-[#8b3a1f]/10 text-[#8b3a1f] rounded shrink-0">
                          {s.collection}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Historical Contextual Eras Summary */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-lg p-4 shadow-2xs">
            <h4 className="font-serif-heading font-semibold text-sm text-[#8b3a1f] mb-1">
              1970–1979: Symbolic Foundations
            </h4>
            <p className="text-[#6b6252] leading-relaxed">
              Dominated by semantic network theories (SCHOLAR, Quillian), SHRDLU procedural microworlds, and the genesis of rule-based clinical systems (MYCIN).
            </p>
          </div>
          <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-lg p-4 shadow-2xs">
            <h4 className="font-serif-heading font-semibold text-sm text-[#8b3a1f] mb-1">
              1980–1989: Knowledge Boom
            </h4>
            <p className="text-[#6b6252] leading-relaxed">
              Industrial expert systems, Japan’s 5th Generation Project, dedicated LISP Machine workstations, and the revival of connectionist neural networks (PDP).
            </p>
          </div>
          <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-lg p-4 shadow-2xs">
            <h4 className="font-serif-heading font-semibold text-sm text-[#8b3a1f] mb-1">
              1990–1998: Common Sense & Web
            </h4>
            <p className="text-[#6b6252] leading-relaxed">
              Large-scale ontological modeling (Cyc), probabilistic Bayesian networks, and early internet archive snapshots emerging via Wayback CDX.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
