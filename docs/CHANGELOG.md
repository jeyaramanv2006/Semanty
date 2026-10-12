# Changelog — FindIT

All notable changes to the FindIT project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Completed
- Adopt the FastAPI backend as the sole authoritative search engine.
- Added a primary Textual TUI over the local REST API with full search, inspection, directory, and sync workflows.
- Standardize user-facing search on one backend-provided hybrid RRF ordering.
- Retired the independent CLI engine after TUI parity; distributable packaging remains out of scope.

- Unified directory registration and synchronization behind real asynchronous backend jobs.
- Enforced hybrid-only ordering for normal API and UI clients and corrected multi-page labels.
- Added the Textual TUI with backend lifecycle ownership, search, inspection, directory management, sync monitoring, and terminal-focused tests.
- Removed the independent `cli/` engine and its separate index format.
- Kept the React client supported, removed ranking-mode controls, and verified frontend lint/build.

Verification: backend contract/indexing suites and Textual tests pass in the project virtualenv; frontend lint and production build pass. Interactive PTY smoke testing remains a manual release check on the target terminal.

---

## [0.1.0] - 2026-10-11

### Completed
- **Performance & Hardware Acceleration — Adaptive GPU Inference with Graceful CPU Fallback (ADR-010)**:
  - Upgraded `EmbeddingEngine` in `backend/app/embeddings/embedder.py` to support dynamic execution device binding.
  - Implemented automatic hardware detection in `backend/app/core/config.py`: auto-selects `"cuda"` if an NVIDIA GPU is available (`torch.cuda.is_available()`), with transparent fallback to `"cpu"`.
  - Added `FINDIT_EMBEDDING_DEVICE` environment override for explicit hardware configuration.
  - Formally recorded decision in `docs/DECISIONS.md` under ADR-010.
  - Verified full test suite passes with 64/64 tests green.
- **Milestone 8 & Batch 7 (Phase 18) — System Hardening, Edge-Case Resilience & Verification Runbook**:
  - Implemented comprehensive automated end-to-end test suite in `backend/tests/test_e2e.py` covering:
    - Empty directory indexing: clean job completion with 0 files and 0 passages.
    - Corrupt and malformed files: corrupted PDFs (invalid binary headers) and corrupted DOCX files (non-zip text) fail gracefully with `extraction_status = 'ERROR'` without halting the sync worker, allowing adjacent valid files to index.
    - Zero-byte files: empty `.txt` and `.md` files classified as `NO_TEXT` without generating empty passage artifacts.
    - Oversized file skip defense: files exceeding `MAX_FILE_SIZE_BYTES` (50MB) recorded with `extraction_status = 'SKIPPED_TOO_LARGE'` to protect CPU memory.
    - Special characters, spaces, brackets, and Unicode: filenames and directories containing brackets, ampersands, accents, and Chinese characters index and retrieve seamlessly.
    - Path traversal confinement: `OSService` verifies physical file existence within registered directories in SQLite, raising `SecurityBoundaryError` for unauthorized system path escapes and `FileNotFoundError` for missing paths.
    - Latency benchmarking: benchmarked 1,000 indexed passages across 20 hybrid search queries, achieving mean latency of **29.36 ms** (p95: 32.95 ms), well under the strict 100ms threshold.
    - Global exception handling middleware: structured JSON envelopes for 404 Not Found, 422 Unprocessable Entity, and 500 Internal Server Error.
    - Temporary file defense: Hardened scanner to ignore Microsoft Office temporary lock files (`~$*`) and Unix dotfiles (`.*`) in `ScannerService` and `DirectoryService`.
    - Directory Document Inspection Feature: Implemented `GET /api/directories/{directory_id}/documents` endpoint in `backend/app/api/directories.py` and `DirectoryService.list_documents`.
    - Added interactive "View files" / "Hide files" expandable accordion drawer in frontend `DirectoriesModal.tsx`, showing live per-file icons, exact filename, formatted size, and status badges (`Indexed (N passages)`, `Pending sync`, `Failed / Locked`, `Skipped (>50MB)`, `No text layer`).
  - Added global error-handling middleware in `backend/app/main.py`.
  - Added `MAX_FILE_SIZE_BYTES = 50MB` setting in `backend/app/core/config.py`.
  - Upgraded `OSService.validate_path_confinement` to normalize both `str` and `Path` inputs.
  - Complete backend test suite: **64 / 64 tests passing** with 0 failures across all 9 test suites.
  - Complete frontend build verified: `tsc -b && vite build` clean with 0 errors.

