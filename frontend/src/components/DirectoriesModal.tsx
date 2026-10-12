/* oxlint-disable react/set-state-in-effect -- sync refresh is intentional after backend jobs complete. */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import type { IndexedDirectory, TrackedDocument, SyncJob } from '../types';
import { pickNativeFolder, getDirectoryDocuments } from '../services/api';

interface DirectoriesModalProps {
  isOpen: boolean;
  onClose: () => void;
  directories: IndexedDirectory[];
  onAddDirectory: (path: string) => void;
  onSyncDirectory: (directoryId: string) => void;
  onSyncAll: () => void;
  onRemoveDirectory: (directoryId: string) => void;
  activeJob: SyncJob | null;
}

export const DirectoriesModal: React.FC<DirectoriesModalProps> = ({
  isOpen,
  onClose,
  directories,
  onAddDirectory,
  onSyncDirectory,
  onSyncAll,
  onRemoveDirectory,
  activeJob,
}) => {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [newPathInput, setNewPathInput] = useState('');
  const [showManualInput, setShowManualInput] = useState(false);
  const [expandedDirectoryId, setExpandedDirectoryId] = useState<string | null>(null);
  const [directoryDocs, setDirectoryDocs] = useState<Record<string, TrackedDocument[]>>({});
  const [loadingDocsId, setLoadingDocsId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadDocumentsForDirectory = useCallback(async (dirId: string) => {
    setLoadingDocsId(dirId);
    try {
      const docs = await getDirectoryDocuments(dirId);
      setDirectoryDocs((prev) => ({ ...prev, [dirId]: docs }));
    } catch (err) {
      console.warn('Failed to fetch documents for directory', dirId, err);
    } finally {
      setLoadingDocsId(null);
    }
  }, []);

  // Re-fetch documents for the expanded directory when an active sync completes
  useEffect(() => {
    if (isOpen && expandedDirectoryId && !activeJob) {
      // oxlint-disable-next-line react(set-state-in-effect)
      loadDocumentsForDirectory(expandedDirectoryId);
    }
  }, [isOpen, expandedDirectoryId, activeJob, loadDocumentsForDirectory]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const safeDirectories = Array.isArray(directories) ? directories : [];
  const totalFolders = safeDirectories.length;
  const totalFiles = safeDirectories.reduce((acc, d) => acc + (d?.file_count || 0), 0);

  // File Explorer directory selection
  const handleBrowseFolder = async () => {
    // 1. Try host backend native folder picker (system dialog)
    try {
      const nativeResult = await pickNativeFolder();
      if (nativeResult.selected && nativeResult.path) {
        onAddDirectory(nativeResult.path);
        return;
      }
      if (nativeResult.selected === false) {
        return; // User cancelled
      }
    } catch {
      // Backend offline or pick endpoint unavailable; fallback
    }

    // 2. Try modern File System Access API
    if ('showDirectoryPicker' in window) {
      try {
        const picker = (window as unknown as { showDirectoryPicker: () => Promise<{ name: string }> }).showDirectoryPicker;
        const handle = await picker();
        if (handle && handle.name) {
          onAddDirectory(handle.name);
          return;
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name === 'AbortError') return;
      }
    }

    // 3. Fallback to HTML5 directory picker
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      const relPath = files[0].webkitRelativePath;
      const folderName = relPath ? relPath.split('/')[0] : files[0].name;
      onAddDirectory(folderName);
    }
    if (e.target) e.target.value = '';
  };

  const handleManualSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newPathInput.trim()) {
      onAddDirectory(newPathInput.trim());
      setNewPathInput('');
      setShowManualInput(false);
    }
  };

  const handleToggleExpand = (dirId: string) => {
    if (expandedDirectoryId === dirId) {
      setExpandedDirectoryId(null);
    } else {
      setExpandedDirectoryId(dirId);
      loadDocumentsForDirectory(dirId);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="directoriesModalTitle"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
    >
      {/* Backdrop */}
      <div
        className="modal-backdrop fixed inset-0 transition-opacity"
        onClick={onClose}
      />

      {/* Hidden file input for native folder picker */}
      <input
        ref={fileInputRef}
        type="file"
        // @ts-expect-error webkitdirectory is a standard non-standard attribute supported in all modern browsers
        webkitdirectory=""
        directory=""
        multiple
        onChange={handleFileInputChange}
        className="hidden"
      />

      {/* Modal Surface */}
      <div className="relative w-full max-w-[820px] bg-[#FFFEFB] border border-[#E3D2BE] rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[88vh] z-10 transition-all duration-200">
        {/* Header */}
        <div className="px-6 pt-5 pb-4 border-b border-[#E3D2BE]/60 flex items-start justify-between gap-4 bg-[#FFFEFB] shrink-0">
          <div className="space-y-1">
            <div className="flex items-center gap-2.5">
              <span className="material-symbols-outlined text-[24px] text-[#9E2F2B]">folder_managed</span>
              <h2 id="directoriesModalTitle" className="font-headline-section text-[20px] font-semibold text-[#292522] tracking-tight">
                Indexed directories
              </h2>
            </div>
            <p className="font-body-sm text-[13px] text-[#77716B]">
              Manage your folders and keep your index up to date.
            </p>
          </div>
          <div className="flex items-center gap-2.5 shrink-0">
            <button
              type="button"
              onClick={onSyncAll}
              className="bg-[#9E2F2B] hover:bg-[#852522] active:scale-95 text-white rounded-xl px-3.5 py-2 text-xs font-medium inline-flex items-center gap-1.5 shadow-sm transition-all focus-ring"
            >
              <span className={`material-symbols-outlined text-[16px] ${activeJob?.job_type === 'SYNC_ALL' ? 'animate-spin' : ''}`}>
                sync
              </span>
              <span>Sync all</span>
            </button>
            <button
              type="button"
              aria-label="Close dialog"
              onClick={onClose}
              className="p-1.5 text-[#77716B] hover:text-[#292522] hover:bg-[#EDE3D4]/50 rounded-lg transition-colors focus-ring"
            >
              <span className="material-symbols-outlined text-[20px]">close</span>
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-5 overflow-y-auto flex-1 bg-[#FFFEFB]">
          {/* Statistics Boxes */}
          <div className="grid grid-cols-2 gap-3.5">
            <div className="p-3.5 rounded-xl bg-[#F8F4EC]/90 border border-[#E3D2BE]/70 flex items-center justify-between">
              <div>
                <span className="text-[11px] font-medium uppercase tracking-wider text-[#77716B]">Folders indexed</span>
                <div className="text-[22px] font-bold text-[#292522] mt-0.5">{totalFolders}</div>
              </div>
              <div className="w-9 h-9 rounded-lg bg-[#EDE3D4] flex items-center justify-center text-[#9E2F2B]">
                <span className="material-symbols-outlined text-[20px]">folder</span>
              </div>
            </div>
            <div className="p-3.5 rounded-xl bg-[#F8F4EC]/90 border border-[#E3D2BE]/70 flex items-center justify-between">
              <div>
                <span className="text-[11px] font-medium uppercase tracking-wider text-[#77716B]">Files indexed</span>
                <div className="text-[22px] font-bold text-[#292522] mt-0.5">{totalFiles.toLocaleString()}</div>
              </div>
              <div className="w-9 h-9 rounded-lg bg-[#EDE3D4] flex items-center justify-center text-[#9E2F2B]">
                <span className="material-symbols-outlined text-[20px]">description</span>
              </div>
            </div>
          </div>

          {/* Global Sync-All Progress Banner — Appears ONLY for 'SYNC_ALL' */}
          {activeJob && activeJob.job_type === 'SYNC_ALL' && (
            <div className="p-4 rounded-xl bg-[#F8F4EC] border border-[#9E2F2B]/30 relative overflow-hidden transition-all animate-in fade-in duration-200">
              <div className="flex items-start justify-between gap-3 mb-2.5">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-[#9E2F2B] text-[20px] animate-spin">sync</span>
                  <div>
                    <h4 className="text-[13px] font-semibold text-[#292522]">Overall sync progress</h4>
                    <p className="text-[12px] text-[#77716B]">{activeJob?.stage || 'Syncing'}: {activeJob?.current_file_or_desc || 'Scanning all registered folders...'}</p>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#9E2F2B]/10 text-[#9E2F2B] border border-[#9E2F2B]/20">
                  {Math.round(activeJob?.progress_percent || 0)}%
                </span>
              </div>
              <div className="w-full bg-[#E5D7C7] h-2 rounded-full overflow-hidden mb-2">
                <div
                  className="bg-[#9E2F2B] h-full rounded-full transition-all duration-300"
                  style={{ width: `${Math.max(5, activeJob?.progress_percent || 0)}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[11px] text-[#77716B]">
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#9E2F2B] animate-ping" />
                  Processed {activeJob?.files_processed ?? 0} of {activeJob?.files_discovered ?? 0} files ({activeJob?.passages_created ?? 0} passages)
                </span>
              </div>
            </div>
          )}

          {/* Directory Rows */}
          <div className="space-y-2.5">
            {safeDirectories.length === 0 ? (
              <div className="py-6 px-4 text-center rounded-xl bg-[#F8F4EC]/50 border border-dashed border-[#E3D2BE]">
                <span className="material-symbols-outlined text-[28px] text-[#77716B]/60 mb-1">folder_off</span>
                <p className="text-xs font-medium text-[#292522]">No directories indexed yet</p>
                <p className="text-[11px] text-[#77716B] mt-0.5">Use the buttons below to choose a folder on your computer.</p>
              </div>
            ) : (
              safeDirectories.map((dir) => {
                const isSyncingThisDir = Boolean(activeJob && activeJob.directory_id === dir.directory_id);

                return (
                  <div
                    key={dir.directory_id}
                    className={`p-3.5 rounded-xl bg-[#F8F4EC]/60 border transition-all flex flex-col gap-2.5 ${
                      isSyncingThisDir
                        ? 'border-[#9E2F2B]/50 bg-[#F8F4EC]'
                        : 'border-[#E3D2BE]/60 hover:border-[#9E2F2B]/40'
                    }`}
                  >
                    {/* Top directory item row */}
                    <div className="flex items-center justify-between gap-3 w-full">
                    <div
                      onClick={() => handleToggleExpand(dir.directory_id)}
                      className="flex items-center gap-3 min-w-0 flex-1 cursor-pointer group select-none"
                      title={expandedDirectoryId === dir.directory_id ? "Click to hide files" : "Click to view files"}
                    >
                      <div className="w-8 h-8 rounded-lg bg-[#EDE3D4] group-hover:bg-[#E3D2BE] flex items-center justify-center text-[#9E2F2B] shrink-0 transition-colors">
                        <span className="material-symbols-outlined text-[18px]">
                          {expandedDirectoryId === dir.directory_id ? 'folder_open' : 'folder'}
                        </span>
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <h4 className="text-sm font-semibold text-[#292522] group-hover:text-[#9E2F2B] transition-colors truncate">
                            {dir.display_name}
                          </h4>
                          <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-[#EDE3D4] text-[#77716B]">
                            {dir.file_count} files
                          </span>
                        </div>
                        <p className="text-xs text-[#77716B] font-mono truncate">{dir.canonical_path}</p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => handleToggleExpand(dir.directory_id)}
                        title={expandedDirectoryId === dir.directory_id ? "Hide files" : "Show indexed files"}
                        className="px-2 py-1 rounded-lg text-xs text-[#77716B] hover:text-[#9E2F2B] hover:bg-[#EDE3D4] transition-colors focus-ring inline-flex items-center gap-1"
                      >
                        <span className="material-symbols-outlined text-[16px]">
                          {expandedDirectoryId === dir.directory_id ? 'expand_less' : 'expand_more'}
                        </span>
                        <span className="hidden sm:inline font-sans text-[11px]">
                          {expandedDirectoryId === dir.directory_id ? 'Hide files' : 'View files'}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => onSyncDirectory(dir.directory_id)}
                        title="Sync folder"
                        disabled={isSyncingThisDir}
                        className="p-1.5 rounded-lg text-[#77716B] hover:text-[#9E2F2B] hover:bg-[#EDE3D4] transition-colors focus-ring disabled:opacity-50"
                      >
                        <span className={`material-symbols-outlined text-[18px] ${isSyncingThisDir ? 'animate-spin text-[#9E2F2B]' : ''}`}>
                          refresh
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDeleteId(confirmDeleteId === dir.directory_id ? null : dir.directory_id);
                        }}
                        title="Remove from index"
                        className={`p-1.5 rounded-lg transition-colors focus-ring ${
                          confirmDeleteId === dir.directory_id
                            ? 'text-white bg-[#BA1A1A]'
                            : 'text-[#77716B] hover:text-[#ba1a1a] hover:bg-[#ffdad6]/50'
                        }`}
                      >
                        <span className="material-symbols-outlined text-[18px]">delete</span>
                      </button>
                    </div>
                  </div>

                  {/* Inline Deletion Confirmation Panel */}
                  {confirmDeleteId === dir.directory_id && (
                    <div className="p-3 rounded-xl bg-[#FFDAD6]/60 border border-[#BA1A1A]/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 animate-in fade-in duration-200">
                      <div className="flex items-center gap-2 text-xs text-[#292522]">
                        <span className="material-symbols-outlined text-[18px] text-[#BA1A1A] shrink-0">warning</span>
                        <span>
                          Remove <strong>{dir.display_name}</strong> from search index? <span className="text-[#77716B]">Source files on disk remain untouched.</span>
                        </span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0 self-end sm:self-auto">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteId(null);
                          }}
                          className="px-2.5 py-1 text-xs text-[#77716B] hover:text-[#292522] rounded-lg hover:bg-black/5 transition-colors"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onRemoveDirectory(dir.directory_id);
                            setConfirmDeleteId(null);
                          }}
                          className="px-3 py-1 text-xs font-semibold text-white bg-[#BA1A1A] hover:bg-[#93000A] active:scale-95 rounded-lg shadow-xs transition-all"
                        >
                          Remove from index
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Expanded Files Inspection Accordion */}
                  {expandedDirectoryId === dir.directory_id && (
                    <div className="mt-2 pt-2.5 border-t border-[#E3D2BE]/60 w-full animate-in fade-in duration-200">
                      <div className="flex items-center justify-between pb-2 text-[11px] text-[#77716B] font-medium border-b border-[#E3D2BE]/40">
                        <span>Tracked files ({directoryDocs[dir.directory_id]?.length ?? dir.file_count})</span>
                        {loadingDocsId === dir.directory_id && (
                          <span className="flex items-center gap-1 text-[#9E2F2B]">
                            <span className="material-symbols-outlined text-[13px] animate-spin">progress_activity</span>
                            Loading...
                          </span>
                        )}
                      </div>

                      {directoryDocs[dir.directory_id] && directoryDocs[dir.directory_id].length > 0 ? (
                        <div className="max-h-60 overflow-y-auto divide-y divide-[#E3D2BE]/30 pr-1">
                          {directoryDocs[dir.directory_id].map((doc) => {
                            let statusBadge = (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#85A37A]/20 text-[#2E5E20] border border-[#85A37A]/30">
                                Indexed ({doc.passage_count} {doc.passage_count === 1 ? 'passage' : 'passages'})
                              </span>
                            );

                            if (doc.extraction_status === 'ERROR') {
                              statusBadge = (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#ffdad6] text-[#ba1a1a] border border-[#ffb4ab]">
                                  Failed / Locked
                                </span>
                              );
                            } else if (doc.extraction_status === 'SKIPPED_TOO_LARGE') {
                              statusBadge = (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#ffedd5] text-[#9a3412] border border-[#fed7aa]">
                                  Skipped (&gt;50MB)
                                </span>
                              );
                            } else if (doc.extraction_status === 'NO_TEXT') {
                              statusBadge = (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#EDE3D4] text-[#77716B]">
                                  No text layer
                                </span>
                              );
                            } else if (doc.extraction_status === 'PENDING') {
                              statusBadge = (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#fef3c7] text-[#92400e] border border-[#fde68a]">
                                  Pending sync
                                </span>
                              );
                            }

                            return (
                              <div key={doc.document_id} className="py-1.5 flex items-center justify-between gap-2 text-xs">
                                <div className="flex items-center gap-2 min-w-0 flex-1">
                                  <span className="material-symbols-outlined text-[15px] text-[#77716B] shrink-0">
                                    {doc.extension?.toLowerCase() === '.pdf' ? 'picture_as_pdf' :
                                     doc.extension?.toLowerCase() === '.pptx' ? 'slideshow' :
                                     doc.extension?.toLowerCase() === '.docx' ? 'description' :
                                     doc.extension?.toLowerCase() === '.py' ? 'code' : 'article'}
                                  </span>
                                  <span className="truncate text-[#292522] font-mono text-[11px]" title={doc.canonical_path}>
                                    {doc.filename}
                                  </span>
                                </div>
                                <div className="flex items-center gap-2 shrink-0">
                                  <span className="text-[10px] text-[#77716B] font-mono">
                                    {(doc.size_bytes ?? 0) > 1048576
                                      ? `${((doc.size_bytes ?? 0) / 1048576).toFixed(1)} MB`
                                      : `${Math.round((doc.size_bytes ?? 0) / 1024)} KB`}
                                  </span>
                                  {statusBadge}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      ) : !loadingDocsId ? (
                        <p className="text-xs text-[#77716B] py-2 italic text-center">
                          No documents discovered yet in this directory.
                        </p>
                      ) : null}
                    </div>
                  )}

                  {/* Individual Folder Sync Load Bar — Appears directly below this specific folder */}
                  {isSyncingThisDir && activeJob && (
                    <div className="pt-2.5 border-t border-[#E3D2BE]/60 w-full animate-in fade-in duration-200">
                      <div className="flex items-center justify-between text-xs mb-1.5">
                        <span className="flex items-center gap-1.5 text-[#77716B]">
                          <span className="material-symbols-outlined text-[15px] text-[#9E2F2B] animate-spin">sync</span>
                          <span className="font-semibold text-[#292522]">{activeJob.stage || 'Syncing'}:</span>
                          <span>{activeJob.current_file_or_desc || 'Scanning files...'}</span>
                        </span>
                        <span className="font-mono text-[11px] font-semibold text-[#9E2F2B] bg-[#9E2F2B]/10 px-2 py-0.5 rounded-full border border-[#9E2F2B]/20">
                          {Math.round(activeJob.progress_percent || 0)}%
                        </span>
                      </div>
                      <div className="w-full bg-[#E5D7C7] h-1.5 rounded-full overflow-hidden mb-1.5">
                        <div
                          className="bg-[#9E2F2B] h-full rounded-full transition-all duration-300"
                          style={{ width: `${Math.max(5, activeJob.progress_percent || 0)}%` }}
                        />
                      </div>
                      <div className="flex items-center justify-between text-[11px] text-[#77716B]">
                        <span>Processed {activeJob.files_processed ?? 0} of {activeJob.files_discovered ?? 0} files</span>
                        <span>{activeJob.passages_created ?? 0} passages created</span>
                      </div>
                    </div>
                  )}
                </div>
              );
            }))}
          </div>

          {/* Add Directory Section */}
          <div className="space-y-2.5">
            {showManualInput ? (
              <form onSubmit={handleManualSubmit} className="p-3.5 rounded-xl border border-[#9E2F2B]/40 bg-[#F8F4EC]/80 space-y-2 animate-in fade-in">
                <label className="block text-xs font-medium text-[#292522]">Enter directory path to index:</label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    autoFocus
                    value={newPathInput}
                    onChange={(e) => setNewPathInput(e.target.value)}
                    placeholder="/Users/you/Documents/Notes or C:/Users/..."
                    className="flex-1 px-3 py-1.5 text-xs bg-white border border-[#E3D2BE] rounded-lg focus:outline-none focus:border-[#9E2F2B]"
                  />
                  <button
                    type="submit"
                    className="px-3 py-1.5 text-xs font-medium text-white bg-[#9E2F2B] hover:bg-[#852522] rounded-lg transition-colors"
                  >
                    Register
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowManualInput(false)}
                    className="px-3 py-1.5 text-xs text-[#77716B] hover:text-[#292522]"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {/* 1. File Explorer native selection button */}
                <button
                  type="button"
                  onClick={handleBrowseFolder}
                  className="py-2.5 px-4 bg-surface hover:bg-[#FAF6F0] border border-[#9E2F2B]/40 hover:border-[#9E2F2B] rounded-xl text-xs font-medium text-[#9E2F2B] flex items-center justify-center gap-2 transition-all shadow-xs active:scale-98"
                >
                  <span className="material-symbols-outlined text-[18px]">folder_open</span>
                  <span>Select Folder via File Explorer</span>
                </button>

                {/* 2. Manual path entry button */}
                <button
                  type="button"
                  onClick={() => setShowManualInput(true)}
                  className="py-2.5 px-4 border border-dashed border-[#E3D2BE] hover:border-[#9E2F2B] rounded-xl text-xs font-medium text-[#77716B] hover:text-[#9E2F2B] flex items-center justify-center gap-2 transition-colors"
                >
                  <span className="material-symbols-outlined text-[16px]">edit_note</span>
                  <span>Enter path manually</span>
                </button>
              </div>
            )}
          </div>

          {/* Immutability Assurance Notice */}
          <div className="pt-2 text-center text-[11px] text-[#77716B] border-t border-[#E3D2BE]/40">
            <span className="inline-flex items-center gap-1">
              <span className="material-symbols-outlined text-[13px] text-[#9E2F2B]">verified_user</span>
              Removing a directory only clears internal search index records. Original files are never modified or deleted.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
