import React, { useState, useEffect } from 'react';
import { TopBar, ViewTab } from './components/TopBar';
import { SourceBrowser } from './components/SourceBrowser';
import { ChatView } from './components/ChatView';
import { TimelineView } from './components/TimelineView';
import { WebsiteTimeMachineView } from './components/WebsiteTimeMachineView';
import { SourceExplorerView } from './components/SourceExplorerView';
import { SettingsModal } from './components/SettingsModal';
import { Toast } from './components/Toast';
import { ChatMessage, AppSettings, SourceDocument, AnswerResponse } from './types';
import { HistoricalApiService } from './services/api';

export default function App() {
  const [activeTab, setActiveTab] = useState<ViewTab>('chat');
  const [isBrowserOpen, setIsBrowserOpen] = useState(true);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);

  // Settings State
  const [settings, setSettings] = useState<AppSettings>({
    showCitationConfidence: true,
    streamAnswers: true,
    backendUrl: 'http://localhost:8000',
    useFallbackSimulation: true
  });
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isBackendConnected, setIsBackendConnected] = useState(false);

  // Toast notifications
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  // Chat State
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeFilter, setActiveFilter] = useState<ChatMessage['sourceFilter'] | undefined>(undefined);

  // Initial Health Check
  const checkHealth = async () => {
    const res = await HistoricalApiService.checkHealth();
    setIsBackendConnected(res.isOnline);
  };

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  // Update Settings
  const handleUpdateSettings = (newSettings: Partial<AppSettings>) => {
    setSettings(prev => ({ ...prev, ...newSettings }));
  };

  // Chat Query Execution
  const handleSendMessage = async (queryText: string, filterContext?: ChatMessage['sourceFilter']) => {
    if (!queryText.trim() || isStreaming) return;

    const userMessageId = `usr_${Date.now()}`;
    const assistantMessageId = `asst_${Date.now() + 1}`;

    const userMsg: ChatMessage = {
      id: userMessageId,
      sender: 'user',
      text: queryText,
      sourceFilter: filterContext,
      timestamp: new Date().toISOString()
    };

    const assistantMsg: ChatMessage = {
      id: assistantMessageId,
      sender: 'assistant',
      text: '',
      statusUpdates: ['Connecting to archival query pipeline...'],
      isLoading: true,
      isStreaming: true,
      sourceFilter: filterContext,
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);

    if (activeTab !== 'chat') {
      setActiveTab('chat');
    }

    try {
      await HistoricalApiService.streamQuery(
        queryText,
        {
          domain: filterContext?.domain,
          source_id: filterContext?.source_id,
          date_from: filterContext?.date_from,
          date_to: filterContext?.date_to,
          stream: settings.streamAnswers
        },
        {
          onStatus: statusMsg => {
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMessageId
                  ? {
                      ...m,
                      statusUpdates: [...(m.statusUpdates || []), statusMsg]
                    }
                  : m
              )
            );
          },
          onToken: token => {
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMessageId
                  ? {
                      ...m,
                      text: m.text + token,
                      isLoading: false,
                      isStreaming: true
                    }
                  : m
              )
            );
          },
          onDone: (response: AnswerResponse) => {
            const fullText = response.answer_segments?.map(s => s.text).join(' ') ?? '';
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMessageId
                  ? {
                      ...m,
                      text: fullText,
                      answerResponse: response,
                      isLoading: false,
                      isStreaming: false
                    }
                  : m
              )
            );
            setIsStreaming(false);
          },
          onError: (errMsg, is503) => {
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMessageId
                  ? {
                      ...m,
                      error: errMsg,
                      isLoading: false,
                      isStreaming: false
                    }
                  : m
              )
            );
            setIsStreaming(false);
          },
          onNoChunksFound: () => {
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMessageId
                  ? {
                      ...m,
                      isNoChunksFound: true,
                      isLoading: false,
                      isStreaming: false
                    }
                  : m
              )
            );
            setIsStreaming(false);
          }
        }
      );
    } catch (err: any) {
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantMessageId
            ? {
                ...m,
                error: err?.message || 'Unexpected search pipeline error.',
                isLoading: false,
                isStreaming: false
              }
            : m
        )
      );
      setIsStreaming(false);
    }
  };

  const handleRetryMessage = (queryText: string, filterContext?: ChatMessage['sourceFilter']) => {
    handleSendMessage(queryText, filterContext);
  };

  const handleFeedback = (messageId: string, feedback: 'up' | 'down') => {
    setMessages(prev =>
      prev.map(m => (m.id === messageId ? { ...m, feedback } : m))
    );
    showToast(feedback === 'up' ? 'Feedback recorded: Helpful citation trace.' : 'Feedback recorded: Insufficient evidence flagged.');
  };

  // Actions from Source Browser or Explorer -> Pre-fill Chat
  const handleAskAboutSource = (source: SourceDocument) => {
    setActiveFilter({
      source_id: source.id,
      source_title: source.title
    });
    setActiveTab('chat');
    handleSendMessage(`Explain the principal methodology, contributions, and findings in "${source.title}" by ${source.author} (${source.year}).`, {
      source_id: source.id,
      source_title: source.title
    });
  };

  // Actions from Website Time Machine -> Pre-fill Chat
  const handleAskAboutDomain = (domain: string, question?: string) => {
    setActiveFilter({ domain });
    setActiveTab('chat');
    handleSendMessage(question || `What research programs and publications were hosted on ${domain} according to historical snapshots?`, {
      domain
    });
  };

  // Action from Timeline -> Filter by Year
  const handleFilterByYear = (year: number) => {
    setSelectedSourceId(null);
    showToast(`Source Explorer filtered to year ${year}.`);
    setActiveTab('explorer');
  };

  // Action from Timeline Date Brush -> Re-issue Query with date range
  const handleApplyDateRange = (from: number, to: number) => {
    const lastUserMsg = [...messages].reverse().find(m => m.sender === 'user');
    const query = lastUserMsg ? lastUserMsg.text : 'What were the major advancements in AI during this period?';

    setActiveFilter({
      date_from: from,
      date_to: to
    });
    setActiveTab('chat');
    handleSendMessage(query, {
      date_from: from,
      date_to: to
    });
    showToast(`Query re-issued with date filter: ${from}–${to}`);
  };

  // Get most recent message that contains retrieved chunks for Timeline view
  const lastMessageWithChunks = [...messages]
    .reverse()
    .find(m => m.answerResponse && m.answerResponse.retrieved_chunks?.length > 0);

  return (
    <div className="min-h-screen bg-[#f5f0e6] text-[#2b2620] flex flex-col font-sans">
      {/* Persistent Top Bar */}
      <TopBar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        isBackendConnected={isBackendConnected}
        onOpenSettings={() => setIsSettingsOpen(true)}
        settings={settings}
      />

      {/* Main Workspace Layout */}
      <main className="flex-1 flex overflow-hidden">
        {/* Left Panel: Source Browser (30% width, collapsible, visible in Chat & Timeline views) */}
        {(activeTab === 'chat' || activeTab === 'timeline') && (
          <SourceBrowser
            isOpen={isBrowserOpen}
            onToggleOpen={() => setIsBrowserOpen(!isBrowserOpen)}
            onAskAboutSource={handleAskAboutSource}
            selectedSourceId={selectedSourceId}
            onSelectSource={setSelectedSourceId}
          />
        )}

        {/* View 1: Chat (Default View) */}
        {activeTab === 'chat' && (
          <ChatView
            messages={messages}
            onSendMessage={handleSendMessage}
            onRetryMessage={handleRetryMessage}
            onFeedback={handleFeedback}
            onSelectSource={srcId => {
              setSelectedSourceId(srcId);
              if (!isBrowserOpen) setIsBrowserOpen(true);
            }}
            isStreaming={isStreaming}
            activeFilter={activeFilter}
            onClearFilter={() => setActiveFilter(undefined)}
            settings={settings}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onShowToast={showToast}
          />
        )}

        {/* View 2: Timeline */}
        {activeTab === 'timeline' && (
          <TimelineView
            lastMessageWithChunks={lastMessageWithChunks}
            onFilterByYear={handleFilterByYear}
            onApplyDateRange={handleApplyDateRange}
            onSelectSource={srcId => {
              setSelectedSourceId(srcId);
              if (!isBrowserOpen) setIsBrowserOpen(true);
            }}
          />
        )}

        {/* View 3: Website Time Machine */}
        {activeTab === 'timemachine' && (
          <WebsiteTimeMachineView
            onAskAboutDomain={handleAskAboutDomain}
            onShowToast={showToast}
          />
        )}

        {/* View 4: Source Explorer */}
        {activeTab === 'explorer' && (
          <SourceExplorerView
            onAskAboutSource={handleAskAboutSource}
            onSelectSourceId={setSelectedSourceId}
          />
        )}
      </main>

      {/* Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        settings={settings}
        onUpdateSettings={handleUpdateSettings}
        isBackendConnected={isBackendConnected}
        onCheckHealth={checkHealth}
        onShowToast={showToast}
      />

      {/* Toast Notification */}
      <Toast message={toastMessage} onClose={() => setToastMessage(null)} />
    </div>
  );
}
