import React from 'react';
import { RetrievedChunk } from '../types';
import { ExternalLink, Bookmark, Globe, FileText } from 'lucide-react';

interface EvidenceCardsProps {
  chunks: RetrievedChunk[];
  onSelectSource?: (sourceId: string) => void;
}

export const EvidenceCards: React.FC<EvidenceCardsProps> = ({
  chunks,
  onSelectSource
}) => {
  if (!chunks || chunks.length === 0) return null;

  // Deduplicate by source — group chunks by source_id, pick the one with the
  // longest snippet (most informative) from each unique source.
  const bySource = new Map<string | number, RetrievedChunk>();
  for (const chunk of chunks) {
    const key = chunk.source_id || chunk.source_title || chunk.id;
    const existing = bySource.get(key);
    if (!existing || (chunk.snippet?.length || 0) > (existing.snippet?.length || 0)) {
      bySource.set(key, chunk);
    }
  }
  const uniqueChunks = Array.from(bySource.values());

  // Format date correctly based on capture_timestamp vs pub_date
  const getProvenanceString = (chunk: RetrievedChunk): string => {
    if (chunk.capture_timestamp || chunk.source_type === 'Website') {
      const ts = chunk.capture_timestamp ? chunk.capture_timestamp.split('T')[0] : (chunk.pub_date || 'Snapshot');
      return `Archived ${ts}`;
    }

    const yearStr = chunk.year || (chunk.pub_date ? chunk.pub_date.substring(0, 4) : 'Historical');
    const authorStr = chunk.author ? `${chunk.author.split(';')[0]} (${yearStr})` : `${yearStr}`;
    const pageStr = chunk.page_number ? ` — Page ${chunk.page_number}` : '';
    return `${authorStr}${pageStr}`;
  };

  const getCollectionBadgeColor = (collection: string) => {
    switch (collection) {
      case 'DTIC':
        return 'bg-[#4a5a6b] text-[#fffdf7]';
      case 'ERIC':
        return 'bg-[#3f6b3f] text-[#fffdf7]';
      case 'Americana':
        return 'bg-[#8b3a1f] text-[#fffdf7]';
      case 'Wayback':
        return 'bg-[#2b2620] text-[#fffdf7]';
      default:
        return 'bg-[#6b6252] text-[#fffdf7]';
    }
  };

  return (
    <div className="mt-3.5 pt-3 border-t border-[#d8cfb8]/80">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-[#2b2620] font-serif-heading">
          <Bookmark className="w-3.5 h-3.5 text-[#8b3a1f]" />
          <span>Cited Primary Evidence ({uniqueChunks.length} source{uniqueChunks.length !== 1 ? 's' : ''} from {chunks.length} chunks)</span>
        </div>
        <span className="text-[10px] text-[#6b6252] font-mono">Scroll right for full trail →</span>
      </div>

      <div className="flex gap-3 overflow-x-auto pb-2 pt-0.5 no-scrollbar snap-x">
        {uniqueChunks.map((chunk, idx) => {
          const provenance = getProvenanceString(chunk);
          const isWeb = chunk.source_type === 'Website' || Boolean(chunk.capture_timestamp);

          return (
            <div
              key={chunk.id || idx}
              onClick={() => onSelectSource?.(chunk.source_id)}
              className="w-72 shrink-0 bg-[#fffdf7] border border-[#d8cfb8] rounded-lg p-3 shadow-2xs hover:shadow-sm hover:-translate-y-0.5 transition-all duration-200 cursor-pointer snap-start flex flex-col justify-between group"
            >
              <div>
                {/* Header with collection and citation tag */}
                <div className="flex items-center justify-between gap-1.5 mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded bg-[#8b3a1f]/10 text-[#8b3a1f] font-mono text-[10px] font-bold flex items-center justify-center">
                      [{idx + 1}]
                    </span>
                    <span className={`text-[9px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded ${getCollectionBadgeColor(chunk.collection)}`}>
                      {chunk.collection}
                    </span>
                  </div>
                  <span className="text-[10px] text-[#6b6252] font-mono flex items-center gap-1">
                    {isWeb ? <Globe className="w-3 h-3 text-[#6b6252]" /> : <FileText className="w-3 h-3 text-[#6b6252]" />}
                    {chunk.source_type}
                  </span>
                </div>

                {/* Source Title */}
                <h4 className="font-serif-heading font-semibold text-xs text-[#2b2620] line-clamp-2 leading-snug group-hover:text-[#8b3a1f] transition-colors">
                  {chunk.source_title}
                </h4>

                {/* Provenance date / author */}
                <div className="text-[11px] text-[#6b6252] font-mono mt-1 mb-2">
                  {provenance}
                </div>

                {/* 2-line snippet */}
                <p className="text-[11px] text-[#2b2620]/80 italic line-clamp-2 leading-relaxed bg-[#f5f0e6]/50 p-1.5 rounded border border-[#d8cfb8]/50">
                  "{chunk.snippet}"
                </p>
              </div>

              {/* Footer link to IA */}
              <div className="mt-2.5 pt-2 border-t border-[#d8cfb8]/40 flex items-center justify-between text-[10px]">
                <span className="text-[#8b3a1f] font-medium group-hover:underline">
                  Inspect in Archive Panel
                </span>
                {chunk.ia_url && (
                  <a
                    href={chunk.ia_url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={e => e.stopPropagation()}
                    className="flex items-center gap-1 text-[#6b6252] hover:text-[#8b3a1f] transition-colors"
                  >
                    <span>Archive.org</span>
                    <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
