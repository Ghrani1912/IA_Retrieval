import React, { useState, useRef, useEffect } from 'react';
import {
  Send,
  Sparkles,
  ThumbsUp,
  ThumbsDown,
  Copy,
  Share2,
  RotateCcw,
  BookOpen,
  Search,
  Check,
  Globe,
  FileText,
  AlertTriangle,
  Radio,
  SlidersHorizontal,
  X,
  Info
} from 'lucide-react';
import { ChatMessage, AppSettings, SourceDocument, RetrievedChunk } from '../types';
import { CitationConfidenceBar } from './CitationConfidenceBar';
import { EvidenceCards } from './EvidenceCards';

interface ChatViewProps {
  messages: ChatMessage[];
  onSendMessage: (query: string, filters?: ChatMessage['sourceFilter']) => void;
  onRetryMessage: (query: string, filters?: ChatMessage['sourceFilter']) => void;
  onFeedback: (messageId: string, feedback: 'up' | 'down') => void;
  onSelectSource: (sourceId: string) => void;
  isStreaming: boolean;
  activeFilter?: ChatMessage['sourceFilter'];
  onClearFilter?: () => void;
  settings: AppSettings;
  onOpenSettings: () => void;
  onShowToast: (msg: string) => void;
}

export const ChatView: React.FC<ChatViewProps> = ({
  messages,
  onSendMessage,
  onRetryMessage,
  onFeedback,
  onSelectSource,
  isStreaming,
  activeFilter,
  onClearFilter,
  settings,
  onOpenSettings,
  onShowToast
}) => {
  const [inputQuery, setInputQuery] = useState('');
  const [hoveredCitation, setHoveredCitation] = useState<{
    index: number;
    chunk?: RetrievedChunk;
    x: number;
    y: number;
  } | null>(null);

  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const starterQueries = [
    {
      title: 'Semantic Networks in 1970s AI',
      query: 'What were semantic networks and how were they used in AI?'
    },
    {
      title: 'MYCIN & Certainty Factors',
      query: 'How did expert systems like MYCIN work and handle uncertainty?'
    },
    {
      title: 'Japanese Fifth Generation Project',
      query: 'What was the Japanese Fifth Generation Computer project?'
    },
    {
      title: 'LISP Machine Architectures',
      query: 'What were the core architectural innovations of 1980s LISP Machines?'
    }
  ];

  // Auto-scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputQuery.trim() || isStreaming) return;
    onSendMessage(inputQuery.trim(), activeFilter);
    setInputQuery('');
  };

  const handleCopyAnswer = (messageId: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedMessageId(messageId);
    onShowToast('Answer copied to clipboard.');
    setTimeout(() => setCopiedMessageId(null), 2000);
  };

  const handleShareAnswer = (message: ChatMessage) => {
    const url = `${window.location.origin}?q=${encodeURIComponent(message.text.substring(0, 80))}`;
    navigator.clipboard.writeText(url);
    onShowToast('Permalink copied to clipboard.');
  };

  /**
   * Enforce citation tooltip logic strictly:
   * Books/papers: "Source: [Title] by [Author], [Year] — Page [X]"
   * Website: "Source: [Domain] — Archived [Date]" (NEVER "Published" or "launched")
   */
  const getCitationTooltipText = (chunk: RetrievedChunk): string => {
    if (chunk.capture_timestamp || chunk.source_type === 'Website') {
      const ts = chunk.capture_timestamp
        ? chunk.capture_timestamp.split('T')[0]
        : chunk.pub_date || 'Wayback Record';
      const domainStr = chunk.domain || 'Internet Archive Snapshot';
      return `Source: ${domainStr} — Archived ${ts}`;
    }

    const authorStr = chunk.author ? `by ${chunk.author.split(';')[0]}` : '';
    const yearStr = chunk.year || (chunk.pub_date ? chunk.pub_date.substring(0, 4) : 'Historical');
    const pageStr = chunk.page_number ? ` — Page ${chunk.page_number}` : '';
    return `Source: ${chunk.source_title} ${authorStr}, ${yearStr}${pageStr}`;
  };

  /**
   * Render answer text with interactive [1], [2] citation markers
   */
  const renderParsedAnswer = (message: ChatMessage) => {
    const answerResponse = message.answerResponse;
    const rawText = message.text;

    if (!answerResponse || !answerResponse.retrieved_chunks || answerResponse.retrieved_chunks.length === 0) {
      // Plain text during initial token stream
      return (
        <div className="text-sm text-[#2b2620] leading-relaxed whitespace-pre-wrap font-serif">
          {rawText}
          {message.isStreaming && <span className="streaming-cursor" />}
        </div>
      );
    }

    // Split text by bracket citations like [1], [2], etc.
    const parts = rawText.split(/(\[\d+\])/g);

    return (
      <div className="text-[14.5px] text-[#2b2620] leading-relaxed font-serif">
        {parts.map((part, pIdx) => {
          const match = part.match(/\[(\d+)\]/);
          if (match) {
            const citNum = parseInt(match[1], 10);
            const chunk = answerResponse.retrieved_chunks[citNum - 1];

            return (
              <span
                key={pIdx}
                onClick={() => chunk && onSelectSource(chunk.source_id)}
                onMouseEnter={e => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  setHoveredCitation({
                    index: citNum,
                    chunk,
                    x: rect.left + window.scrollX,
                    y: rect.top + window.scrollY - 10
                  });
                }}
                onMouseLeave={() => setHoveredCitation(null)}
                className="citation-link font-mono text-[12px] inline-block select-none"
              >
                [{citNum}]
              </span>
            );
          }
          return <span key={pIdx}>{part}</span>;
        })}
        {message.isStreaming && <span className="streaming-cursor" />}
      </div>
    );
  };

  return (
    <div className="flex-1 flex flex-col h-[calc(100vh-3.5rem)] bg-[#f5f0e6] relative overflow-hidden">
      {/* Header bar */}
      <div className="px-4 py-2.5 bg-[#fffdf7] border-b border-[#d8cfb8] flex items-center justify-between shadow-2xs z-10 shrink-0">
        <div>
          <h1 className="font-serif-heading text-base font-bold text-[#2b2620] flex items-center gap-2">
            <span>Historical Intelligence</span>
            <span className="text-[10px] font-sans font-normal px-2 py-0.5 bg-[#f5f0e6] border border-[#d8cfb8] rounded text-[#6b6252]">
              1970s–1990s Research
            </span>
          </h1>
          <p className="text-[11px] text-[#6b6252]">
            Evidence-grounded answers anchored to primary DTIC, ERIC & Americana literature
          </p>
        </div>

        {/* Filter badge if active */}
        {activeFilter && (
          <div className="flex items-center gap-1.5 bg-[#8b3a1f]/10 border border-[#8b3a1f]/30 px-2.5 py-1 rounded-md text-xs text-[#8b3a1f]">
            <Search className="w-3 h-3 text-[#8b3a1f]" />
            <span className="font-mono text-[11px]">
              Filtered by: {activeFilter.domain || activeFilter.source_title || 'Targeted Corpus'}
            </span>
            {onClearFilter && (
              <button onClick={onClearFilter} className="hover:text-[#6f2e17] ml-1">
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
        {messages.length === 0 ? (
          /* STATE 1: Empty / Welcome */
          <div className="max-w-2xl mx-auto my-auto pt-6 pb-10 text-center select-none animate-in fade-in duration-300">
            <div className="w-14 h-14 rounded-xl bg-[#8b3a1f] text-[#fffdf7] mx-auto flex items-center justify-center shadow-md mb-4">
              <BookOpen className="w-7 h-7" />
            </div>

            <h2 className="font-display-title text-2xl sm:text-3xl font-bold text-[#2b2620] mb-2 tracking-wide">
              Historical Intelligence
            </h2>
            <p className="text-sm sm:text-base text-[#6b6252] max-w-lg mx-auto font-serif leading-relaxed mb-6">
              Investigate the architecture, debates, and empirical results of computer science and AI research from 1970 to 1998.
            </p>

            {/* Starter Query Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-left mb-6">
              {starterQueries.map((starter, i) => (
                <button
                  key={i}
                  id={`starter-query-card-${i}`}
                  onClick={() => onSendMessage(starter.query, activeFilter)}
                  className="p-3.5 bg-[#fffdf7] border border-[#d8cfb8] rounded-lg text-left shadow-2xs hover:border-[#8b3a1f] hover:shadow-sm hover:-translate-y-0.5 transition-all group"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] font-semibold text-[#8b3a1f] font-mono">
                      {starter.title}
                    </span>
                    <Sparkles className="w-3 h-3 text-[#8b3a1f] opacity-60 group-hover:opacity-100" />
                  </div>
                  <p className="text-xs text-[#2b2620] line-clamp-2 font-serif">
                    "{starter.query}"
                  </p>
                </button>
              ))}
            </div>

            <div className="inline-flex items-center gap-2 text-xs text-[#6b6252] bg-[#fffdf7] border border-[#d8cfb8] px-3.5 py-1.5 rounded-full font-mono shadow-2xs">
              <span className="w-2 h-2 rounded-full bg-[#3f6b3f]" />
              <span>Powered by 44 indexed sources from DTIC, ERIC, and Americana collections</span>
            </div>
          </div>
        ) : (
          /* Render Messages */
          messages.map(msg => {
            const isUser = msg.sender === 'user';

            if (isUser) {
              return (
                <div key={msg.id} className="flex justify-end animate-in fade-in duration-200">
                  <div className="max-w-xl bg-[#8b3a1f] text-[#fffdf7] px-4 py-2.5 rounded-2xl rounded-tr-xs shadow-2xs text-sm">
                    <p className="whitespace-pre-wrap">{msg.text}</p>
                    {msg.sourceFilter && (
                      <div className="mt-1 text-[10px] text-[#fffdf7]/80 font-mono flex items-center gap-1 border-t border-[#fffdf7]/20 pt-1">
                        <Search className="w-2.5 h-2.5" />
                        <span>Filter: {msg.sourceFilter.domain || msg.sourceFilter.source_title}</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            }

            // Assistant message
            return (
              <div
                key={msg.id}
                id={`assistant-message-${msg.id}`}
                className="flex gap-3 max-w-3xl animate-in fade-in duration-200"
              >
                <div className="w-7 h-7 rounded-md bg-[#2b2620] text-[#fffdf7] flex items-center justify-center shrink-0 mt-1 shadow-2xs">
                  <BookOpen className="w-3.5 h-3.5 text-[#f5f0e6]" />
                </div>

                <div className="flex-1 bg-[#fffdf7] border border-[#d8cfb8] rounded-xl p-4 sm:p-5 shadow-2xs">
                  {/* STATE 2: Loading SSE status events */}
                  {msg.isLoading && (!msg.text || msg.statusUpdates?.length) && (
                    <div className="space-y-2 py-1">
                      <div className="flex items-center gap-2 text-xs text-[#6b6252] font-mono">
                        <div className="flex items-center gap-1">
                          <span className="typing-dot" />
                          <span className="typing-dot" />
                          <span className="typing-dot" />
                        </div>
                        <span className="font-semibold text-[#8b3a1f]">Retrieving archival evidence...</span>
                      </div>

                      {msg.statusUpdates && msg.statusUpdates.length > 0 && (
                        <div className="space-y-1 pl-4 border-l-2 border-[#8b3a1f]/30">
                          {msg.statusUpdates.map((st, sIdx) => (
                            <div
                              key={sIdx}
                              className="text-[11px] font-mono text-[#6b6252] flex items-center gap-1.5 animate-in fade-in duration-150"
                            >
                              <span className="text-[#8b3a1f]">›</span>
                              <span>{st}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* ERROR STATE: 503 / Stream Error / Zero chunks */}
                  {msg.error ? (
                    <div className="p-3 bg-[#a13a2f]/10 border border-[#a13a2f]/30 rounded-lg text-xs text-[#a13a2f] flex items-start gap-2.5">
                      <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                      <div className="space-y-1.5">
                        <p className="font-semibold">{msg.error}</p>
                        <button
                          onClick={() => onRetryMessage(messages[messages.indexOf(msg) - 1]?.text || '', msg.sourceFilter)}
                          className="flex items-center gap-1 text-[11px] font-bold text-[#a13a2f] underline hover:text-[#6f2e17]"
                        >
                          <RotateCcw className="w-3 h-3" />
                          <span>Retry Query</span>
                        </button>
                      </div>
                    </div>
                  ) : msg.isNoChunksFound ? (
                    <div className="p-3 bg-[#f5f0e6] border border-[#d8cfb8] rounded-lg text-xs text-[#6b6252] flex items-start gap-2.5">
                      <Search className="w-4 h-4 shrink-0 mt-0.5 text-[#8b3a1f]" />
                      <div>
                        <p className="font-semibold text-[#2b2620]">
                          No sources in the indexed corpus address this question.
                        </p>
                        <p className="text-[11px] mt-1 text-[#6b6252]">
                          Try querying topics such as semantic networks, MYCIN, STRIPS planning, LISP machines, or Wayback domains with a domain filter.
                        </p>
                      </div>
                    </div>
                  ) : (
                    /* STATES 3 & 4: Streaming or Completed Answer */
                    <>
                      {/* Parsed Answer Paragraphs with Citations */}
                      {renderParsedAnswer(msg)}

                      {/* Citation Confidence Bar (if enabled in settings) */}
                      {settings.showCitationConfidence && msg.answerResponse && (
                        <CitationConfidenceBar
                          segments={msg.answerResponse.answer_segments}
                          distribution={msg.answerResponse.citation_distribution}
                        />
                      )}

                      {/* Low-Evidence Warning: fires when chunks come from ≤2 unique sources */}
                      {!msg.isStreaming && msg.answerResponse && msg.answerResponse.retrieved_chunks && msg.answerResponse.retrieved_chunks.length > 0 && (() => {
                        const uniqueSources = new Set(msg.answerResponse!.retrieved_chunks!.map((c: any) => c.source_id));
                        return uniqueSources.size <= 2;
                      })() && (
                        <div className="mt-2 p-2 bg-amber-50 border border-amber-200 rounded-md text-[11px] text-amber-800 flex items-start gap-1.5">
                          <Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                          <span>
                            <strong>Thin evidence:</strong> Answers drawn from only {(() => { const s = new Set(msg.answerResponse!.retrieved_chunks!.map((c: any) => c.source_id)); return s.size; })()} unique source{(() => { const s = new Set(msg.answerResponse!.retrieved_chunks!.map((c: any) => c.source_id)); return s.size !== 1 ? 's' : '' })()}. Answer may be incomplete or reflect a single document's perspective.
                          </span>
                        </div>
                      )}

                      {/* Citation Confidence Warning */}
                      {!msg.isStreaming && msg.answerResponse?.citation_distribution && msg.answerResponse.citation_distribution.unknown > 50 && (
                        <div className="mt-2 p-2 bg-orange-50 border border-orange-200 rounded-md text-[11px] text-orange-800 flex items-start gap-1.5">
                          <Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                          <span>
                            <strong>Low citation confidence:</strong> {msg.answerResponse.citation_distribution.unknown}% of claims could not be verified against source text. Treat with caution.
                          </span>
                        </div>
                      )}

                      {/* Evidence Source Cards */}
                      {msg.answerResponse && msg.answerResponse.retrieved_chunks?.length > 0 && (
                        <EvidenceCards
                          chunks={msg.answerResponse.retrieved_chunks}
                          onSelectSource={onSelectSource}
                        />
                      )}

                      {/* Feedback & Actions Row */}
                      {!msg.isStreaming && msg.text && (
                        <div className="mt-3 pt-2.5 border-t border-[#d8cfb8]/50 flex items-center justify-between text-xs text-[#6b6252]">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[11px] text-[#6b6252]">Verified citation trail</span>
                          </div>

                          <div className="flex items-center gap-1 sm:gap-2">
                            <button
                              onClick={() => onFeedback(msg.id, 'up')}
                              title="Helpful synthesis"
                              className={`p-1.5 rounded hover:bg-[#f5f0e6] transition-colors ${
                                msg.feedback === 'up' ? 'text-[#3f6b3f] font-bold bg-[#3f6b3f]/10' : 'text-[#6b6252]'
                              }`}
                            >
                              <ThumbsUp className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => onFeedback(msg.id, 'down')}
                              title="Inaccurate or weak evidence"
                              className={`p-1.5 rounded hover:bg-[#f5f0e6] transition-colors ${
                                msg.feedback === 'down' ? 'text-[#a13a2f] font-bold bg-[#a13a2f]/10' : 'text-[#6b6252]'
                              }`}
                            >
                              <ThumbsDown className="w-3.5 h-3.5" />
                            </button>
                            <span className="w-px h-3.5 bg-[#d8cfb8] mx-1" />
                            <button
                              onClick={() => handleCopyAnswer(msg.id, msg.text)}
                              title="Copy full answer"
                              className="p-1.5 rounded hover:bg-[#f5f0e6] text-[#6b6252] hover:text-[#2b2620] flex items-center gap-1 text-[11px]"
                            >
                              {copiedMessageId === msg.id ? (
                                <>
                                  <Check className="w-3.5 h-3.5 text-[#3f6b3f]" />
                                  <span className="text-[#3f6b3f] text-[10px]">Copied</span>
                                </>
                              ) : (
                                <>
                                  <Copy className="w-3.5 h-3.5" />
                                  <span className="hidden sm:inline text-[10px]">Copy</span>
                                </>
                              )}
                            </button>
                            <button
                              onClick={() => handleShareAnswer(msg)}
                              title="Share permalink"
                              className="p-1.5 rounded hover:bg-[#f5f0e6] text-[#6b6252] hover:text-[#2b2620] flex items-center gap-1 text-[11px]"
                            >
                              <Share2 className="w-3.5 h-3.5" />
                              <span className="hidden sm:inline text-[10px]">Share</span>
                            </button>
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Floating Citation Tooltip */}
      {hoveredCitation && hoveredCitation.chunk && (
        <div
          style={{
            position: 'fixed',
            left: `${Math.min(window.innerWidth - 320, Math.max(16, hoveredCitation.x - 40))}px`,
            top: `${hoveredCitation.y - 44}px`
          }}
          className="z-50 bg-[#2b2620] text-[#fffdf7] text-xs px-3 py-1.5 rounded-md shadow-xl max-w-sm pointer-events-none animate-in fade-in duration-100 font-sans border border-[#d8cfb8]/30"
        >
          <div className="font-mono text-[11px]">
            {getCitationTooltipText(hoveredCitation.chunk)}
          </div>
        </div>
      )}

      {/* Input Bar */}
      <div className="p-3 sm:p-4 bg-[#fffdf7] border-t border-[#d8cfb8] shadow-xs z-10 shrink-0">
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto flex items-center gap-2">
          <div className="relative flex-1">
            <input
              ref={inputRef}
              id="chat-query-input"
              type="text"
              placeholder="Ask questions about AI research from the 1970s–1990s or Wayback domain history..."
              value={inputQuery}
              onChange={e => setInputQuery(e.target.value)}
              disabled={isStreaming}
              className="w-full pl-4 pr-10 py-2.5 text-sm bg-[#f5f0e6] border border-[#d8cfb8] rounded-xl text-[#2b2620] placeholder-[#6b6252]/70 focus:outline-none focus:border-[#8b3a1f] focus:ring-1 focus:ring-[#8b3a1f]/30 disabled:opacity-50 transition-colors shadow-2xs font-serif"
            />
            {inputQuery && (
              <button
                type="button"
                onClick={() => setInputQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[#6b6252] hover:text-[#2b2620]"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          <button
            type="submit"
            id="chat-send-btn"
            disabled={!inputQuery.trim() || isStreaming}
            className="px-4 py-2.5 bg-[#8b3a1f] text-[#fffdf7] rounded-xl font-medium text-xs hover:bg-[#6f2e17] disabled:opacity-40 disabled:hover:bg-[#8b3a1f] transition-all flex items-center gap-1.5 shadow-2xs shrink-0 cursor-pointer"
          >
            <span>Ask Archive</span>
            <Send className="w-3.5 h-3.5" />
          </button>
        </form>
      </div>
    </div>
  );
};
