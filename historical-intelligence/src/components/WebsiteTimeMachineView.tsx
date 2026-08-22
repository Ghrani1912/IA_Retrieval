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
  MessageSquare
} from 'lucide-react';
import { SnapshotData, IngestJob } from '../types';
import { HistoricalApiService } from '../services/api';

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
  const [is404, setIs404] = useState(false);

  // Ingestion job state
  const [ingestJob, setIngestJob] = useState<IngestJob | null>(null);
  const [isRequestingIngest, setIsRequestingIngest] = useState(false);

  // Chat follow-up input
  const [chatQuestion, setChatQuestion] = useState('');

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

  // Initial load
  useEffect(() => {
    if (activeDomain) {
      fetchDomain(activeDomain);
    }
  }, []);

  const handleDomainSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!domainInput.trim()) return;
    fetchDomain(domainInput);
  };

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
                onChange={e => setDomainInput(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-sm bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg text-[#2b2620] placeholder-[#6b6252]/70 focus:outline-none focus:border-[#8b3a1f] font-mono"
              />
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
            </div>

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
