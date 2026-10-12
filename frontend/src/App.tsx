import React, { useState, useEffect, useRef } from 'react';
import { TerracottaCanvas } from './components/TerracottaCanvas';
import { SearchResultCard } from './components/SearchResultCard';
import { PassageInspectorModal } from './components/PassageInspectorModal';
import { DirectoriesModal } from './components/DirectoriesModal';
import { ErrorBoundary } from './components/ErrorBoundary';
import type { SearchResult, PassageDetail, IndexedDirectory, SyncJob } from './types';
import {
  searchPassages,
  getPassageDetail,
  getIndexedDirectories,
  registerDirectory,
  deleteDirectory,
  syncDirectory,
  syncAllDirectories,
  getJobStatus,
  getSyncStatus,
  openContainingFolder,
} from './services/api';

export function App() {
  const [viewState, setViewState] = useState<'hero' | 'results'>('hero');
  const [queryInput, setQueryInput] = useState('');
  const [activeQuery, setActiveQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [totalAvailable, setTotalAvailable] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [pulseCount, setPulseCount] = useState(0);

  // Popover & Modal States
  const [foldersModalOpen, setFoldersModalOpen] = useState(false);
  const [selectedPassage, setSelectedPassage] = useState<PassageDetail | null>(null);

  // Directories & Sync state
  const [directories, setDirectories] = useState<IndexedDirectory[]>([]);
  const [activeJob, setActiveJob] = useState<SyncJob | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const searchInputRef = useRef<HTMLInputElement | null>(null);

  const totalFilesIndexed = directories.reduce((acc, d) => acc + (d?.file_count || 0), 0);

  // Load directories on mount
  useEffect(() => {
    getIndexedDirectories().then((dirs) => setDirectories(dirs));
  }, []);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const executeSearch = async (
    searchTerm: string
  ) => {
    if (!searchTerm.trim()) return;

    setPulseCount((c) => c + 1);
    setIsLoading(true);
    setActiveQuery(searchTerm.trim());
    setViewState('results');

    try {
      const data = await searchPassages(searchTerm.trim(), 20, 0);
      setResults(data.results);
      setTotalAvailable(data.total_available);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Search failed';
      showToast(message);
    } finally {
      setIsLoading(false);
    }
  };


  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    executeSearch(queryInput);
  };

  const handleClear = () => {
    setQueryInput('');
    if (searchInputRef.current) {
      searchInputRef.current.focus();
    }
  };

  const handleInspectPassage = async (item: SearchResult) => {
    try {
      const detail = await getPassageDetail(item.chunk_id);
      setSelectedPassage(detail);
    } catch {
      // Fallback: construct detail from search result item
      setSelectedPassage({
        chunk_id: item.chunk_id,
        document_id: item.document_id,
        filename: item.filename,
        display_path: item.display_path,
        canonical_path: item.canonical_path,
        file_type: item.file_type,
        location_label: item.location_label,
        text: item.passage_preview,
        hybrid_rank: item.hybrid_rank,
        semantic_rank: item.semantic_rank,
        lexical_rank: item.lexical_rank,
      });
    }
  };

  const handleOpenFolder = async (item: SearchResult | PassageDetail) => {
    try {
      const targetPath = item.canonical_path || item.document_id;
      await openContainingFolder(targetPath);
      showToast(`Revealed file in native folder: ${item.filename}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Could not launch file explorer';
      showToast(`Error: ${msg}`);
    }
  };

  // Sync operations with real background job polling
  const handleSyncDirectory = async (dirId: string) => {
    const target = directories.find((d) => d.directory_id === dirId);
    if (!target) return;

    try {
      const res = await syncDirectory(dirId);
      const jobId = res.job_id;

      // Set initial state
      setActiveJob({
        job_id: jobId,
        directory_id: dirId,
        job_type: 'SYNC_DIRECTORY',
        status: 'RUNNING',
        stage: 'Scanning files',
        progress_percent: 5,
        files_discovered: target.file_count,
        files_processed: 0,
        passages_created: 0,
        current_file_or_desc: `Scanning ${target.display_name}...`,
      });

      // Poll until job completes
      const pollTimer = setInterval(async () => {
        try {
          const job = await getJobStatus(jobId);
          if (!job) return;

          if (job.status === 'COMPLETED') {
            clearInterval(pollTimer);
            setActiveJob(null);
            showToast(`Sync completed for ${target.display_name} (${job.files_processed} files, ${job.passages_created} passages).`);
            const updatedDirs = await getIndexedDirectories();
            setDirectories(updatedDirs);
          } else if (job.status === 'FAILED') {
            clearInterval(pollTimer);
            setActiveJob(null);
            showToast(`Sync failed: ${job.error_summary || 'Unknown error'}`);
            const updatedDirs = await getIndexedDirectories();
            setDirectories(updatedDirs);
          } else {
            setActiveJob(job);
          }
        } catch {
          // Keep polling on transient network hiccups
        }
      }, 500);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to trigger directory sync';
      showToast(`Error: ${msg}`);
      setActiveJob(null);
    }
  };

  const handleSyncAll = async () => {
    try {
      const res = await syncAllDirectories();
      if (!res.jobs || res.jobs.length === 0) {
        showToast('No registered directories found to sync.');
        return;
      }

      showToast(`Enqueued sync across ${res.jobs.length} directories.`);
      const firstJobId = res.jobs[0].job_id;

      setActiveJob({
        job_id: firstJobId,
        job_type: 'SYNC_ALL',
        status: 'RUNNING',
        stage: 'Scanning all directories',
        progress_percent: 5,
        files_discovered: 0,
        files_processed: 0,
        passages_created: 0,
        current_file_or_desc: `Indexing across ${res.jobs.length} registered folders...`,
      });

      // Poll sync jobs until all complete
      const pollTimer = setInterval(async () => {
        try {
          const jobs = await getSyncStatus();
          const running = jobs.filter((j) => j.status === 'RUNNING' || j.status === 'QUEUED');

          if (running.length === 0) {
            clearInterval(pollTimer);
            setActiveJob(null);
            showToast(`All ${directories.length} directories successfully synchronized.`);
            const updatedDirs = await getIndexedDirectories();
            setDirectories(updatedDirs);
          } else {
            // Display currently running job in progress bar
            setActiveJob(running[0]);
          }
        } catch {
          // Keep polling
        }
      }, 600);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to trigger sync-all';
      showToast(`Error: ${msg}`);
      setActiveJob(null);
    }
  };

  const handleAddDirectory = async (path: string) => {
    try {
      const res = await registerDirectory(path);
      showToast(`Registered: ${res.directory.display_name} (${res.directory.file_count} files)`);
      const updatedDirs = await getIndexedDirectories();
      setDirectories(updatedDirs);

      // Trigger automatic sync for the newly added folder
      handleSyncDirectory(res.directory.directory_id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Registration failed';
      showToast(`Registration error: ${msg}`);
    }
  };

  const handleRemoveDirectory = async (dirId: string) => {
    try {
      const res = await deleteDirectory(dirId);
      setDirectories((prev) => prev.filter((d) => d.directory_id !== dirId));
      showToast(res.message || 'Directory removed. Original files are untouched.');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to delete directory';
      showToast(`Error: ${msg}`);
    }
  };

  return (
    <div className="relative flex flex-col min-h-screen bg-surface-canvas text-text-primary overflow-x-hidden selection:bg-brick-light selection:text-[#7D231F]">
      {/* Topographic Labyrinth Canvas Background */}
      <TerracottaCanvas isSearching={isLoading} pulseTrigger={pulseCount} />

      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-60 bg-surface-elevated border border-border-subtle shadow-xl px-4 py-2.5 rounded-xl text-xs font-medium text-cocoa flex items-center gap-2 animate-in slide-in-from-bottom-2 duration-200">
          <span className="w-2 h-2 rounded-full bg-emerald-600"></span>
          <span>{toastMessage}</span>
        </div>
      )}

      {/* DYNAMIC TOP HEADER (Morphs between hero and sticky results header) */}
      <header
        id="appHeader"
        className={`z-30 w-full view-transition ${
          viewState === 'results'
            ? 'sticky top-0 px-4 sm:px-8 border-b border-[#E3D2BE]/60 bg-[#F8F4EC]/90 backdrop-blur-md py-3 shadow-xs'
            : 'pt-16 pb-6'
        }`}
      >
        <div
          className={`w-full mx-auto flex flex-col items-center ${
            viewState === 'results' ? 'max-w-6xl' : 'max-w-4xl'
          }`}
        >
          {/* HERO CENTERED BRAND & TAGLINE (Visible in Hero state, smoothly collapses in results) */}
          <div
            id="heroCenterBlock"
            className={`view-transition overflow-hidden w-full text-center flex flex-col items-center justify-center select-none ${
              viewState === 'results'
                ? 'opacity-0 max-h-0 mb-0 pointer-events-none'
                : 'opacity-100 max-h-[260px] mb-8'
            }`}
          >
            {/* FindIT Wordmark with Dot */}
            <div
              onClick={() => setViewState('hero')}
              className="mb-4 flex items-center justify-center gap-1.5 group cursor-pointer"
            >
              <span className="font-headline-hero tracking-[-0.04em] font-bold text-[34px] sm:text-[46px] text-text-primary">
                Find<span className="text-primary-container font-extrabold tracking-tight">IT</span>
              </span>
              <span className="w-2 h-2 rounded-full bg-primary-container inline-block mb-1 group-hover:scale-125 transition-transform duration-200" />
            </div>

            <h1 className="font-headline-hero text-2xl sm:text-[36px] sm:leading-[44px] text-text-primary tracking-tight font-semibold mb-2">
              Find what you remember.
            </h1>
            <p className="font-body-md text-body-md text-text-secondary max-w-md mx-auto leading-relaxed">
              Whatever you remember, find where it belongs.
            </p>
          </div>

          {/* HEADER ROW: Strictly Centered Across Both Modes */}
          {viewState === 'hero' ? (
            /* HERO MODE: 100% Dead-Center Aligned to Screen */
            <div className="w-full max-w-[720px] mx-auto flex flex-col items-center justify-center">
              <form onSubmit={handleFormSubmit} className="relative w-full">
                <div className="w-full relative flex items-center rounded-2xl bg-surface-canvas/90 backdrop-blur-sm border border-[#9E2F2B]/40 hover:border-[#9E2F2B]/60 shadow-[0_4px_20px_-2px_rgba(158,47,43,0.08),0_1px_4px_rgba(41,37,34,0.04)] focus-within:border-[#9E2F2B] focus-within:shadow-[0_0_0_3px_rgba(158,47,43,0.18),0_8px_30px_-4px_rgba(158,47,43,0.14)] px-4 py-3 transition-all duration-200">
                  {/* Left: Magnifying Search Icon */}
                  <div className="pr-3 flex items-center justify-center text-text-secondary pointer-events-none group-focus-within:text-primary-container transition-colors">
                    <span className="material-symbols-outlined text-[22px]">search</span>
                  </div>

                  {/* Input field */}
                  <input
                    ref={searchInputRef}
                    type="text"
                    spellCheck="false"
                    autoComplete="off"
                    value={queryInput}
                    onChange={(e) => setQueryInput(e.target.value)}
                    placeholder="Search your documents…"
                    className="w-full bg-transparent font-body-lg text-sm sm:text-base text-text-primary placeholder:text-text-secondary/70 focus:outline-none"
                  />

                  {/* Right Actions: Clear, Folder Manager Trigger, Enter Hint */}
                  <div className="flex items-center gap-1.5 pl-2 shrink-0">
                    {queryInput.length > 0 && (
                      <button
                        type="button"
                        aria-label="Clear query"
                        onClick={handleClear}
                        className="text-text-secondary hover:text-text-primary p-1 rounded-lg transition-colors focus:outline-none"
                      >
                        <span className="material-symbols-outlined text-[18px]">close</span>
                      </button>
                    )}

                    <div className="h-4 w-px bg-sand-300"></div>

                    {/* Folder Icon Trigger */}
                    <button
                      type="button"
                      aria-label="Indexed folders"
                      onClick={() => setFoldersModalOpen(true)}
                      title="Manage indexed folders"
                      className="p-1.5 rounded-xl text-text-secondary hover:text-primary-container hover:bg-surface-secondary/70 active:scale-95 transition-all focus:outline-none focus:ring-1 focus:ring-primary-container"
                    >
                      <span className="material-symbols-outlined text-[20px]">folder</span>
                    </button>

                    <button
                      type="submit"
                      className="hidden sm:inline-flex items-center text-[11px] font-mono font-medium text-warmgrey/70 bg-sand-200/60 hover:bg-sand-200 hover:text-cocoa px-1.5 py-0.5 rounded border border-sand-300/60 transition-colors"
                    >
                      ↵ Enter
                    </button>
                  </div>
                </div>
              </form>

              <div className="mt-5 flex items-center justify-center gap-2 text-xs text-warmgrey select-none">
                <span className="w-2 h-2 rounded-full bg-brick" aria-hidden="true" />
                <span>Unified hybrid ranking · meaning and exact terms together</span>
              </div>

              {/* Indexed statistics in Hero View (Folder & File counts) */}
              <div className="mt-5 flex items-center justify-center gap-3 text-xs text-warmgrey select-none">
                <div
                  className="flex items-center gap-1.5 cursor-pointer hover:text-brick transition-colors"
                  onClick={() => setFoldersModalOpen(true)}
                  title="Manage indexed folders"
                >
                  <span className="material-symbols-outlined text-[15px]">folder</span>
                  <span>{directories.length} {directories.length === 1 ? 'folder' : 'folders'} indexed</span>
                </div>
                <span className="text-sand-300">·</span>
                <div
                  className="flex items-center gap-1.5 cursor-pointer hover:text-brick transition-colors"
                  onClick={() => setFoldersModalOpen(true)}
                  title="Manage indexed folders"
                >
                  <span className="material-symbols-outlined text-[15px]">description</span>
                  <span>{totalFilesIndexed} {totalFilesIndexed === 1 ? 'file' : 'files'} indexed</span>
                </div>
              </div>
            </div>
          ) : (
            /* RESULTS MODE: Extended Search Bar Header with No Tagline */
            <div className="w-full flex items-center justify-between gap-3 sm:gap-4 md:gap-6">
              {/* Left Column: Wordmark */}
              <div className="shrink-0 flex items-center">
                <div
                  id="headerLeftWordmark"
                  className="view-transition flex items-center gap-2 cursor-pointer animate-in fade-in"
                  onClick={() => setViewState('hero')}
                  title="Return to FindIT hero view"
                >
                  <div className="text-2xl font-bold tracking-tight text-cocoa hover:text-brick transition-colors">
                    Find<span className="text-brick font-bold">IT</span>
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-brick ml-0.5 align-middle" />
                  </div>
                </div>
              </div>

              {/* Center Column: Extended Search Input Bar */}
              <div className="flex-1 w-full max-w-4xl min-w-0 mx-2 sm:mx-4">
                <form onSubmit={handleFormSubmit} className="relative w-full">
                  <div className="w-full relative flex items-center rounded-2xl bg-[#FFFEFB] border border-[#9E2F2B]/40 hover:border-[#9E2F2B] focus-within:border-[#9E2F2B] px-3.5 py-2 shadow-xs focus-within:shadow-[0_0_0_3px_rgba(158,47,43,0.14)] transition-all duration-200">
                    <div className="pr-2.5 flex items-center justify-center text-text-secondary pointer-events-none group-focus-within:text-primary-container transition-colors shrink-0">
                      <span className="material-symbols-outlined text-[20px]">search</span>
                    </div>

                    <input
                      ref={searchInputRef}
                      type="text"
                      spellCheck="false"
                      autoComplete="off"
                      value={queryInput}
                      onChange={(e) => setQueryInput(e.target.value)}
                      placeholder="Search your documents…"
                      className="w-full min-w-0 bg-transparent font-body-lg text-sm md:text-base text-text-primary placeholder:text-text-secondary/70 focus:outline-none"
                    />

                    <div className="flex items-center gap-1.5 pl-2 shrink-0">
                      {queryInput.length > 0 && (
                        <button
                          type="button"
                          aria-label="Clear query"
                          onClick={handleClear}
                          className="text-text-secondary hover:text-text-primary p-1 rounded-lg transition-colors focus:outline-none"
                        >
                          <span className="material-symbols-outlined text-[16px]">close</span>
                        </button>
                      )}

                      <div className="h-4 w-px bg-sand-300"></div>

                      <button
                        type="button"
                        aria-label="Indexed folders"
                        onClick={() => setFoldersModalOpen(true)}
                        title="Manage indexed folders"
                        className="p-1.5 rounded-xl text-text-secondary hover:text-primary-container hover:bg-surface-secondary/70 active:scale-95 transition-all focus:outline-none focus:ring-1 focus:ring-primary-container"
                      >
                        <span className="material-symbols-outlined text-[18px]">folder</span>
                      </button>

                      <button
                        type="submit"
                        className="hidden sm:inline-flex items-center text-[11px] font-mono font-medium text-warmgrey/70 bg-sand-200/60 hover:bg-sand-200 hover:text-cocoa px-1.5 py-0.5 rounded border border-sand-300/60 transition-colors"
                      >
                        ↵ Enter
                      </button>
                    </div>
                  </div>
                </form>
              </div>

              {/* Right Column: Hero view button and Index Status (shrink-0, whitespace-nowrap) */}
              <div className="shrink-0 flex items-center gap-2.5 whitespace-nowrap">
                <button
                  type="button"
                  onClick={() => setViewState('hero')}
                  className="hidden sm:inline-flex items-center px-2.5 py-1 text-xs font-medium text-warmgrey hover:text-cocoa rounded-full bg-sand-200/50 hover:bg-sand-200 border border-sand-300/60 transition-colors whitespace-nowrap"
                  title="Switch view to hero homepage"
                >
                  Hero view
                </button>
                <div
                  onClick={() => setFoldersModalOpen(true)}
                  className="flex items-center gap-1.5 text-xs text-warmgrey font-medium pl-1 sm:pl-2 sm:border-l sm:border-sand-300 cursor-pointer hover:text-brick transition-colors whitespace-nowrap"
                  title={`${directories.length} folders · ${totalFilesIndexed} files indexed`}
                >
                  <span className="w-2 h-2 rounded-full bg-emerald-600 shrink-0" />
                  <span className="hidden sm:inline whitespace-nowrap">{directories.length} folders · {totalFilesIndexed} files</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </header>

      {/* MAIN UNIFIED SEARCH RESULTS REGION */}
      {viewState === 'results' && (
        <main className="view-transition flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-6 pb-20 animate-in fade-in slide-in-from-bottom-2 duration-300">
          <div className="flex flex-col items-center justify-center gap-2 mb-8">
            <div className="text-xs text-warmgrey font-mono flex items-center gap-2">
              <span>{totalAvailable} matching {totalAvailable === 1 ? 'passage' : 'passages'}</span>
              <span>·</span>
              <span>for "{activeQuery}"</span>
            </div>
          </div>

          {/* LOADING STATE */}
          {isLoading && (
            <div className="py-12 flex flex-col items-center justify-center text-center space-y-3">
              <span className="material-symbols-outlined text-[32px] text-brick animate-spin">
                progress_activity
              </span>
              <p className="text-xs text-warmgrey font-mono">Running hybrid vector & lexical retrieval...</p>
            </div>
          )}

          {/* EMPTY RESULTS STATE */}
          {!isLoading && results.length === 0 && (
            <div className="py-16 text-center space-y-3 bg-surface border border-sand-300 rounded-2xl p-8">
              <div className="w-12 h-12 rounded-full bg-sand-200 text-brick flex items-center justify-center mx-auto">
                <span className="material-symbols-outlined text-[24px]">search_off</span>
              </div>
              <h3 className="text-base font-semibold text-cocoa">No matching passages found</h3>
              <p className="text-xs text-warmgrey max-w-sm mx-auto">
                Try describing what you remember with different keywords, or check that the target folder is indexed.
              </p>
              <button
                type="button"
                onClick={() => setFoldersModalOpen(true)}
                className="mt-2 text-xs text-brick hover:underline font-medium"
              >
                Manage indexed folders →
              </button>
            </div>
          )}

          {/* UNIFIED RESULTS LIST */}
          {!isLoading && results.length > 0 && (
            <section aria-label="Search passages" className="space-y-2.5 mb-10">
              {results.map((result) => (
                <SearchResultCard
                  key={result.chunk_id}
                  result={result}
                  onInspect={handleInspectPassage}
                  onOpenFolder={handleOpenFolder}
                />
              ))}
            </section>
          )}

          {/* Bottom helper guidance */}
          <div className="pt-4 text-center text-xs text-warmgrey border-t border-sand-300/60">
            Click any row to inspect relevant extracted passages · Use{' '}
            <span className="font-mono text-[11px] bg-sand-200/60 px-1 py-0.5 rounded">
              Open in folder
            </span>{' '}
            to locate the physical file
          </div>
        </main>
      )}

      {/* PASSAGE INSPECTION MODAL */}
      <ErrorBoundary fallbackTitle="Could not load passage detail" onReset={() => setSelectedPassage(null)}>
        <PassageInspectorModal
          passage={selectedPassage}
          query={activeQuery}
          onClose={() => setSelectedPassage(null)}
          onOpenFolder={handleOpenFolder}
        />
      </ErrorBoundary>

      {/* INDEXED DIRECTORIES MANAGEMENT MODAL */}
      <ErrorBoundary fallbackTitle="Could not load directories dialog" onReset={() => setFoldersModalOpen(false)}>
        <DirectoriesModal
          isOpen={foldersModalOpen}
          onClose={() => setFoldersModalOpen(false)}
          directories={directories}
          onAddDirectory={handleAddDirectory}
          onSyncDirectory={handleSyncDirectory}
          onSyncAll={handleSyncAll}
          onRemoveDirectory={handleRemoveDirectory}
          activeJob={activeJob}
        />
      </ErrorBoundary>
    </div>
  );
}
export default App;
