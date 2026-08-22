import React from 'react';
import { AnswerSegment } from '../types';
import { ShieldCheck } from 'lucide-react';

interface CitationConfidenceBarProps {
  segments?: AnswerSegment[];
  distribution?: {
    verified: number;
    inferred: number;
    unknown: number;
  };
}

export const CitationConfidenceBar: React.FC<CitationConfidenceBarProps> = ({
  segments,
  distribution
}) => {
  // Compute distribution if not precalculated
  let verifiedPct = 0;
  let inferredPct = 0;
  let unknownPct = 0;

  if (distribution) {
    verifiedPct = distribution.verified;
    inferredPct = distribution.inferred;
    unknownPct = distribution.unknown;
  } else if (segments && segments.length > 0) {
    const citedSegments = segments.filter(s => s.citation_index !== undefined || s.chunk_ids.length > 0);
    const total = citedSegments.length || segments.length;

    let verifiedCount = 0;
    let inferredCount = 0;
    let unknownCount = 0;

    for (const seg of segments) {
      if (seg.citation_type === 'directly_verified') verifiedCount++;
      else if (seg.citation_type === 'inferred') inferredCount++;
      else unknownCount++;
    }

    verifiedPct = Math.round((verifiedCount / total) * 100);
    inferredPct = Math.round((inferredCount / total) * 100);
    unknownPct = Math.max(0, 100 - verifiedPct - inferredPct);
  } else {
    verifiedPct = 100;
  }

  return (
    <div className="my-3 pt-2.5 pb-1 border-t border-[#d8cfb8]/60 text-xs">
      <div className="flex items-center justify-between mb-1.5 text-[11px] text-[#6b6252]">
        <div className="flex items-center gap-1 font-medium text-[#2b2620]">
          <ShieldCheck className="w-3.5 h-3.5 text-[#3f6b3f]" />
          <span>Citation Verification Distribution</span>
        </div>
        <div className="flex items-center gap-3 font-mono text-[10px]">
          <span className="flex items-center gap-1 text-[#3f6b3f]">
            <span className="w-2 h-2 rounded-full bg-[#3f6b3f]" />
            Directly Verified ({verifiedPct}%)
          </span>
          <span className="flex items-center gap-1 text-[#a67c1e]">
            <span className="w-2 h-2 rounded-full bg-[#a67c1e]" />
            Inferred ({inferredPct}%)
          </span>
          {unknownPct > 0 && (
            <span className="flex items-center gap-1 text-[#6b6252]">
              <span className="w-2 h-2 rounded-full bg-[#8c8273]" />
              Unanchored ({unknownPct}%)
            </span>
          )}
        </div>
      </div>

      {/* Progress Track */}
      <div className="h-1.5 w-full bg-[#e7dfce] rounded-full overflow-hidden flex">
        {verifiedPct > 0 && (
          <div
            style={{ width: `${verifiedPct}%` }}
            className="h-full bg-[#3f6b3f] transition-all duration-500 ease-out"
            title={`Directly Verified: ${verifiedPct}%`}
          />
        )}
        {inferredPct > 0 && (
          <div
            style={{ width: `${inferredPct}%` }}
            className="h-full bg-[#a67c1e] transition-all duration-500 ease-out"
            title={`Inferred: ${inferredPct}%`}
          />
        )}
        {unknownPct > 0 && (
          <div
            style={{ width: `${unknownPct}%` }}
            className="h-full bg-[#8c8273] transition-all duration-500 ease-out"
            title={`Unanchored: ${unknownPct}%`}
          />
        )}
      </div>
    </div>
  );
};
