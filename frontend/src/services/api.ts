import type { SearchResult, PassageDetail, IndexedDirectory, TrackedDocument, HealthStatus, SyncJob } from '../types';

// Use relative API base path proxied through Vite dev server to FastAPI backend
const API_BASE_URL = '/api';

/**
 * Checks backend health and runtime configuration.
 */
export async function checkBackendHealth(): Promise<HealthStatus | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/health`);
    if (response.ok) {
      return await response.json();
    }
  } catch {
    // Backend offline / not yet reachable
  }
  return null;
}

/**
 * Executes live hybrid vector + lexical search via POST /api/search.
 */
export async function searchPassages(
  query: string,
  limit: number = 20,
  offset: number = 0
): Promise<{ query: string; total_available: number; results: SearchResult[]; next_offset?: number | null }> {
  const trimmed = query.trim();
  if (!trimmed) {
    return { query: '', total_available: 0, results: [] };
  }

  try {
    const response = await fetch(`${API_BASE_URL}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: trimmed, limit, offset }),
    });

    if (response.ok) {
      const data = await response.json();
      return {
        query: data.query,
        total_available: data.total_available ?? data.results.length,
        results: data.results || [],
        next_offset: data.next_offset,
      };
    } else {
      const errData = await response.json().catch(() => null);
      const msg = errData?.detail || 'Search query failed on backend';
      throw new Error(msg);
    }
  } catch (err: unknown) {
    loggerFallback('search', err);
    if (err instanceof Error && err.message) throw err;
    throw new Error('Backend unavailable. Start FindIT and try again.');
  }
}

/**
 * Retrieves full extracted passage text, coordinates, and surrounding context.
 */
export async function getPassageDetail(chunkId: string): Promise<PassageDetail> {
  const response = await fetch(`${API_BASE_URL}/passages/${chunkId}`);
  if (!response.ok) {
    const errData = await response.json().catch(() => null);
    throw new Error(errData?.detail || `Passage '${chunkId}' not found`);
  }
  return await response.json();
}

/**
 * Fetches all user-approved directories with file and passage counts.
 */
export async function getIndexedDirectories(): Promise<IndexedDirectory[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/directories`);
    if (response.ok) {
      const data = await response.json();
      return data.directories || [];
    }
  } catch (err) {
    loggerFallback('getIndexedDirectories', err);
  }
  return [];
}

/**
 * Fetches all tracked files within a specific directory.
 */
export async function getDirectoryDocuments(directoryId: string): Promise<TrackedDocument[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/directories/${directoryId}/documents`);
    if (response.ok) {
      const data = await response.json();
      return data.documents || [];
    }
  } catch (err) {
    loggerFallback('getDirectoryDocuments', err);
  }
  return [];
}

/**
 * Registers a new local folder root for indexing.
 */
export async function registerDirectory(
  canonicalPath: string
): Promise<{ directory: IndexedDirectory; initial_job_id: string }> {
  const response = await fetch(`${API_BASE_URL}/directories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ canonical_path: canonicalPath.trim() }),
  });

  if (!response.ok) {
    const errData = await response.json().catch(() => null);
    const msg =
      errData?.detail?.error?.message ||
      errData?.detail ||
      'Failed to register directory path';
    throw new Error(msg);
  }
  return await response.json();
}

/**
 * Unlinks a directory: purges index records while keeping disk files untouched.
 */
export async function deleteDirectory(
  directoryId: string
): Promise<{ success: boolean; directory_id: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/directories/${directoryId}`, {
    method: 'DELETE',
  });

  if (!response.ok) {
    const errData = await response.json().catch(() => null);
    const msg =
      errData?.detail?.error?.message ||
      errData?.detail ||
      'Failed to delete directory registration';
    throw new Error(msg);
  }
  return await response.json();
}

/**
 * Triggers an incremental synchronization job for a single directory.
 */
export async function syncDirectory(
  directoryId: string
): Promise<{ job_id: string; directory_id: string; status: string }> {
  const response = await fetch(`${API_BASE_URL}/sync/${directoryId}`, {
    method: 'POST',
  });

  if (!response.ok) {
    const errData = await response.json().catch(() => null);
    const msg =
      errData?.detail?.error?.message ||
      errData?.detail ||
      'Failed to start directory synchronization';
    throw new Error(msg);
  }
  return await response.json();
}

