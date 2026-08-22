import React from 'react';
import { CheckCircle, Info } from 'lucide-react';

interface ToastProps {
  message: string | null;
  onClose: () => void;
}

export const Toast: React.FC<ToastProps> = ({ message }) => {
  if (!message) return null;

  return (
    <div className="fixed bottom-6 right-6 z-50 bg-[#2b2620] text-[#fffdf7] px-4 py-2.5 rounded-lg shadow-xl border border-[#d8cfb8]/30 flex items-center gap-2 text-xs animate-in fade-in slide-in-from-bottom-2 duration-200 font-sans">
      <CheckCircle className="w-4 h-4 text-[#3f6b3f]" />
      <span>{message}</span>
    </div>
  );
};