## [0.1.0-m6] - 2026-10-11

### Completed
- **Milestone 6 & Batch 6 (Phases 15, 16, 17) — Full-Stack Integration: Vite Proxy, Live API & UI Wiring**:
  - Configured Vite Reverse Proxy in `frontend/vite.config.ts` forwarding `/api` requests directly to FastAPI local backend at `http://127.0.0.1:8000` with `changeOrigin: true`.
  - Re-architected `frontend/src/services/api.ts` to connect to live backend endpoints with zero mock fallbacks during active connectivity:
    - `POST /api/search` with Reciprocal Rank Fusion ($k=60$) results.
    - `GET /api/passages/{id}` retrieving complete unvarnished text, surrounding context, and rank metadata.
    - `GET /api/directories`, `POST /api/directories`, `DELETE /api/directories/{id}`.
    - `POST /api/sync`, `POST /api/sync/{directory_id}`, `GET /api/sync/status`, `GET /api/jobs/{id}`.
    - `POST /api/directories/pick` native OS directory dialog launcher.
    - `POST /api/open-location` native Windows Explorer reveal bridge.
  - Enhanced `frontend/src/types/index.ts` with complete `PassageDetail` context fields (`surrounding_context_before`, `surrounding_context_after`, `chunk_ordinal`) and `SyncJob` execution metadata.
  - Updated `PassageInspectorModal.tsx` to render surrounding document context, keyword highlights, and direct native folder reveal action.
  - Wired `App.tsx` and `DirectoriesModal.tsx` to live backend:
    - Active polling interval (500ms) tracking `index_jobs` stages and displaying real-time progress bars (0% to 100%).
    - Live hybrid search execution with score badges and rank popover.
    - Clean production build verified via `tsc -b && vite build` (272 kB bundle, zero TypeScript errors).

## [0.1.0-m7] - 2026-10-11

### Completed
- **Milestone 7 & Batch 5 (Phases 12, 13, 14) — Incremental Sync Scanner, Background Worker & Index Pruning**:
  - Implemented `ScannerService` and `ScanResult` in `backend/app/sync/scanner.py`:
    - Recursive crawling of user-approved directory roots.
    - Directory boundary confinement with symlink containment defense.
    - Automated skipping of ignored directories (`.git`, `node_modules`, `.venv`, etc.) and unsupported extensions.
    - Timestamp (`mtime`), file size (`size_bytes`), and buffered SHA-256 fingerprint change detection.
    - Precise categorization into `new_files`, `modified_files`, `deleted_files`, and `unchanged_files`.
  - Implemented `PruningService` in `backend/app/services/pruning_service.py`:
    - Atomic index pruning: removes obsolete vectors from FAISS and postings from BM25.
    - Cascade deletion of directory and document metadata in SQLite (`foreign_keys = ON`).
    - Source document immutability guarantee: original files on disk remain 100% untouched.
    - Added disaster-recovery utility `rebuild_bm25_from_sqlite()` as mandated by TRD Section 6.2.
  - Implemented `SyncWorker` in `backend/app/sync/worker.py`:
    - Multi-threaded asynchronous execution pool with per-directory locking.
    - Complete multi-stage indexing pipeline: `VALIDATING` -> `SCANNING` -> `EXTRACTING` -> `EMBEDDING` -> `INDEXING` -> `COMPLETED`.
    - Real-time progress metric calculations recorded in `index_jobs` table.
    - Seamless extractor and chunker dispatch with sequential 64-bit vector ID mapping.
  - Implemented Synchronization REST API in `backend/app/api/sync.py`:
    - `POST /api/sync`: triggers global incremental synchronization across all registered folders.
    - `POST /api/sync/{directory_id}`: triggers sync for a single directory (returns 202 Accepted).
    - `GET /api/sync/status`: queries live status, stage, and file counts across running/recent jobs.
    - `GET /api/jobs/{job_id}`: retrieves detailed job execution metrics as per API.md Section 3.1.
  - Connected `DirectoryService.delete_directory` to `PruningService.prune_directory` and `DirectoryService.sync_directory` to `SyncWorker`.
  - Registered `sync.router` in `backend/app/main.py`.
  - Added comprehensive test suite `backend/tests/test_sync.py` (5 tests covering change detection, directory pruning, disk file immutability, full pipeline execution, and REST endpoints).
  - Full backend test suite passing with **56/56 tests passing**.

