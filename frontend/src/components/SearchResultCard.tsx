import React from 'react';
import type { SearchResult } from '../types';
import { formatLocationLabel } from '../utils/location';

interface SearchResultCardProps {
  result: SearchResult;
  onInspect: (result: SearchResult) => void;
  onOpenFolder: (result: SearchResult) => void;
}

export const SearchResultCard: React.FC<SearchResultCardProps> = ({
  result,
  onInspect,
  onOpenFolder,
}) => {
  const getFileIcon = (fileType: string) => {
    switch (fileType.toLowerCase()) {
      case 'docx':
      case 'doc':
        return (
          <div className="w-8 h-8 rounded-lg bg-brick-light/70 text-brick flex items-center justify-center flex-shrink-0">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.9" viewBox="0 0 24 24">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" x2="8" y1="13" y2="13"></line>
              <line x1="16" x2="8" y1="17" y2="17"></line>
            </svg>
          </div>
        );
      case 'pdf':
        return (
          <div className="w-8 h-8 rounded-lg bg-brick-light/70 text-brick flex items-center justify-center flex-shrink-0">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.9" viewBox="0 0 24 24">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="12" x2="12" y1="18" y2="12"></line>
              <line x1="9" x2="15" y1="15" y2="15"></line>
            </svg>
          </div>
        );
      case 'pptx':
      case 'ppt':
        return (
          <div className="w-8 h-8 rounded-lg bg-brick-light/70 text-brick flex items-center justify-center flex-shrink-0">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.9" viewBox="0 0 24 24">
              <rect height="14" rx="2" ry="2" width="20" x="2" y="3"></rect>
              <line x1="8" x2="16" y1="21" y2="21"></line>
              <line x1="12" x2="12" y1="17" y2="21"></line>
            </svg>
          </div>
        );
      case 'md':
      case 'markdown':
        return (
          <div className="w-8 h-8 rounded-lg bg-sand-200 text-cocoa flex items-center justify-center flex-shrink-0">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <polyline points="10 9 9 9 8 9"></polyline>
            </svg>
          </div>
        );
      case 'code':
      case 'py':
      case 'ts':
      case 'js':
        return (
          <div className="w-8 h-8 rounded-lg bg-sand-200 text-cocoa flex items-center justify-center flex-shrink-0 font-mono text-[11px] font-semibold">
            &lt;/&gt;
          </div>
        );
      case 'config':
      case 'toml':
      case 'yaml':
      case 'json':
        return (
          <div className="w-8 h-8 rounded-lg bg-sand-200 text-cocoa flex items-center justify-center flex-shrink-0 font-mono text-[11px] font-semibold">
            cfg
          </div>
        );
      default:
        return (
          <div className="w-8 h-8 rounded-lg bg-sand-200 text-cocoa flex items-center justify-center flex-shrink-0">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
          </div>
        );
    }
  };

  return (
    <div
      onClick={() => onInspect(result)}
      className="group relative flex items-center justify-between p-4 bg-[#FFFEFB]/85 backdrop-blur-md hover:bg-white border border-[#E3D2BE]/80 hover:border-[#9E2F2B]/60 rounded-2xl shadow-[0_4px_20px_-4px_rgba(41,37,34,0.06),0_1px_3px_rgba(41,37,34,0.03)] hover:shadow-[0_8px_30px_-6px_rgba(158,47,43,0.12),0_2px_8px_rgba(41,37,34,0.05)] hover:-translate-y-0.5 transition-all duration-200 cursor-pointer"
    >
      <div className="flex items-center gap-3.5 min-w-0 flex-1 pr-3">
        {getFileIcon(result.file_type)}

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-cocoa group-hover:text-brick transition-colors truncate">
              {result.filename}
            </span>
            <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-sand-200/70 text-cocoa">
              {formatLocationLabel(result.location_label, result.file_type)}
            </span>
          </div>
          <div className="text-[11px] text-warmgrey truncate mt-0.5">
            {result.display_path} {result.last_updated ? `· ${result.last_updated}` : ''}
          </div>
        </div>
      </div>

      <div
        className="flex items-center gap-2 flex-shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Only the authoritative backend rank is shown to users. */}
        <div className="hidden sm:flex items-center gap-1.5 mr-2.5 text-xs font-mono">
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-brick-light text-brick font-semibold border border-brick/20 shadow-xs"
            title="Backend hybrid rank (Reciprocal Rank Fusion)"
          >
            <span className="text-[10px] uppercase font-sans font-medium text-brick/80">Rank</span>
            #{result.hybrid_rank}
          </span>
        </div>

        <button
          type="button"
          aria-label={`Open ${result.filename} in file explorer`}
          onClick={() => onOpenFolder(result)}
          title="Open containing folder in file explorer"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-warmgrey hover:text-brick hover:bg-brick-light/60 border border-transparent hover:border-brick/20 transition-all focus-ring"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
          </svg>
          <span className="hidden sm:inline">Open in folder</span>
        </button>
      </div>
    </div>
  );
};
