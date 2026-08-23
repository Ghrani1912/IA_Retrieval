import React, { useState, useEffect } from 'react';
import {
  BookOpen,
  SlidersHorizontal,
  Info,
  Layers,
  ChevronDown
} from 'lucide-react';
import { AppSettings } from '../types';

interface CorpusStats {
  total_sources: number;
  sources_with_chunks: number;
  total_chunks: number;
  collections: Array<{ name: string; sources: number; chunks: number }>;
}

const FALLBACK_STATS: CorpusStats = {
  total_sources: 0,
  sources_with_chunks: 0,
  total_chunks: 0,
  collections: [],
};

export type ViewTab = 'chat' | 'timeline' | 'timemachine' | 'explorer';

interface TopBarProps {
  activeTab: ViewTab;
  onTabChange: (tab: ViewTab) => void;
  isBackendConnected: boolean;
  onOpenSettings: () => void;
  settings: AppSettings;
}

const COLLECTION_COLORS: Record<string, string> = {
  dticarchive: '#4a5a6b',
  ericarchive: '#3f6b3f',
  americana: '#8b3a1f',
};
const DEFAULT_COLOR = '#6b6252';

const COLLECTION_LABELS: Record<string, string> = {
  dticarchive: 'DTIC (Defense)',
  ericarchive: 'ERIC (Education)',
  americana: 'Americana (Libraries)',
};