## [0.1.0-m5] - 2026-10-11

### Completed
- **Milestone 5 & Batch 4 (Phases 9, 10, 11) — Hybrid Search (RRF), Passage Inspector API & Native OS Launcher**:
  - Implemented `SearchService` in `backend/app/services/search_service.py`:
    - Dispatches queries to FAISS (top-50 semantic) and BM25 (top-50 lexical).
    - Fuses results via Reciprocal Rank Fusion ($k=60$): $RRF(d) = \sum_{r \in \mathcal{R}} \frac{1}{60 + \text{rank}_r(d)}$.
    - Hydrates ranked candidate chunks with SQLite metadata (`documents` and `passages` tables).
    - Formats trustworthy location coordinate labels (`Page X`, `Slide Y`, `Lines X–Y`, `Section: Z`), passage preview snippets, and shortened display paths (`~/...`).
    - Implemented passage detail inspection with previous and next surrounding passage chunks in the same document.
  - Implemented `OSService` in `backend/app/services/os_service.py`:
    - Safe invocation of Windows Explorer (`explorer.exe /select,"<path>"`) with path traversal prevention and directory confinement against approved roots in SQLite.
    - Added document launch in default associated application.
  - Implemented API router endpoints:
    - `POST /api/search` and `GET /api/search`: hybrid search with pagination (`limit`, `offset`, `next_offset`).
    - `GET /api/passages/{chunk_id}`: full passage detail for Passage Inspector modal with surrounding context.
    - `POST /api/open-location`: reveals file in native explorer.
    - `POST /api/documents/{document_id}/open-folder`: opens document's containing folder.
    - `POST /api/documents/{document_id}/open`: launches document in default viewer.
  - Added test suite `backend/tests/test_search.py` with 12 tests covering RRF mathematics, search service, pagination, passage context, OS confinement security, and FastAPI endpoints.
  - Full backend test suite passing with **51/51 tests passing**.

## [0.1.0-m4] - 2026-10-11

