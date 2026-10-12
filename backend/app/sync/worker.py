"""
FindIT Background Sync Worker & Job Progress Engine

Orchestrates incremental directory synchronization jobs in background threads:
Scanning -> Pruning -> Text Extraction -> Chunking -> Embedding -> FAISS & BM25 Indexing.
Maintains atomic progress and status in the index_jobs table.
"""

import concurrent.futures
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.core import config
from app.db.database import get_db
from app.extractors.factory import get_extractor_for_file
from app.chunking.chunker import StructureAwareChunker
from app.embeddings.embedder import EmbeddingEngine, get_embedder
from app.indexing.faiss_index import FaissIndex, get_faiss_index
from app.indexing.bm25_index import BM25Index, get_bm25_index
from app.sync.scanner import ScannerService, ScanResult, ScannedFile
from app.services.pruning_service import PruningService

logger = logging.getLogger("findit.sync.worker")


class SyncWorker:
    """
    Manages and executes directory synchronization and indexing pipelines.
    Runs asynchronously on a background thread pool with per-directory locking
    and live SQLite job progress tracking.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        max_workers: int = 2,
        faiss_idx: Optional[FaissIndex] = None,
        bm25_idx: Optional[BM25Index] = None,
    ):
        self.db_path = db_path or config.DATABASE_PATH
        self.faiss_idx = faiss_idx
        self.bm25_idx = bm25_idx
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="findit-sync-worker",
        )
        self._lock = threading.Lock()
        self._active_directories: Set[str] = set()
        self._active_jobs: Dict[str, concurrent.futures.Future] = {}

    def is_directory_syncing(self, directory_id: str) -> bool:
        """Returns True if a sync job is currently running for the directory."""
        with self._lock:
            return directory_id in self._active_directories

    def wait_for_directory(self, directory_id: str, timeout: float = 30.0) -> None:
        """Wait for queued/running jobs before pruning the directory's rows."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                job_items = list(self._active_jobs.items())
                active = directory_id in self._active_directories
            futures = [future for job_id, future in job_items if self._job_directory(job_id) == directory_id]
            for future in futures:
                if future.done():
                    continue
                # A worker catches pipeline errors and records them in SQLite;
                # this wait only synchronizes lifecycle ownership.
                try:
                    future.result(timeout=max(0.01, deadline - time.monotonic()))
                except concurrent.futures.TimeoutError:
                    break
                except Exception:
                    pass
            with get_db(self.db_path) as conn:
                row = conn.execute(
                    "SELECT 1 FROM index_jobs WHERE directory_id = ? AND status IN ('QUEUED', 'RUNNING') LIMIT 1",
                    (directory_id,),
                ).fetchone()
            if not active and row is None:
                return
            time.sleep(0.05)
        raise TimeoutError(f"Timed out waiting for directory jobs: {directory_id}")

    def _job_directory(self, job_id: str) -> Optional[str]:
        with get_db(self.db_path) as conn:
            row = conn.execute("SELECT directory_id FROM index_jobs WHERE job_id = ?", (job_id,)).fetchone()
            return row["directory_id"] if row else None

    def start_sync(
        self,
        directory_id: str,
        job_type: str = "SYNC_DIRECTORY",
        background: bool = True,
    ) -> str:
        """
        Enqueues an incremental synchronization job for a single directory.

        Args:
            directory_id: Directory to synchronize.
            job_type: INITIAL_INDEX or SYNC_DIRECTORY.
            background: If True, executes asynchronously in thread pool.

        Returns:
            job_id (str)
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        job_id = "job_" + uuid.uuid4().hex[:8]

        with self._lock:
            if directory_id in self._active_directories:
                # Find existing running job for this directory
                existing_job = self._get_running_job_for_directory(directory_id)
                if existing_job:
                    logger.info(f"Directory '{directory_id}' is already syncing under job {existing_job}")
                    return existing_job

            self._active_directories.add(directory_id)

        # 1. Create job record in SQLite
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO index_jobs (
                    job_id, directory_id, job_type, status, stage,
                    files_discovered, files_processed, files_failed,
                    passages_created, started_at, updated_at
                ) VALUES (?, ?, ?, 'QUEUED', 'VALIDATING', 0, 0, 0, 0, ?, ?);
                """,
                (job_id, directory_id, job_type, now_iso, now_iso),
            )
            # Mark directory as SYNCING
            cursor.execute(
                """
                UPDATE directories
                SET sync_status = 'SYNCING', last_sync_started_at = ?
                WHERE directory_id = ?;
                """,
                (now_iso, directory_id),
            )

        # 2. Launch execution
        if background:
            future = self._executor.submit(
                self._execute_sync_job,
                directory_id=directory_id,
                job_id=job_id,
            )
            with self._lock:
                self._active_jobs[job_id] = future
        else:
            self._execute_sync_job(directory_id=directory_id, job_id=job_id)

        return job_id

    def start_sync_all(self, background: bool = True) -> List[Dict[str, Any]]:
        """
        Triggers synchronization for all registered directories.

        Returns:
            List of enqueued job descriptors: [{"job_id": ..., "directory_id": ...}]
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT directory_id FROM directories ORDER BY added_at ASC;")
            rows = cursor.fetchall()

        results = []
        for r in rows:
            dir_id = r["directory_id"]
            job_id = self.start_sync(dir_id, job_type="SYNC_ALL", background=background)
            results.append({"job_id": job_id, "directory_id": dir_id, "status": "QUEUED"})
        return results

    def _get_running_job_for_directory(self, directory_id: str) -> Optional[str]:
        """Queries database for currently running job ID for directory."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT job_id FROM index_jobs
                WHERE directory_id = ? AND status IN ('QUEUED', 'RUNNING')
                ORDER BY started_at DESC LIMIT 1;
                """,
                (directory_id,),
            )
            row = cursor.fetchone()
            return row["job_id"] if row else None

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves real-time status and progress for a job ID."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 
                    job_id, directory_id, job_type, status, stage,
                    files_discovered, files_processed, files_failed,
                    passages_created, started_at, updated_at,
                    completed_at, error_summary
                FROM index_jobs
                WHERE job_id = ?;
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            files_discovered = row["files_discovered"]
            files_processed = row["files_processed"]
            progress = 0.0
            if files_discovered > 0:
                progress = round(min(1.0, files_processed / files_discovered), 3)
            elif row["status"] == "COMPLETED":
                progress = 1.0

            return {
                "job_id": row["job_id"],
                "directory_id": row["directory_id"],
                "job_type": row["job_type"],
                "status": row["status"],
                "stage": row["stage"],
                "files_discovered": files_discovered,
                "files_processed": files_processed,
                "files_failed": row["files_failed"],
                "passages_created": row["passages_created"],
                "progress": progress,
                "started_at": row["started_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
                "error_summary": row["error_summary"],
            }

    def list_jobs(
        self,
        directory_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Lists recent indexing jobs with optional directory filtering."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            if directory_id:
                cursor.execute(
                    """
                    SELECT 
                        job_id, directory_id, job_type, status, stage,
                        files_discovered, files_processed, files_failed,
                        passages_created, started_at, updated_at,
                        completed_at, error_summary
                    FROM index_jobs
                    WHERE directory_id = ?
                    ORDER BY started_at DESC LIMIT ?;
                    """,
                    (directory_id, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT 
                        job_id, directory_id, job_type, status, stage,
                        files_discovered, files_processed, files_failed,
                        passages_created, started_at, updated_at,
                        completed_at, error_summary
                    FROM index_jobs
                    ORDER BY started_at DESC LIMIT ?;
                    """,
                    (limit,),
                )
            rows = cursor.fetchall()
            jobs = []
            for row in rows:
                files_discovered = row["files_discovered"]
                files_processed = row["files_processed"]
                progress = 0.0
                if files_discovered > 0:
                    progress = round(min(1.0, files_processed / files_discovered), 3)
                elif row["status"] == "COMPLETED":
                    progress = 1.0

                jobs.append({
                    "job_id": row["job_id"],
                    "directory_id": row["directory_id"],
                    "job_type": row["job_type"],
                    "status": row["status"],
                    "stage": row["stage"],
                    "files_discovered": files_discovered,
                    "files_processed": files_processed,
                    "files_failed": row["files_failed"],
                    "passages_created": row["passages_created"],
                    "progress": progress,
                    "started_at": row["started_at"],
                    "updated_at": row["updated_at"],
                    "completed_at": row["completed_at"],
                    "error_summary": row["error_summary"],
                })
            return jobs

    def _update_job_progress(
        self,
        job_id: str,
        stage: str,
        files_discovered: Optional[int] = None,
        files_processed: Optional[int] = None,
        files_failed: Optional[int] = None,
        passages_created: Optional[int] = None,
        status: Optional[str] = None,
        error_summary: Optional[str] = None,
    ) -> None:
        """Internal helper to atomically update job progress in SQLite."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            updates = ["stage = ?", "updated_at = ?"]
            params: List[Any] = [stage, now_iso]

            if files_discovered is not None:
                updates.append("files_discovered = ?")
                params.append(files_discovered)
            if files_processed is not None:
                updates.append("files_processed = ?")
                params.append(files_processed)
            if files_failed is not None:
                updates.append("files_failed = ?")
                params.append(files_failed)
            if passages_created is not None:
                updates.append("passages_created = ?")
                params.append(passages_created)
            if status is not None:
                updates.append("status = ?")
                params.append(status)
                if status in ("COMPLETED", "FAILED"):
                    updates.append("completed_at = ?")
                    params.append(now_iso)
            if error_summary is not None:
                updates.append("error_summary = ?")
                params.append(error_summary)

            params.append(job_id)
            query = f"UPDATE index_jobs SET {', '.join(updates)} WHERE job_id = ?;"
            cursor.execute(query, params)

    def _execute_sync_job(self, directory_id: str, job_id: str) -> None:
        """
        Core synchronization pipeline execution:
        Validating -> Scanning -> Pruning -> Extracting -> Chunking -> Embedding -> Indexing
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        logger.info(f"Starting sync execution for directory '{directory_id}' under job '{job_id}'")

        try:
            # 1. VALIDATING STAGE
            self._update_job_progress(job_id, stage="VALIDATING", status="RUNNING")

            with get_db(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT canonical_path, display_name FROM directories WHERE directory_id = ?;",
                    (directory_id,),
                )
                dir_row = cursor.fetchone()
                if not dir_row:
                    raise ValueError(f"Directory with ID '{directory_id}' not found in database.")

                canonical_path = dir_row["canonical_path"]
                dir_path = Path(canonical_path).resolve()
                if not dir_path.exists() or not dir_path.is_dir():
                    raise ValueError(f"Registered directory missing on disk: '{canonical_path}'")

            # 2. SCANNING STAGE
            self._update_job_progress(job_id, stage="SCANNING")
            scan_result: ScanResult = ScannerService.scan_directory(
                directory_path=dir_path,
                directory_id=directory_id,
                db_path=self.db_path,
            )

            total_candidate_files = scan_result.candidate_count
            self._update_job_progress(
                job_id,
                stage="SCANNING",
                files_discovered=total_candidate_files,
            )
            logger.info(
                f"Scan complete for '{canonical_path}': "
                f"{len(scan_result.new_files)} new, {len(scan_result.modified_files)} modified, "
                f"{len(scan_result.deleted_files)} deleted, {len(scan_result.unchanged_files)} unchanged."
            )

            # 3. PRUNING STAGE (Deleted & Modified Files)
            faiss_index = self.faiss_idx or get_faiss_index()
            bm25_index = self.bm25_idx or get_bm25_index()

            # Handle deleted files
            if scan_result.deleted_files:
                deleted_doc_ids = [d["document_id"] for d in scan_result.deleted_files]
                PruningService.prune_documents(
                    deleted_doc_ids,
                    db_path=self.db_path,
                    faiss_idx=faiss_index,
                    bm25_idx=bm25_index,
                    persist_indices=False,
                )
                logger.info(f"Pruned {len(deleted_doc_ids)} deleted documents from indices.")

            # Handle modified files (remove previous passages and vectors before re-indexing)
            if scan_result.modified_files:
                modified_paths = [f.canonical_path.lower() for f in scan_result.modified_files]
                with get_db(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT document_id, canonical_path FROM documents WHERE directory_id = ?;",
                        (directory_id,),
                    )
                    all_existing = cursor.fetchall()
                    mod_doc_ids = [
                        r["document_id"] for r in all_existing
                        if r["canonical_path"].replace("\\", "/").lower() in modified_paths
                    ]

                if mod_doc_ids:
                    PruningService.prune_documents(
                        mod_doc_ids,
                        db_path=self.db_path,
                        faiss_idx=faiss_index,
                        bm25_idx=bm25_index,
                        persist_indices=False,
                    )
                    logger.info(f"Pruned {len(mod_doc_ids)} modified documents before re-indexing.")

            # Files needing extraction & indexing
            files_to_index: List[ScannedFile] = scan_result.new_files + scan_result.modified_files

            if not files_to_index:
                # Fast path: No content updates needed
                if scan_result.deleted_files:
                    faiss_index.save()
                    bm25_index.save()

                with get_db(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE directories
                        SET sync_status = 'IDLE', last_sync_completed_at = ?, last_error = NULL
                        WHERE directory_id = ?;
                        """,
                        (now_iso, directory_id),
                    )

                self._update_job_progress(
                    job_id,
                    stage="INDEXING",
                    status="COMPLETED",
                    files_processed=total_candidate_files,
                )
                logger.info(f"Job {job_id} completed early (no files modified).")
                return

            # 4. EXTRACTION, CHUNKING, EMBEDDING & INDEXING PIPELINE
            chunker = StructureAwareChunker()
            embedding_engine = get_embedder()

            files_processed = len(scan_result.unchanged_files)
            files_failed = 0
            total_passages_created = 0

            for scanned_file in files_to_index:
                file_path = Path(scanned_file.canonical_path)
                extractor = get_extractor_for_file(file_path)

                doc_id = "doc_" + uuid.uuid4().hex[:12]
                now_doc_iso = datetime.now(timezone.utc).isoformat()

                # Skip files exceeding MAX_FILE_SIZE_BYTES
                if scanned_file.size_bytes > config.MAX_FILE_SIZE_BYTES:
                    logger.warning(
                        f"Skipping oversized file '{file_path}' ({scanned_file.size_bytes} bytes exceeds {config.MAX_FILE_SIZE_BYTES} limit)"
                    )
                    with get_db(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO documents (
                                document_id, directory_id, canonical_path, filename,
                                extension, file_type, size_bytes, modified_time,
                                content_fingerprint, extraction_status, last_indexed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'SKIPPED_TOO_LARGE', ?)
                            ON CONFLICT(canonical_path) DO UPDATE SET
                                extraction_status = 'SKIPPED_TOO_LARGE',
                                last_indexed_at = excluded.last_indexed_at;
                            """,
                            (
                                doc_id, directory_id, scanned_file.canonical_path,
                                scanned_file.filename, scanned_file.extension,
                                scanned_file.file_type, scanned_file.size_bytes,
                                scanned_file.modified_time, scanned_file.content_fingerprint,
                                now_doc_iso,
                            ),
                        )
                    files_failed += 1
                    files_processed += 1
                    self._update_job_progress(
                        job_id,
                        stage="EXTRACTING",
                        files_processed=files_processed,
                        files_failed=files_failed,
                    )
                    continue

                if not extractor:
                    # Unsupported format
                    with get_db(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO documents (
                                document_id, directory_id, canonical_path, filename,
                                extension, file_type, size_bytes, modified_time,
                                content_fingerprint, extraction_status, last_indexed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'UNSUPPORTED', ?)
                            ON CONFLICT(canonical_path) DO UPDATE SET
                                extraction_status = 'UNSUPPORTED',
                                last_indexed_at = excluded.last_indexed_at;
                            """,
                            (
                                doc_id, directory_id, scanned_file.canonical_path,
                                scanned_file.filename, scanned_file.extension,
                                scanned_file.file_type, scanned_file.size_bytes,
                                scanned_file.modified_time, scanned_file.content_fingerprint,
                                now_doc_iso,
                            ),
                        )
                    files_failed += 1
                    files_processed += 1
                    self._update_job_progress(
                        job_id,
                        stage="EXTRACTING",
                        files_processed=files_processed,
                        files_failed=files_failed,
                    )
                    continue

                # 4.1 EXTRACTING
                self._update_job_progress(job_id, stage="EXTRACTING")
                try:
                    extracted_doc = extractor.extract(file_path)
                except Exception as e:
                    logger.warning(f"Failed extraction on '{file_path}': {e}")
                    with get_db(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO documents (
                                document_id, directory_id, canonical_path, filename,
                                extension, file_type, size_bytes, modified_time,
                                content_fingerprint, extraction_status, last_indexed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ERROR', ?)
                            ON CONFLICT(canonical_path) DO UPDATE SET
                                extraction_status = 'ERROR',
                                last_indexed_at = excluded.last_indexed_at;
                            """,
                            (
                                doc_id, directory_id, scanned_file.canonical_path,
                                scanned_file.filename, scanned_file.extension,
                                scanned_file.file_type, scanned_file.size_bytes,
                                scanned_file.modified_time, scanned_file.content_fingerprint,
                                now_doc_iso,
                            ),
                        )
                    files_failed += 1
                    files_processed += 1
                    self._update_job_progress(
                        job_id,
                        stage="EXTRACTING",
                        files_processed=files_processed,
                        files_failed=files_failed,
                    )
                    continue

                # Check if extractor encountered an error
                if getattr(extracted_doc, "extraction_status", "OK") == "ERROR":
                    logger.warning(
                        f"Extractor reported error on '{file_path}': {extracted_doc.error_message}"
                    )
                    with get_db(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO documents (
                                document_id, directory_id, canonical_path, filename,
                                extension, file_type, size_bytes, modified_time,
                                content_fingerprint, extraction_status, last_indexed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ERROR', ?)
                            ON CONFLICT(canonical_path) DO UPDATE SET
                                extraction_status = 'ERROR',
                                last_indexed_at = excluded.last_indexed_at;
                            """,
                            (
                                doc_id, directory_id, scanned_file.canonical_path,
                                scanned_file.filename, scanned_file.extension,
                                scanned_file.file_type, scanned_file.size_bytes,
                                scanned_file.modified_time, scanned_file.content_fingerprint,
                                now_doc_iso,
                            ),
                        )
                    files_failed += 1
                    files_processed += 1
                    self._update_job_progress(
                        job_id,
                        stage="EXTRACTING",
                        files_processed=files_processed,
                        files_failed=files_failed,
                    )
                    continue

                # Check if extracted document has text
                has_text = any(b.text.strip() for b in extracted_doc.blocks)
                if not has_text:
                    with get_db(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO documents (
                                document_id, directory_id, canonical_path, filename,
                                extension, file_type, size_bytes, modified_time,
                                content_fingerprint, extraction_status, last_indexed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'NO_TEXT', ?)
                            ON CONFLICT(canonical_path) DO UPDATE SET
                                extraction_status = 'NO_TEXT',
                                last_indexed_at = excluded.last_indexed_at;
                            """,
                            (
                                doc_id, directory_id, scanned_file.canonical_path,
                                scanned_file.filename, scanned_file.extension,
                                scanned_file.file_type, scanned_file.size_bytes,
                                scanned_file.modified_time, scanned_file.content_fingerprint,
                                now_doc_iso,
                            ),
                        )
                    files_processed += 1
                    self._update_job_progress(
                        job_id,
                        stage="EXTRACTING",
                        files_processed=files_processed,
                    )
                    continue

                # 4.2 CHUNKING
                chunks = chunker.chunk_document(doc_id, extracted_doc)
                if not chunks:
                    with get_db(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO documents (
                                document_id, directory_id, canonical_path, filename,
                                extension, file_type, size_bytes, modified_time,
                                content_fingerprint, extraction_status, last_indexed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'NO_TEXT', ?)
                            ON CONFLICT(canonical_path) DO UPDATE SET
                                extraction_status = 'NO_TEXT',
                                last_indexed_at = excluded.last_indexed_at;
                            """,
                            (
                                doc_id, directory_id, scanned_file.canonical_path,
                                scanned_file.filename, scanned_file.extension,
                                scanned_file.file_type, scanned_file.size_bytes,
                                scanned_file.modified_time, scanned_file.content_fingerprint,
                                now_doc_iso,
                            ),
                        )
                    files_processed += 1
                    self._update_job_progress(
                        job_id,
                        stage="EXTRACTING",
                        files_processed=files_processed,
                    )
                    continue

                # 4.3 EMBEDDING
                self._update_job_progress(job_id, stage="EMBEDDING")
                texts = [c.text for c in chunks]
                embeddings = embedding_engine.embed_texts(texts)

                # 4.4 INDEXING
                self._update_job_progress(job_id, stage="INDEXING")
                with get_db(self.db_path) as conn:
                    cursor = conn.cursor()
                    # Query highest existing vector_id to ensure sequential uniqueness
                    cursor.execute("SELECT COALESCE(MAX(vector_id), 0) FROM passages;")
                    max_vec_id = int(cursor.fetchone()[0])
                    vector_ids = [max_vec_id + 1 + i for i in range(len(chunks))]
                    chunk_ids = [c.chunk_id for c in chunks]

                    # 1. Insert into FAISS
                    faiss_index.add_vectors(embeddings, vector_ids, chunk_ids)

                    # 2. Insert into BM25
                    bm25_index.add_documents(chunk_ids, texts)

                    # 3. Insert Document into SQLite
                    cursor.execute(
                        """
                        INSERT INTO documents (
                            document_id, directory_id, canonical_path, filename,
                            extension, file_type, size_bytes, modified_time,
                            content_fingerprint, extraction_status, last_indexed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OK', ?)
                        ON CONFLICT(canonical_path) DO UPDATE SET
                            document_id = excluded.document_id,
                            size_bytes = excluded.size_bytes,
                            modified_time = excluded.modified_time,
                            content_fingerprint = excluded.content_fingerprint,
                            extraction_status = 'OK',
                            last_indexed_at = excluded.last_indexed_at;
                        """,
                        (
                            doc_id, directory_id, scanned_file.canonical_path,
                            scanned_file.filename, scanned_file.extension,
                            scanned_file.file_type, scanned_file.size_bytes,
                            scanned_file.modified_time, scanned_file.content_fingerprint,
                            now_doc_iso,
                        ),
                    )

                    # 4. Insert Passages into SQLite
                    for chunk, v_id in zip(chunks, vector_ids):
                        cursor.execute(
                            """
                            INSERT INTO passages (
                                chunk_id, document_id, chunk_ordinal, text, normalized_text,
                                page_number, start_page, end_page, slide_number,
                                start_line, end_line, section_heading, paragraph_index, vector_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            (
                                chunk.chunk_id, doc_id, chunk.chunk_ordinal, chunk.text,
                                chunk.text.lower(), chunk.page_number, chunk.start_page,
                                chunk.end_page, chunk.slide_number, chunk.start_line,
                                chunk.end_line, chunk.section_heading, chunk.paragraph_index,
                                v_id,
                            ),
                        )

                total_passages_created += len(chunks)
                files_processed += 1
                self._update_job_progress(
                    job_id,
                    stage="INDEXING",
                    files_processed=files_processed,
                    passages_created=total_passages_created,
                )

            # 5. Persist indices to disk
            try:
                faiss_index.save()
            except Exception as e:
                logger.warning(f"Failed to persist FAISS index: {e}")

            try:
                bm25_index.save()
            except Exception as e:
                logger.warning(f"Failed to persist BM25 index: {e}")

            # 6. Finalize Directory & Job Status
            with get_db(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE directories
                    SET sync_status = 'IDLE', last_sync_completed_at = ?, last_error = NULL
                    WHERE directory_id = ?;
                    """,
                    (now_iso, directory_id),
                )

            self._update_job_progress(
                job_id,
                stage="INDEXING",
                status="COMPLETED",
                files_processed=total_candidate_files,
                files_failed=files_failed,
                passages_created=total_passages_created,
            )
            logger.info(
                f"Successfully completed sync job '{job_id}' for directory '{directory_id}': "
                f"{files_processed} files processed, {total_passages_created} passages indexed."
            )

        except Exception as e:
            # A directory can be removed while a queued job is draining. That
            # is a normal lifecycle race, not an application traceback.
            missing_directory = "Registered directory missing" in str(e) or "not found in database" in str(e)
            if missing_directory:
                logger.info("Sync job '%s' ended after its directory was removed: %s", job_id, e)
            else:
                logger.error(f"Sync job '{job_id}' failed with exception: {e}", exc_info=True)
            with get_db(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE directories
                    SET sync_status = 'ERROR', last_error = ?
                    WHERE directory_id = ?;
                    """,
                    (str(e), directory_id),
                )

            self._update_job_progress(
                job_id,
                stage="INDEXING",
                status="FAILED",
                error_summary=str(e),
            )
        finally:
            with self._lock:
                self._active_directories.discard(directory_id)
                self._active_jobs.pop(job_id, None)


# Global singleton instance
_SYNC_WORKER: Optional[SyncWorker] = None
_WORKER_LOCK = threading.Lock()


def get_sync_worker() -> SyncWorker:
    """Returns singleton SyncWorker instance."""
    global _SYNC_WORKER
    if _SYNC_WORKER is None:
        with _WORKER_LOCK:
            if _SYNC_WORKER is None:
                _SYNC_WORKER = SyncWorker()
    return _SYNC_WORKER
