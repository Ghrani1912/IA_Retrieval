import React, { useState } from 'react';
import { X, SlidersHorizontal, Check, RefreshCw, Server, ShieldCheck, Zap } from 'lucide-react';
import { AppSettings } from '../types';
import { HistoricalApiService } from '../services/api';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  settings: AppSettings;
  onUpdateSettings: (newSettings: Partial<AppSettings>) => void;
  isBackendConnected: boolean;
  onCheckHealth: () => void;
  onShowToast: (msg: string) => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  settings,
  onUpdateSettings,
  isBackendConnected,
  onCheckHealth,
  onShowToast
}) => {
  const [urlInput, setUrlInput] = useState(settings.backendUrl);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  if (!isOpen) return null;

  const handleSaveUrl = () => {
    HistoricalApiService.setBackendUrl(urlInput);
    onUpdateSettings({ backendUrl: urlInput });
    onShowToast('Backend URL updated.');
  };

  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestResult(null);
    HistoricalApiService.setBackendUrl(urlInput);

    const health = await HistoricalApiService.checkHealth();
    setIsTesting(false);
    if (health.isOnline) {
      setTestResult({ ok: true, message: 'Successfully connected to backend API (/health).' });
      onCheckHealth();
    } else {
      setTestResult({
        ok: false,
        message: `Offline at ${urlInput}. Active fallback archival engine is engaging automatically.`
      });
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#2b2620]/40 backdrop-blur-xs flex items-center justify-center p-4 select-none">
      <div className="bg-[#fffdf7] border border-[#d8cfb8] rounded-2xl max-w-md w-full p-5 sm:p-6 shadow-2xl space-y-5 animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#d8cfb8] pb-3">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="w-4 h-4 text-[#8b3a1f]" />
            <h3 className="font-serif-heading font-bold text-base text-[#2b2620]">
              Assistant Settings
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-[#6b6252] hover:text-[#2b2620] hover:bg-[#f5f0e6]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Toggles */}
        <div className="space-y-4 text-xs">
          {/* Toggle 1: Show citation confidence */}
          <div className="flex items-center justify-between gap-3 p-3 bg-[#f5f0e6]/60 rounded-xl border border-[#d8cfb8]/70">
            <div className="flex items-start gap-2.5">
              <ShieldCheck className="w-4 h-4 text-[#3f6b3f] shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold text-[#2b2620] block">
                  Show citation confidence
                </span>
                <span className="text-[11px] text-[#6b6252]">
                  Displays directly verified vs inferred confidence breakdown bar
                </span>
              </div>
            </div>

            <button
              onClick={() => onUpdateSettings({ showCitationConfidence: !settings.showCitationConfidence })}
              className={`w-10 h-5 rounded-full transition-colors relative cursor-pointer ${
                settings.showCitationConfidence ? 'bg-[#8b3a1f]' : 'bg-[#d8cfb8]'
              }`}
            >
              <span
                className={`w-3.5 h-3.5 rounded-full bg-[#fffdf7] absolute top-0.5 transition-transform ${
                  settings.showCitationConfidence ? 'left-5.5' : 'left-1'
                }`}
              />
            </button>
          </div>

          {/* Toggle 2: Stream answers */}
          <div className="flex items-center justify-between gap-3 p-3 bg-[#f5f0e6]/60 rounded-xl border border-[#d8cfb8]/70">
            <div className="flex items-start gap-2.5">
              <Zap className="w-4 h-4 text-[#a67c1e] shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold text-[#2b2620] block">
                  Stream answers
                </span>
                <span className="text-[11px] text-[#6b6252]">
                  Receive tokens incrementally via SSE (if off, waits for full response)
                </span>
              </div>
            </div>

            <button
              onClick={() => onUpdateSettings({ streamAnswers: !settings.streamAnswers })}
              className={`w-10 h-5 rounded-full transition-colors relative cursor-pointer ${
                settings.streamAnswers ? 'bg-[#8b3a1f]' : 'bg-[#d8cfb8]'
              }`}
            >
              <span
                className={`w-3.5 h-3.5 rounded-full bg-[#fffdf7] absolute top-0.5 transition-transform ${
                  settings.streamAnswers ? 'left-5.5' : 'left-1'
                }`}
              />
            </button>
          </div>

          {/* API Backend Status & URL Config */}
          <div className="p-3 bg-[#f5f0e6]/60 rounded-xl border border-[#d8cfb8]/70 space-y-2.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Server className="w-4 h-4 text-[#8b3a1f]" />
                <span className="font-semibold text-[#2b2620]">
                  Backend API Connection
                </span>
              </div>
              <div className="flex items-center gap-1.5 font-mono text-[11px]">
                <span
                  className={`w-2 h-2 rounded-full ${
                    isBackendConnected ? 'bg-[#3f6b3f]' : 'bg-[#a13a2f]'
                  }`}
                />
                <span className={isBackendConnected ? 'text-[#3f6b3f] font-bold' : 'text-[#a13a2f]'}>
                  {isBackendConnected ? 'Connected' : 'Offline (Integrated Mode)'}
                </span>
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] uppercase font-semibold text-[#6b6252] block font-mono">
                FastAPI Server URL
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={urlInput}
                  onChange={e => setUrlInput(e.target.value)}
                  placeholder="http://localhost:8000"
                  className="flex-1 px-2.5 py-1.5 bg-[#fffdf7] border border-[#d8cfb8] rounded-lg text-[#2b2620] font-mono text-xs focus:outline-none focus:border-[#8b3a1f]"
                />
                <button
                  onClick={handleSaveUrl}
                  className="px-2.5 py-1.5 bg-[#f5f0e6] border border-[#d8cfb8] text-[#2b2620] rounded-lg hover:bg-[#fffdf7] text-xs"
                >
                  Save
                </button>
              </div>
            </div>

            <div className="pt-1 flex items-center justify-between">
              <button
                onClick={handleTestConnection}
                disabled={isTesting}
                className="flex items-center gap-1 text-[11px] text-[#8b3a1f] font-semibold hover:underline"
              >
                {isTesting ? (
                  <RefreshCw className="w-3 h-3 animate-spin" />
                ) : (
                  <RefreshCw className="w-3 h-3" />
                )}
                <span>Test Connection</span>
              </button>

              <span className="text-[10px] text-[#6b6252] font-mono">
                Status via GET /health
              </span>
            </div>

            {testResult && (
              <div
                className={`p-2 rounded text-[11px] font-mono ${
                  testResult.ok
                    ? 'bg-[#3f6b3f]/10 text-[#3f6b3f] border border-[#3f6b3f]/30'
                    : 'bg-[#a13a2f]/10 text-[#a13a2f] border border-[#a13a2f]/30'
                }`}
              >
                {testResult.message}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="pt-2 border-t border-[#d8cfb8] flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-[#8b3a1f] text-[#fffdf7] rounded-lg text-xs font-semibold hover:bg-[#6f2e17] transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