### Completed
- **Milestone 4 & Batch 3 (Phases 6, 7, 8) — Semantic Embeddings, FAISS Vector Index & BM25 Lexical Engine**:
  - Implemented `EmbeddingEngine` and `get_embedder()` in `backend/app/embeddings/embedder.py`:
    - Wraps `sentence-transformers/all-MiniLM-L6-v2` with lazy loading on demand and CPU thread safety.
    - Produces exactly 384-dimensional dense vectors with strict L2-normalization ($\|\mathbf{v}\|_2 = 1.0$).
    - Supports batch document embedding (`embed_texts`) and single query vector inference (`embed_query`).
  - Implemented `FaissIndex` and `VectorSearchResult` in `backend/app/indexing/faiss_index.py`:
    - Wraps `faiss.IndexFlatIP(384)` inside `faiss.IndexIDMap2` for exact cosine similarity search and explicit 64-bit vector ID mapping.
    - Implemented vector insertion (`add_vectors`), ID-based removal (`remove_vectors`), and chunk removal (`remove_chunks`).
    - Implemented atomic serialization to disk (`backend/data/index.faiss`) and bidirectional `vector_id` $\leftrightarrow$ `chunk_id` metadata mapping (`index.faiss.map.json`).
  - Implemented `BM25Index`, `RobustBM25Okapi`, and `tokenize_code_and_prose` in `backend/app/indexing/bm25_index.py`:
    - Custom identifier-aware tokenizer extracting natural prose while preserving compound programming symbols (`snake_case`, `camelCase`, `PascalCase`, dotted module names, and file paths) alongside their individual sub-components.
    - Implemented `RobustBM25Okapi` with positive-smoothed Lucene IDF ($\ln(1 + \frac{N - n + 0.5}{n + 0.5})$) guaranteeing non-zero scores on small corpora.
    - Implemented dynamic document addition, deletion, and atomic pickle serialization (`backend/data/bm25.pkl`).
  - Created comprehensive unit test suite in `backend/tests/test_indices.py` covering:
    - 384D vector dimensions and unit norms.
    - FAISS exact inner-product search and 100 sample vector verification checkpoint with cosine similarities $\in [-1.0, 1.0]$.
    - BM25 verification checkpoint ranking exact `auth_middleware` matches over prose.
    - Rare identifier retrieval and atomic index save/reload fidelity.
  - Full backend test suite passing with **39/39 tests passing**.

## [0.1.0-m3] - 2026-10-11

### Completed
- **Milestone 3 & Batch 2 (Phases 3, 4, 5) — Multi-Format Extraction & Structure-Aware Chunking**:
  - Implemented `BaseExtractor`, `ExtractedBlock`, and `ExtractedDocument` contracts in `backend/app/extractors/base.py`.
  - Implemented `TextExtractor` in `backend/app/extractors/text_extractor.py` parsing `.txt`, `.md`, `.markdown`, source code (`.py`, `.ts`, `.js`, etc.), and config (`.json`, `.yaml`, `.toml`) with exact 1-indexed line numbers, markdown heading hierarchy stacks, and code symbol boundaries.
  - Implemented `PDFExtractor` in `backend/app/extractors/pdf_extractor.py` using PyMuPDF (`pymupdf`) extracting text per page with 1-indexed page coordinates (`Page X of Y`), paragraph grouping, and scanned non-text PDF fallback detection (`NO_TEXT`).
  - Implemented `DocxExtractor` in `backend/app/extractors/docx_extractor.py` using `python-docx` extracting headings, paragraphs, and tables with section hierarchy retention.
  - Implemented `PptxExtractor` in `backend/app/extractors/pptx_extractor.py` using `python-pptx` extracting slide titles, body shapes, and speaker notes with strict slide coordinate isolation (`Slide X`).
  - Implemented extractor factory in `backend/app/extractors/factory.py` resolving appropriate extractors by file extension.
  - Implemented `StructureAwareChunker` in `backend/app/chunking/chunker.py` using a 350-token window with 50-token overlap, ensuring zero text bleeding across PPTX slides, preserving PDF page numbers, and attaching exact 1-indexed line ranges and parent headings.
  - Added unit test suites `backend/tests/test_extractors.py` (9 tests) and `backend/tests/test_chunker.py` (5 tests). Entire backend test suite passes with **26/26 tests passing**.

## [0.1.0-m2] - 2026-10-11

