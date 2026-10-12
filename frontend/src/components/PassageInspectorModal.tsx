import React, { useEffect, useState } from 'react';
import type { PassageDetail } from '../types';
import { formatLocationLabel } from '../utils/location';

interface PassageInspectorModalProps {
  passage: PassageDetail | null;
  query: string;
  onClose: () => void;
  onOpenFolder: (passage: PassageDetail) => void;
}

export const PassageInspectorModal: React.FC<PassageInspectorModalProps> = ({
  passage,
  query,
  onClose,
  onOpenFolder,
}) => {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    if (passage) {
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [passage, onClose]);

  if (!passage) return null;

  const handleCopy = () => {
    navigator.clipboard.writeText(passage.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Render passage text with query highlights
  const renderHighlightedText = (text: string, searchQuery: string) => {
    if (!searchQuery.trim()) return text;
    const words = searchQuery
      .trim()
      .split(/\s+/)
      .filter((w) => w.length > 2)
      .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));

    if (words.length === 0) return text;
    const regex = new RegExp(`(${words.join('|')})`, 'gi');
    const parts = text.split(regex);

    return parts.map((part, index) => {
      if (regex.test(part)) {
        return (
          <mark key={index} className="match-highlight">
            {part}
          </mark>
        );
      }
      return part;
    });
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="modalFileName"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
    >
      {/* Backdrop */}
      <div
        className="modal-backdrop fixed inset-0 transition-opacity"
        onClick={onClose}
      />

      {/* Modal Surface */}
      <div className="relative w-full max-w-2xl bg-surface border border-sand-300 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[88vh] z-10 animate-in fade-in zoom-in-95 duration-200">
        {/* Modal Header */}
        <div className="flex items-start justify-between p-5 pb-4 border-b border-sand-200 bg-sand-50/70">
          <div className="min-w-0 pr-4">
            <div className="flex items-center gap-2 mb-1">
              <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-brick-light text-brick uppercase">
                {passage.file_type}
              </span>
              <h3 id="modalFileName" className="text-base sm:text-lg font-bold text-cocoa truncate">
                {passage.filename}
              </h3>
            </div>
            <p className="text-xs text-warmgrey font-mono truncate">
              {passage.canonical_path}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            title="Close dialog (Escape)"
            className="p-1.5 rounded-lg text-warmgrey hover:text-cocoa hover:bg-sand-200 transition-colors focus-ring"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24">
              <line x1="18" x2="6" y1="6" y2="18"></line>
              <line x1="6" x2="18" y1="6" y2="18"></line>
            </svg>
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto space-y-6 text-sm text-cocoa leading-relaxed bg-[#FFFEFB]">
          {/* Metadata location badge bar */}
          <div className="flex items-center justify-between pb-3 border-b border-sand-200/70 text-xs text-warmgrey flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <svg className="w-3.5 h-3.5 text-brick" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                <circle cx="12" cy="10" r="3"></circle>
              </svg>
              <span className="font-medium text-cocoa">
                {formatLocationLabel(passage.location_label, passage.file_type)}
              </span>
            </div>
          </div>

          {/* Preceding context if available */}
          {passage.surrounding_context_before && (
            <div className="space-y-1">
              <span className="text-[11px] font-mono text-warmgrey uppercase tracking-wider font-semibold">
                Context Before
              </span>
              <div className="p-3 rounded-lg bg-sand-100/50 border border-sand-200/50 font-mono text-xs text-warmgrey/90 leading-relaxed whitespace-pre-wrap select-text">
                {passage.surrounding_context_before}
              </div>
            </div>
          )}

          {/* Matched Passage Text */}
          <div className="space-y-1">
            <span className="text-[11px] font-mono text-brick uppercase tracking-wider font-semibold">
              Matched Passage
            </span>
            <div className="p-4 rounded-xl bg-sand-50/80 border border-sand-300 font-mono text-[13px] leading-relaxed whitespace-pre-wrap select-text text-[#292522] shadow-xs">
              {renderHighlightedText(passage.text, query)}
            </div>
          </div>

          {/* Succeeding context if available */}
          {passage.surrounding_context_after && (
            <div className="space-y-1">
              <span className="text-[11px] font-mono text-warmgrey uppercase tracking-wider font-semibold">
                Context After
              </span>
              <div className="p-3 rounded-lg bg-sand-100/50 border border-sand-200/50 font-mono text-xs text-warmgrey/90 leading-relaxed whitespace-pre-wrap select-text">
                {passage.surrounding_context_after}
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-between p-4 px-6 border-t border-sand-200 bg-sand-50/50">
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-cocoa bg-sand-200/70 hover:bg-sand-200 border border-sand-300/60 transition-colors focus-ring"
          >
            <span className="material-symbols-outlined text-[16px]">
              {copied ? 'check' : 'content_copy'}
            </span>
            {copied ? 'Copied' : 'Copy passage'}
          </button>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onOpenFolder(passage)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white bg-brick hover:bg-[#852522] transition-colors shadow-sm focus-ring"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
              </svg>
              Open containing folder
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg text-xs font-medium text-warmgrey hover:text-cocoa hover:bg-sand-200 transition-colors"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
