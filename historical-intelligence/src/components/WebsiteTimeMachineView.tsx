import React, { useState, useEffect } from 'react';
import {
  Globe,
  Search,
  History,
  AlertCircle,
  Loader2,
  Calendar,
  Layers,
  ArrowRight,
  ExternalLink,
  RefreshCw,
  MessageSquare,
  TrendingUp,
  TrendingDown,
  Minus,
  ArrowLeftRight
} from 'lucide-react';
import { SnapshotData, IngestJob } from '../types';
import { HistoricalApiService } from '../services/api';

interface EvolutionData {
  domain: string;
  summary: string;
  eras: Array<{
    period: string;
    focus: string;
    key_changes: string[];
  }>;
  key_topics: string[];
  trend: 'growing' | 'shrinking' | 'stable' | 'shifted';
  snapshot_years: number[];
  chunks_per_year: Record<string, number>;
  status?: string;
  snapshot_count?: number;
  historical_context?: string;
  archival_notes?: string;
}

interface WebsiteTimeMachineViewProps {
  onAskAboutDomain: (domain: string, question?: string) => void;
  onShowToast: (msg: string) => void;
}

export const WebsiteTimeMachineView: React.FC<WebsiteTimeMachineViewProps> = ({
  onAskAboutDomain,
  onShowToast
}) => {
  const [domainInput, setDomainInput] = useState('');
  const [activeDomain, setActiveDomain] = useState<string | null>('ai.mit.edu');
  const [snapshotData, setSnapshotData] = useState<SnapshotData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [ingestedDomains, setIngestedDomains] = useState<{domain: string; snapshot_count: number}[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [is404, setIs404] = useState(false);

  // Ingestion job state
  const [ingestJob, setIngestJob] = useState<IngestJob | null>(null);
  const [isRequestingIngest, setIsRequestingIngest] = useState(false);

  // Chat follow-up input
  const [chatQuestion, setChatQuestion] = useState('');

  // Evolution analysis state
  const [evolutionData, setEvolutionData] = useState<EvolutionData | null>(null);
  const [isLoadingEvolution, setIsLoadingEvolution] = useState(false);
  const [showEvolution, setShowEvolution] = useState(false);

  const sampleDomains = [
    { label: 'MIT AI Lab', domain: 'ai.mit.edu' },
    { label: 'Stanford CS', domain: 'cs.stanford.edu' },
    { label: 'CMU SCS', domain: 'cs.cmu.edu' },
    { label: 'Symbolics Lisp', domain: 'symbolics.com' },
    { label: 'W3C Semantic Web', domain: 'w3.org' }
  ];

  // Fetch domain snapshots
  const fetchDomain = async (domainToFetch: string) => {
    const cleanDomain = domainToFetch.toLowerCase().trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '');
    if (!cleanDomain) return;

    setIsLoading(true);
    setIs404(false);
    setIngestJob(null);
    setActiveDomain(cleanDomain);

    try {
      const data = await HistoricalApiService.getSnapshots(cleanDomain);
      if (data) {
        setSnapshotData(data);
        setIs404(false);
      } else {
        setSnapshotData(null);
        setIs404(true);
      }
    } catch {
      setSnapshotData(null);
      setIs404(true);
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch ingested domains on mount
  useEffect(() => {
    const fetchIngested = async () => {
      try {
        const res = await fetch(`${HistoricalApiService.getBackendUrl()}/snapshots/ingested-domains`);
        if (res.ok) setIngestedDomains(await res.json());
      } catch { /* ignore */ }
    };
    fetchIngested();
    if (activeDomain) fetchDomain(activeDomain);
  }, []);  const handleDomainSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!domainInput.trim()) return;
    setShowSuggestions(false);
    fetchDomain(domainInput);
  };

  // Filter ingested domains for autocomplete
  const filteredSuggestions = domainInput.trim().length > 0
    ? ingestedDomains.filter(d =>
        d.domain.toLowerCase().includes(domainInput.toLowerCase().trim())
      )
    : [];

  // Request Indexing via POST /ingest + Poll GET /ingest/{job_id}/status
  const handleRequestIngest = async () => {
    if (!activeDomain) return;
    setIsRequestingIngest(true);

    try {
      const job = await HistoricalApiService.triggerIngest(activeDomain);
      setIngestJob(job);
      onShowToast(`Crawling task initiated for ${activeDomain}.`);

      // Poll job status
      const pollInterval = setInterval(async () => {
        const updated = await HistoricalApiService.getIngestStatus(job.job_id);
        setIngestJob(updated);

        if (updated.status === 'completed') {
          clearInterval(pollInterval);
          setIsRequestingIngest(false);
          onShowToast(`Domain ${activeDomain} successfully indexed!`);
          // Re-fetch snapshots
          fetchDomain(activeDomain);
        } else if (updated.status === 'failed') {
          clearInterval(pollInterval);
          setIsRequestingIngest(false);
          onShowToast(`Indexing failed for ${activeDomain}.`);
        }
      }, 1500);
    } catch {
      setIsRequestingIngest(false);
    }
  };

  const handleAskSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeDomain) return;
    const q = chatQuestion.trim() || `What is the historical evolution of ${activeDomain} recorded in Wayback snapshots?`;
    onAskAboutDomain(activeDomain, q);
  };

  // Fetch evolution analysis
  const fetchEvolution = async () => {
    if (!activeDomain) return;
    setIsLoadingEvolution(true);
    setShowEvolution(true);
    try {
      const res = await fetch(`${HistoricalApiService.getBackendUrl()}/corpus/evolution/${encodeURIComponent(activeDomain)}`);
      if (res.ok) {
        const data = await res.json();
        setEvolutionData(data);
        
        // If no content chunks yet but LLM can analyze CDX metadata, fetch LLM analysis
        if (data.status === 'ingesting' && data.can_llm_analyze) {
          try {
            const llmRes = await fetch(`${HistoricalApiService.getBackendUrl()}/corpus/evolution/${encodeURIComponent(activeDomain)}/cdx-analysis`);
            if (llmRes.ok) {
              const llmData = await llmRes.json();
              // Merge LLM analysis with CDX data
              setEvolutionData(prev => prev ? {
                ...prev,
                summary: llmData.summary || prev.summary,
                eras: llmData.eras && llmData.eras.length > 0 ? llmData.eras : prev.eras,
                key_topics: llmData.key_topics && llmData.key_topics.length > 0 ? llmData.key_topics : prev.key_topics,
                historical_context: llmData.historical_context,
                archival_notes: llmData.archival_notes,
                status: 'llm_analyzed',
              } : prev);
            }
          } catch {
            // LLM analysis failed, keep CDX data
          }
        }
      } else {
        setEvolutionData(null);
      }
    } catch {
      setEvolutionData(null);
    } finally {
      setIsLoadingEvolution(false);
    }
  };

  // Trend icon helper
  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case 'growing': return <TrendingUp className="w-4 h-4 text-green-600" />;
      case 'shrinking': return <TrendingDown className="w-4 h-4 text-red-600" />;
      case 'shifted': return <ArrowLeftRight className="w-4 h-4 text-amber-600" />;
      default: return <Minus className="w-4 h-4 text-[#6b6252]" />;
    }
  };

  return (
    <div className="flex-1 flex flex-col h-[calc(100vh-3.5rem)] overflow-y-auto bg-[#f5f0e6] p-4 sm:p-6 select-none">
      <div className="max-w-4xl mx-auto w-full space-y-6">
        {/* Search / Domain Input Card */}
        <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-5 shadow-2xs">
          <div className="flex items-center gap-2 mb-2">
            <Globe className="w-5 h-5 text-[#8b3a1f]" />
            <h2 className="font-serif-heading text-xl font-bold text-[#2b2620]">
              Wayback & CDX Time Machine
            </h2>
          </div>
          <p className="text-xs text-[#6b6252] mb-4 font-serif">
            Inspect historical Internet Archive Wayback Machine CDX snapshots, capture coverage frequencies, and crawl gap intervals.
          </p>

          <form onSubmit={handleDomainSubmit} className="flex gap-2">
            <div className="relative flex-1">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#6b6252]" />
              <input
                id="timemachine-domain-input"
                type="text"
                placeholder="Enter a domain (e.g. ai.mit.edu, cs.stanford.edu, symbolics.com)..."
                value={domainInput}
                onChange={e => { setDomainInput(e.target.value); setShowSuggestions(true); }}
                onFocus={() => domainInput.trim().length > 0 && setShowSuggestions(true)}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                className="w-full pl-9 pr-4 py-2 text-sm bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg text-[#2b2620] placeholder-[#6b6252]/70 focus:outline-none focus:border-[#8b3a1f] font-mono"
              />
              {showSuggestions && filteredSuggestions.length > 0 && (
                <ul className="absolute z-50 top-full left-0 right-0 mt-1 bg-[#fffdf7] border border-[#d8cfb8] rounded-lg shadow-lg max-h-48 overflow-y-auto">
                  {filteredSuggestions.map(d => (
                    <li
                      key={d.domain}
                      onMouseDown={() => {
                        setDomainInput(d.domain);
                        setShowSuggestions(false);
                        fetchDomain(d.domain);
                      }}
                      className="px-3 py-2 text-xs font-mono text-[#2b2620] hover:bg-[#8b3a1f]/10 cursor-pointer flex justify-between items-center"
                    >
                      <span>{d.domain}</span>
                      <span className="text-[#6b6252] text-[10px]">{d.snapshot_count} snapshots</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <button
              type="submit"
              id="timemachine-search-btn"
              disabled={isLoading || !domainInput.trim()}
              className="px-4 py-2 bg-[#8b3a1f] text-[#fffdf7] rounded-lg text-xs font-medium hover:bg-[#6f2e17] disabled:opacity-50 transition-colors shadow-2xs flex items-center gap-1.5 shrink-0"
            >
              {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <History className="w-3.5 h-3.5" />}
              <span>Lookup Domain</span>
            </button>
          </form>

          {/* Quick preset links */}
          <div className="flex items-center gap-2 mt-3 text-xs overflow-x-auto no-scrollbar">
            <span className="text-[11px] text-[#6b6252] font-mono shrink-0">Sample historical domains:</span>
            {sampleDomains.map(item => (
              <button
                key={item.domain}
                onClick={() => {
                  setDomainInput(item.domain);
                  fetchDomain(item.domain);
                }}
                className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors shrink-0 ${
                  activeDomain === item.domain
                    ? 'bg-[#8b3a1f]/15 text-[#8b3a1f] border-[#8b3a1f]/40 font-semibold'
                    : 'bg-[#f5f0e6] text-[#6b6252] border-[#d8cfb8] hover:text-[#2b2620]'
                }`}
              >
                {item.domain}
              </button>
            ))}
          </div>
        </div>

        {/* Loading State */}
        {isLoading && (
          <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-10 text-center shadow-2xs">
            <Loader2 className="w-8 h-8 text-[#8b3a1f] animate-spin mx-auto mb-3" />
            <p className="font-serif-heading text-sm font-semibold text-[#2b2620]">
              Querying Wayback CDX Server for {activeDomain}...
            </p>
            <p className="text-xs text-[#6b6252] mt-1 font-mono">
              Retrieving timestamp intervals and historical HTTP response codes
            </p>
          </div>
        )}

        {/* 404 STATE: Domain not cached -> Request indexing workflow */}
        {!isLoading && is404 && activeDomain && (
          <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-6 shadow-2xs animate-in fade-in duration-200">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-[#a67c1e]/15 text-[#a67c1e] flex items-center justify-center shrink-0">
                <AlertCircle className="w-5 h-5" />
              </div>
              <div className="flex-1">
                <h3 className="font-serif-heading font-semibold text-base text-[#2b2620]">
                  This domain hasn't been indexed yet.
                </h3>
                <p className="text-xs text-[#6b6252] mt-1 leading-relaxed">
                  No cached Wayback CDX snapshot metadata exists in the local vector cache for{' '}
                  <span className="font-mono font-semibold text-[#8b3a1f]">{activeDomain}</span>. You can trigger an automated background ingestion job to crawl Memento records and index historical chunks.
                </p>

                {/* Indexing trigger button */}
                {!ingestJob ? (
                  <div className="mt-4">
                    <button
                      id="request-indexing-btn"
                      onClick={handleRequestIngest}
                      disabled={isRequestingIngest}
                      className="px-4 py-2 bg-[#8b3a1f] text-[#fffdf7] rounded-lg text-xs font-medium hover:bg-[#6f2e17] transition-colors shadow-2xs flex items-center gap-1.5"
                    >
                      {isRequestingIngest ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          <span>Dispatching Ingestion Task...</span>
                        </>
                      ) : (
                        <>
                          <RefreshCw className="w-3.5 h-3.5" />
                          <span>Request Ingestion & Indexing</span>
                        </>
                      )}
                    </button>
                  </div>
                ) : (
                  /* Live Ingestion Job Status Dashboard */
                  <div className="mt-4 p-4 bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg space-y-2 text-xs font-mono">
                    <div className="flex items-center justify-between text-[#2b2620]">
                      <span className="font-semibold text-[11px] text-[#8b3a1f]">
                        JOB ID: {ingestJob.job_id}
                      </span>
                      <span className="uppercase text-[10px] px-1.5 py-0.5 rounded bg-[#8b3a1f]/10 text-[#8b3a1f] font-bold">
                        {ingestJob.status}
                      </span>
                    </div>

                    {/* Progress Bar */}
                    <div className="h-2 w-full bg-[#d8cfb8] rounded-full overflow-hidden">
                      <div
                        style={{ width: `${ingestJob.progress}%` }}
                        className="h-full bg-[#8b3a1f] transition-all duration-300"
                      />
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-[#6b6252]">
                      <span>{ingestJob.message}</span>
                      <span>{ingestJob.progress}%</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 200 STATE: Mini-Dashboard */}
        {!isLoading && snapshotData && (
          <div className="space-y-6 animate-in fade-in duration-200">
            {/* Stats Metrics Cards */}
            <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-5 shadow-2xs">
              <div className="flex items-center justify-between border-b border-[#d8cfb8] pb-3 mb-4">
                <div>
                  <h3 className="font-serif-heading text-lg font-bold text-[#2b2620]">
                    {snapshotData.domain}
                  </h3>
                  <p className="text-xs text-[#6b6252] font-mono">
                    CDX Archive Summary & Timestamp Range
                  </p>
                </div>
                <a
                  href={`https://web.archive.org/web/*/${snapshotData.domain}`}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-xs text-[#8b3a1f] hover:underline font-mono"
                >
                  <span>Open on Wayback Machine</span>
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>

              {/* Phrasing Mandate: Always "known snapshot", never "launched" or "went live" */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs mb-4">
                <div className="bg-[#f5f0e6] p-3 rounded-lg border border-[#d8cfb8]">
                  <span className="text-[10px] uppercase font-semibold text-[#6b6252] block">
                    Earliest known snapshot:
                  </span>
                  <span className="font-mono text-sm font-bold text-[#2b2620] mt-0.5 block">
                    {snapshotData.earliest_snapshot}
                  </span>
                  <span className="text-[10px] text-[#6b6252] mt-1 block">
                    First recorded CDX capture
                  </span>
                </div>

                <div className="bg-[#f5f0e6] p-3 rounded-lg border border-[#d8cfb8]">
                  <span className="text-[10px] uppercase font-semibold text-[#6b6252] block">
                    Latest snapshot:
                  </span>
                  <span className="font-mono text-sm font-bold text-[#2b2620] mt-0.5 block">
                    {snapshotData.latest_snapshot}
                  </span>
                  <span className="text-[10px] text-[#6b6252] mt-1 block">
                    Most recent archived crawl
                  </span>
                </div>

                <div className="bg-[#f5f0e6] p-3 rounded-lg border border-[#d8cfb8]">
                  <span className="text-[10px] uppercase font-semibold text-[#6b6252] block">
                    Total snapshot count:
                  </span>
                  <span className="font-mono text-sm font-bold text-[#8b3a1f] mt-0.5 block">
                    {snapshotData.total_snapshots.toLocaleString()}
                  </span>
                  <span className="text-[10px] text-[#6b6252] mt-1 block">
                    Aggregated Memento responses
                  </span>
                </div>
              </div>

              {/* Gap Years Callout */}
              {snapshotData.gap_years && snapshotData.gap_years.length > 0 && (
                <div className="p-3 bg-[#a67c1e]/10 border border-[#a67c1e]/30 rounded-lg text-xs text-[#2b2620] mb-4 flex items-start gap-2">
                  <Calendar className="w-4 h-4 text-[#a67c1e] shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold text-[#a67c1e] block">
                      Archive Interval Gap Identified:
                    </span>
                    <p className="text-[11px] text-[#6b6252] mt-0.5">
                      {snapshotData.gap_years.join('; ')} — Zero web crawler captures recorded during these intervals.
                    </p>
                  </div>
                </div>
              )}

              {/* Mini Bar Chart of snapshots per year */}
              <div className="mt-4 pt-3 border-t border-[#d8cfb8]">
                <h4 className="font-serif-heading font-semibold text-xs text-[#2b2620] mb-3">
                  Historical Snapshot Frequency by Year
                </h4>

                <div className="h-32 flex items-end justify-between gap-1 px-1 border-b border-[#d8cfb8]">
                  {Object.entries(snapshotData.snapshots_per_year).map(([year, rawCount]) => {
                    const count = Number(rawCount);
                    const values = Object.values(snapshotData.snapshots_per_year).map(Number);
                    const maxVal = Math.max(1, ...values);
                    const heightPct = count > 0 ? Math.max(10, Math.round((count / maxVal) * 100)) : 0;

                    return (
                      <div
                        key={year}
                        className="flex-1 flex flex-col items-center justify-end h-full group relative"
                      >
                        {count > 0 ? (
                          <div
                            style={{ height: `${heightPct}%` }}
                            className="w-full bg-[#8b3a1f] rounded-t-xs group-hover:bg-[#6f2e17] transition-all"
                            title={`${year}: ${count} snapshots`}
                          />
                        ) : (
                          <div className="w-full h-1 bg-[#d8cfb8]" title={`${year}: No snapshots`} />
                        )}
                        <span className="text-[8px] font-mono text-[#6b6252] mt-1 group-hover:font-bold">
                          {parseInt(year, 10) % 3 === 0 ? `'${year.slice(-2)}` : ''}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Analyze Evolution Button */}
              <div className="mt-4 pt-3 border-t border-[#d8cfb8]">
                <button
                  onClick={fetchEvolution}
                  disabled={isLoadingEvolution}
                  className="w-full px-4 py-2 bg-[#a67c1e] text-[#fffdf7] rounded-lg text-xs font-medium hover:bg-[#8a6816] disabled:opacity-50 transition-colors shadow-2xs flex items-center justify-center gap-2"
                >
                  {isLoadingEvolution ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Analyzing Content Evolution...</span>
                    </>
                  ) : (
                    <>
                      <TrendingUp className="w-3.5 h-3.5" />
                      <span>Analyze Website Evolution Across Snapshots</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Evolution Analysis Panel */}
            {showEvolution && (
              <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-5 shadow-2xs animate-in fade-in duration-200">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Layers className="w-4 h-4 text-[#a67c1e]" />
                    <h4 className="font-serif-heading text-sm font-bold text-[#2b2620]">
                      Content Evolution Analysis
                    </h4>
                  </div>
                  <button
                    onClick={() => setShowEvolution(false)}
                    className="text-[10px] text-[#6b6252] hover:text-[#2b2620] font-mono"
                  >
                    [close]
                  </button>
                </div>

                {isLoadingEvolution ? (
                  <div className="py-8 text-center">
                    <Loader2 className="w-6 h-6 text-[#a67c1e] animate-spin mx-auto mb-2" />
                    <p className="text-xs text-[#6b6252]">Analyzing content across snapshots...</p>
                  </div>
                ) : evolutionData ? (
                  <div className="space-y-4">
                    {/* Ingesting status banner */}
                    {(evolutionData.status === 'ingesting' || evolutionData.status === 'llm_analyzed') && (
                      <div className="p-3 bg-[#a67c1e]/10 border border-[#a67c1e]/30 rounded-lg text-xs text-[#2b2620] flex items-start gap-2">
                        {evolutionData.status === 'ingesting' ? (
                          <Loader2 className="w-4 h-4 text-[#a67c1e] shrink-0 mt-0.5 animate-spin" />
                        ) : (
                          <TrendingUp className="w-4 h-4 text-[#a67c1e] shrink-0 mt-0.5" />
                        )}
                        <div>
                          <span className="font-bold text-[#a67c1e] block">
                            {evolutionData.status === 'llm_analyzed' ? 'LLM Historical Analysis' : 'Content Indexing In Progress'}
                          </span>
                          <p className="text-[11px] text-[#6b6252] mt-0.5">
                            {evolutionData.status === 'llm_analyzed' 
                              ? 'Analysis based on snapshot metadata and historical context. Content ingestion is also running in the background for deeper analysis.'
                              : 'This domain has ' + (evolutionData.snapshot_count?.toLocaleString() || '') + ' Wayback snapshots but content has not been indexed yet. Background ingestion is running.'
                            }
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Summary */}
                    <div className="p-3 bg-[#f5f0e6] rounded-lg border border-[#d8cfb8]">
                      <p className="text-xs text-[#2b2620] font-serif leading-relaxed">
                        {evolutionData.summary}
                      </p>
                    </div>

                    {/* Trend + Key Topics */}
                    {(evolutionData.trend !== 'stable' || (evolutionData.key_topics && evolutionData.key_topics.length > 0)) && (
                      <div className="flex items-center gap-4 text-xs">
                        {evolutionData.trend !== 'stable' && (
                          <div className="flex items-center gap-1.5">
                            {getTrendIcon(evolutionData.trend)}
                            <span className="text-[#6b6252]">Trend:</span>
                            <span className="font-semibold text-[#2b2620] capitalize">
                              {evolutionData.trend}
                            </span>
                          </div>
                        )}
                        {evolutionData.key_topics && evolutionData.key_topics.length > 0 && (
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="text-[#6b6252]">Key topics:</span>
                            {evolutionData.key_topics.map((topic, i) => (
                              <span
                                key={i}
                                className="px-1.5 py-0.5 bg-[#8b3a1f]/10 text-[#8b3a1f] rounded text-[10px] font-mono"
                              >
                                {topic}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Eras Timeline */}
                    {evolutionData.eras && evolutionData.eras.length > 0 && (
                      <div className="space-y-3">
                        <h5 className="font-serif-heading text-xs font-semibold text-[#2b2620]">
                          Historical Eras
                        </h5>
                        <div className="relative pl-4 border-l-2 border-[#d8cfb8]">
                          {evolutionData.eras.map((era, i) => (
                            <div key={i} className="mb-4 last:mb-0 relative">
                              <div className="absolute -left-[1.3rem] w-3 h-3 rounded-full bg-[#a67c1e] border-2 border-[#fffdf7]" />
                              <div className="bg-[#f5f0e6] p-3 rounded-lg border border-[#d8cfb8]">
                                <div className="flex items-center gap-2 mb-1">
                                  <span className="font-mono text-[10px] font-bold text-[#a67c1e] bg-[#a67c1e]/10 px-1.5 py-0.5 rounded">
                                    {era.period}
                                  </span>
                                </div>
                                <p className="text-[11px] text-[#2b2620] font-serif">
                                  {era.focus}
                                </p>
                                {era.key_changes && era.key_changes.length > 0 && (
                                  <ul className="mt-2 space-y-0.5">
                                    {era.key_changes.map((change, j) => (
                                      <li key={j} className="text-[10px] text-[#6b6252] flex items-start gap-1">
                                        <span className="text-[#a67c1e] mt-0.5">•</span>
                                        {change}
                                      </li>
                                    ))}
                                  </ul>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Historical Context */}
                    {evolutionData.historical_context && (
                      <div className="p-3 bg-[#8b3a1f]/5 border border-[#8b3a1f]/20 rounded-lg">
                        <span className="text-[10px] uppercase font-semibold text-[#8b3a1f] block mb-1">Historical Context</span>
                        <p className="text-[11px] text-[#2b2620] font-serif leading-relaxed">
                          {evolutionData.historical_context}
                        </p>
                      </div>
                    )}

                    {/* Archival Notes */}
                    {evolutionData.archival_notes && (
                      <div className="p-3 bg-[#a67c1e]/5 border border-[#a67c1e]/20 rounded-lg">
                        <span className="text-[10px] uppercase font-semibold text-[#a67c1e] block mb-1">Archival Significance</span>
                        <p className="text-[11px] text-[#2b2620] font-serif leading-relaxed">
                          {evolutionData.archival_notes}
                        </p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="py-6 text-center">
                    <AlertCircle className="w-5 h-5 text-[#6b6252] mx-auto mb-2" />
                    <p className="text-xs text-[#6b6252]">
                      Unable to generate evolution analysis. Ensure snapshots are indexed for this domain.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Ask About This Website's History -> Routes to Chat */}
            <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-5 shadow-2xs">
              <div className="flex items-center gap-2 mb-2">
                <MessageSquare className="w-4 h-4 text-[#8b3a1f]" />
                <h4 className="font-serif-heading text-sm font-bold text-[#2b2620]">
                  Ask About {snapshotData.domain}'s Historical Architecture
                </h4>
              </div>
              <p className="text-xs text-[#6b6252] mb-3 font-serif">
                Formulate an evidence-grounded inquiry using Memento snapshots and laboratory memos associated with this domain.
              </p>

              <form onSubmit={handleAskSubmit} className="flex gap-2">
                <input
                  type="text"
                  placeholder={`e.g. What were the prominent AI projects hosted on ${snapshotData.domain} in the late 1990s?`}
                  value={chatQuestion}
                  onChange={e => setChatQuestion(e.target.value)}
                  className="flex-1 px-3 py-2 text-xs bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg text-[#2b2620] placeholder-[#6b6252]/70 focus:outline-none focus:border-[#8b3a1f] font-serif"
                />
                <button
                  type="submit"
                  className="px-4 py-2 bg-[#8b3a1f] text-[#fffdf7] rounded-lg text-xs font-medium hover:bg-[#6f2e17] transition-colors shadow-2xs flex items-center gap-1 shrink-0"
                >
                  <span>Query in Chat</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