### Completed
- **Milestone 2 & Phase 2 — Directory Management & Discovery Engine**:
  - Implemented `DirectoryService` in `backend/app/services/directory_service.py` supporting directory path canonicalization, system root drive rejection (`C:\`, `/`), overlap conflict detection, and file discovery.
  - Implemented recursive directory scanner (`scan_files`) with SHA-256 fingerprinting, symlink confinement checks, and support for all target document extensions (`.pdf`, `.docx`, `.pptx`, `.md`, `.txt`, `.py`, `.ts`, `.json`, etc.).
  - Added SQLite schema domain models in `backend/app/db/models.py` (`DirectoryModel`, `DirectorySummary`, `DocumentModel`, `PassageModel`, `IndexJobModel`).
  - Implemented REST API route controllers in `backend/app/api/directories.py`:
    - `GET /api/directories`: lists registered directories with live document and passage counts.
    - `POST /api/directories`: validates and registers new directory root with initial scan and job creation.
    - `DELETE /api/directories/{id}`: unlinks directory from database while preserving physical files on disk.
    - `POST /api/directories/{id}/sync`: triggers incremental scan of single registered directory.
    - `POST /api/directories/sync-all`: triggers batch sync across all registered directories.
    - `POST /api/directories/pick`: native OS folder picker dialog bridge.
  - Added comprehensive test suite in `backend/tests/test_directories.py` with 12 passing tests across database, health, directory CRUD, conflicts, root drive rejection, and mocked native picker.
  - Wired live directory CRUD, sync, and native picker client functions into React frontend (`src/services/api.ts`, `src/components/DirectoriesModal.tsx`, `src/App.tsx`).

## [0.1.0-m1] - 2026-10-11

### Completed
- **Milestone 1 — Project Skeleton & Local Runtime**:
  - Implemented and verified SQLite database initialization in WAL mode (`findit.db`) enforcing foreign keys and full schema DDL matching `docs/DATABASE.md` (`directories`, `documents`, `passages`, `index_jobs`).
  - Added unit test suite `tests/test_database.py` validating WAL pragmas, schema tables, and cascade deletion.
  - Implemented `/api/health` diagnostic endpoint matching `docs/API.md` response contract, verified via unit test (`tests/test_health.py`) and live HTTP curl.
  - Configured FastAPI application with strict loopback binding (`127.0.0.1:8000`), CORS allowlisting (`5173`, `3000`), and startup lifespan database initialization.
  - Integrated `checkBackendHealth` in frontend `src/services/api.ts` and added runtime status indicators across both Hero and Results views in `src/App.tsx`.
  - Verified frontend build (`tsc -b && vite build`) and running dev server (`http://localhost:5173/`).

## [0.1.0-spec] - 2026-10-11

### Added
- **Product & System Specification**:
  - `docs/PRD.md`: Full Product Requirements Document detailing product vision, personas, core promise, visual language (ivory canvas, terracotta contours), in-place transition choreography, and non-goals.
  - `docs/REQUIREMENTS.md`: Comprehensive requirement catalog with classification tracking (Confirmed, Proposed, Constraints, Ambiguities).
  - `docs/TRD.md`: Technical Requirements Document covering extractors, chunking, 384D `all-MiniLM-L6-v2` embeddings, FAISS `IndexFlatIP`, BM25, RRF algorithm ($k=60$), and benchmark test query suite.
  - `docs/ARCHITECTURE.md`: Complete system topology, component boundaries, sequence diagrams for indexing and search pipelines, and frontend state machine.
  - `docs/API.md`: Strict loopback-bound REST API contracts for directory management, search, passage retrieval, and native OS folder navigation.
  - `docs/DATABASE.md`: SQLite schema DDL (`directories`, `documents`, `passages`, `index_jobs`), vector mapping, and atomic rebuild strategy.
  - `docs/SECURITY.md`: Comprehensive threat model, path traversal defenses, approved-root boundary confinement, and source file immutability guarantees.
  - `docs/ROADMAP.md`: 8-milestone delivery schedule with explicit exit criteria and acceptance checklist.
  - `docs/DECISIONS.md`: Approved Architectural Decision Records (ADR-001 through ADR-009).
  - `docs/RISKS.md`: Risk assessment register with concrete mitigation strategies.
- **Agent Governance & Environment**:
  - `AGENTS.md`: AI execution guidelines establishing user final authority, strict prohibition against AI committing/pushing, and documentation synchronization rules.
  - `.gitignore`: Configured workspace ignore rules for `notes/`, `Stitch/`, and `.agents/`.