/**
 * Triggers incremental synchronization across all registered directories.
 */
export async function syncAllDirectories(): Promise<{
  status: string;
  jobs: Array<{ job_id: string; directory_id: string; status: string }>;
}> {
  const response = await fetch(`${API_BASE_URL}/sync`, {
    method: 'POST',
  });

  if (!response.ok) {
    const errData = await response.json().catch(() => null);
    const msg =
      errData?.detail?.error?.message ||
      errData?.detail ||
      'Failed to trigger global synchronization';
    throw new Error(msg);
  }
  return await response.json();
}

/**
 * Queries detailed status, stage, and file metrics for a specific indexing job.
 */
export async function getJobStatus(jobId: string): Promise<SyncJob | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/jobs/${jobId}`);
    if (response.ok) {
      const data = await response.json();
      return {
        job_id: data.job_id,
        directory_id: data.directory_id,
        job_type: data.job_type,
        status: data.status,
        stage: data.stage,
        progress_percent: Math.round((data.progress ?? 0) * 100),
        files_discovered: data.files_discovered ?? 0,
        files_processed: data.files_processed ?? 0,
        passages_created: data.passages_created ?? 0,
        error_summary: data.error_summary,
        current_file_or_desc: formatJobStageDescription(data.stage, data.files_processed, data.files_discovered),
      };
    }
  } catch (err) {
    loggerFallback(`getJobStatus(${jobId})`, err);
  }
  return null;
}

/**
 * Queries current status across all running and recent sync jobs.
 */
export async function getSyncStatus(jobId?: string, directoryId?: string): Promise<SyncJob[]> {
  try {
    const params = new URLSearchParams();
    if (jobId) params.append('job_id', jobId);
    if (directoryId) params.append('directory_id', directoryId);

    const url = `${API_BASE_URL}/sync/status${params.toString() ? '?' + params.toString() : ''}`;
    const response = await fetch(url);
    if (response.ok) {
      const data = await response.json();
      return (data.jobs || []).map((j: any) => ({
        job_id: j.job_id,
        directory_id: j.directory_id,
        job_type: j.job_type,
        status: j.status,
        stage: j.stage,
        progress_percent: Math.round((j.progress ?? 0) * 100),
        files_discovered: j.files_discovered ?? 0,
        files_processed: j.files_processed ?? 0,
        passages_created: j.passages_created ?? 0,
        error_summary: j.error_summary,
        current_file_or_desc: formatJobStageDescription(j.stage, j.files_processed, j.files_discovered),
      }));
    }
  } catch (err) {
    loggerFallback('getSyncStatus', err);
  }
  return [];
}

/**
 * Triggers host OS native folder picker dialog.
 */
export async function pickNativeFolder(): Promise<{ path: string | null; selected: boolean }> {
  const response = await fetch(`${API_BASE_URL}/directories/pick`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error('Native folder picker request failed');
  }
  return await response.json();
}

/**
 * Commands the OS file manager (Windows Explorer) to reveal the physical file.
 */
export async function openContainingFolder(
  pathOrDocumentId: string
): Promise<{ success: boolean; message: string; path?: string }> {
  const isDocId = pathOrDocumentId.startsWith('doc_');
  const payload = isDocId ? { document_id: pathOrDocumentId } : { path: pathOrDocumentId };

  const response = await fetch(`${API_BASE_URL}/open-location`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errData = await response.json().catch(() => null);
    throw new Error(errData?.detail || 'Failed to open location in file explorer');
  }
  return await response.json();
}

function formatJobStageDescription(stage: string, processed: number, total: number): string {
  switch (stage?.toUpperCase()) {
    case 'VALIDATING':
      return 'Validating directory boundaries';
    case 'SCANNING':
      return 'Scanning filesystem for document changes';
    case 'EXTRACTING':
      return `Extracting document text (${processed}/${total} files)`;
    case 'EMBEDDING':
      return `Generating 384D semantic embeddings (${processed}/${total} files)`;
    case 'INDEXING':
      return 'Updating FAISS vector index & BM25 postings';
    default:
      return stage || 'Processing';
  }
}

function loggerFallback(context: string, err: unknown) {
  console.debug(`[FindIT API] ${context} error (check backend connection):`, err);
}