export const TopBar: React.FC<TopBarProps> = ({
  activeTab,
  onTabChange,
  isBackendConnected,
  onOpenSettings
}) => {
  const [showCorpusTooltip, setShowCorpusTooltip] = useState(false);
  const [corpusStats, setCorpusStats] = useState<CorpusStats>(FALLBACK_STATS);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const resp = await fetch('http://localhost:8000/corpus/stats');
        if (resp.ok) {
          const data = await resp.json();
          setCorpusStats(data);
        }
      } catch {
        // Backend not available — use fallback (zeros)
      }
    };
    fetchStats();
    // Poll every 30 seconds for live corpus stats (catches on-demand ingestions)
    const interval = setInterval(fetchStats, 30000);
    return () => clearInterval(interval);
  }, []);

  const tabs: { id: ViewTab; label: string }[] = [
    { id: 'chat', label: 'Chat' },
    { id: 'timeline', label: 'Timeline' },
    { id: 'timemachine', label: 'Website Time Machine' },
    { id: 'explorer', label: 'Source Explorer' }
  ];

  return (
    <header className="sticky top-0 z-30 bg-[#fffdf7] border-b border-[#d8cfb8] shadow-xs select-none">
      <div className="max-w-7xl mx-auto px-3 sm:px-6 h-14 flex items-center justify-between gap-2">
        {/* Left: App Logo & Name + Tabs */}
        <div className="flex items-center gap-4 sm:gap-7 overflow-x-auto no-scrollbar">
          <div
            id="brand-logo-btn"
            onClick={() => onTabChange('chat')}
            className="flex items-center gap-2.5 cursor-pointer py-1 group shrink-0"
          >
            <div className="w-8 h-8 rounded-md bg-[#8b3a1f] flex items-center justify-center text-[#fffdf7] shadow-xs group-hover:bg-[#6f2e17] transition-colors">
              <BookOpen className="w-4 h-4" />
            </div>
            <div>
              <div className="font-display-title text-base sm:text-lg font-bold text-[#2b2620] tracking-wide leading-none">
                Historical Intelligence
              </div>
              <div className="text-[10px] text-[#6b6252] font-mono tracking-tight hidden sm:block">
                1970s–1990s AI Research Corpus
              </div>
            </div>
          </div>

          {/* View Tabs */}
          <nav className="hidden md:flex items-center space-x-1 border-l border-[#d8cfb8] pl-5 h-7">
            {tabs.map(tab => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  id={`nav-tab-${tab.id}`}
                  onClick={() => onTabChange(tab.id)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all whitespace-nowrap ${
                    isActive
                      ? 'bg-[#f5f0e6] text-[#8b3a1f] font-semibold border border-[#d8cfb8] shadow-2xs'
                      : 'text-[#6b6252] hover:text-[#2b2620] hover:bg-[#f5f0e6]/60'
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Right: Corpus Breakdown Tooltip & Settings */}
        <div className="flex items-center gap-2 sm:gap-4 shrink-0">
          {/* Corpus Metrics Badge with Dropdown/Tooltip */}
          <div className="relative">
            <button
              id="corpus-tooltip-toggle"
              onClick={() => setShowCorpusTooltip(!showCorpusTooltip)}
              onMouseEnter={() => setShowCorpusTooltip(true)}
              onMouseLeave={() => setShowCorpusTooltip(false)}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs bg-[#f5f0e6] border border-[#d8cfb8] rounded-md text-[#2b2620] hover:border-[#8b3a1f]/50 transition-colors"
            >
              <Layers className="w-3.5 h-3.5 text-[#8b3a1f]" />
              <span className="font-mono text-[11px] sm:text-xs">
                Corpus: <span className="font-semibold">{corpusStats.sources_with_chunks} sources</span>, {corpusStats.total_chunks.toLocaleString()} chunks
              </span>
              <ChevronDown className="w-3 h-3 text-[#6b6252]" />
            </button>

            {/* Tooltip Content */}
            {showCorpusTooltip && (
              <div
                className="absolute right-0 mt-1 w-72 bg-[#fffdf7] border border-[#d8cfb8] rounded-lg shadow-lg p-3 z-50 text-xs text-[#2b2620] animate-in fade-in zoom-in-95 duration-150"
                onMouseEnter={() => setShowCorpusTooltip(true)}
                onMouseLeave={() => setShowCorpusTooltip(false)}
              >
                <div className="font-serif-heading text-sm font-semibold text-[#8b3a1f] border-b border-[#d8cfb8] pb-1.5 mb-2 flex items-center justify-between">
                  <span>Indexed Archival Collections</span>
                  <Info className="w-3.5 h-3.5 text-[#6b6252]" />
                </div>
                <div className="space-y-2">
                  {corpusStats.collections.map((coll) => (
                    <div key={coll.name} className="flex justify-between items-center text-[11px]">
                      <div className="flex items-center gap-1.5">
                        <span
                          className="w-2.5 h-2.5 rounded-full"
                          style={{ backgroundColor: COLLECTION_COLORS[coll.name] || DEFAULT_COLOR }}
                        />
                        <span className="font-medium">{COLLECTION_LABELS[coll.name] || coll.name}</span>
                      </div>
                      <span className="font-mono text-[#6b6252]">
                        {coll.sources} source{coll.sources !== 1 ? 's' : ''} ({coll.chunks.toLocaleString()} chunks)
                      </span>
                    </div>
                  ))}
                  {corpusStats.collections.length === 0 && (
                    <p className="text-[11px] text-[#6b6252] italic">No indexed collections yet.</p>
                  )}
                </div>
                <div className="mt-2.5 pt-2 border-t border-[#d8cfb8] text-[10px] text-[#6b6252]">
                  Chronological coverage: 1970 – 1998 with CDX Wayback snapshots.
                </div>
              </div>
            )}
          </div>

          {/* Backend Connection Indicator & Settings Gear */}
          <div className="flex items-center gap-2">
            <div
              title={isBackendConnected ? 'Connected to FastAPI Backend' : 'Running with built-in archival engine (FastAPI offline)'}
              className="flex items-center gap-1.5 text-[11px] font-mono text-[#6b6252] hidden sm:flex"
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  isBackendConnected ? 'bg-[#3f6b3f] ring-2 ring-[#3f6b3f]/20' : 'bg-[#a13a2f]'
                }`}
              />
              <span className="text-[10px]">
                {isBackendConnected ? 'API Live' : 'Archival Mode'}
              </span>
            </div>

            <button
              id="topbar-settings-btn"
              onClick={onOpenSettings}
              title="Assistant Settings"
              className="p-1.5 rounded-md hover:bg-[#f5f0e6] border border-transparent hover:border-[#d8cfb8] text-[#6b6252] hover:text-[#2b2620] transition-colors"
            >
              <SlidersHorizontal className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Mobile view sub-tabs */}
      <div className="md:hidden flex items-center justify-around border-t border-[#d8cfb8] px-2 py-1.5 bg-[#f5f0e6]">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`px-2 py-1 text-xs rounded transition-colors ${
              activeTab === tab.id
                ? 'bg-[#fffdf7] text-[#8b3a1f] font-semibold shadow-2xs border border-[#d8cfb8]'
                : 'text-[#6b6252]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
    </header>
  );
};
