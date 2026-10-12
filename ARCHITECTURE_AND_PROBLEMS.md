# Semanty / FindIT — Architecture, System Design & Problems Report

> **Target Audience:** This document provides a complete, exhaustive breakdown of the **Semanty (FindIT)** repository for any software engineer or Large Language Model (LLM) with zero prior context. It covers the core problem statement, the complete technical architecture of all subsystems, how components communicate, and all architectural flaws, bugs, and redundancies present in the codebase.

---

## 1. Problem Statement & Motivation

### 1.1 The Desktop Search Bottleneck
Traditional desktop search mechanisms (such as Windows Search Indexer, macOS Spotlight, or standard filesystem grep) suffer from major limitations:
1. **Keyword Rigidity:** They rely on exact filename matches or exact substring lexical hits. If a user searches for `"tax return documents"`, a file titled `Form_1040_2024.pdf` containing `"Internal Revenue Service Adjusted Gross Income"` will often not match unless the exact words "tax return" appear verbatim.
2. **Loss of Context & Coordinate Blindness:** Traditional tools return a file as a monolithic unit. They do not tell the user *where* in a 200-page PDF or 80-slide presentation the answer was found, nor do they extract surrounding context.
3. **Format Fragmentation:** Reading presentations (`.pptx`), formatted documents (`.docx`), vector PDFs (`.pdf`), markdown notes (`.md`), and source code files (`.py`, `.ts`) usually requires separate tools or heavyweight enterprise software.
4. **Cloud / Privacy Trade-offs:** Commercial cloud-based semantic search tools upload private documents to third-party cloud vectors and LLM APIs, violating user privacy and confidentiality.

### 1.2 Semanty's Value Proposition
Semanty (internal code name: **FindIT**) is designed as a **100% local, privacy-first, desktop hybrid search engine**:
* **Semantic Recall:** Uses a local sentence-transformer (`all-MiniLM-L6-v2`) to map natural-language concepts into 384-dimensional dense vectors stored in a local **FAISS** index.
* **Lexical Precision:** Employs a custom **BM25** index with a technical-identifier tokenizer to match exact variable names, hashes, numbers, and jargon.
* **Reciprocal Rank Fusion (RRF):** Merges dense and lexical results using rank-based reciprocal score addition ($k=60$).
* **Structural Coordinates:** Tracks exact physical locations (Page $X$, Slide $Y$, Lines $A$–$B$, Section headings) so users can jump straight to the source passage.

---

## 2. System Architecture & Components

The repository is structured into three primary layers, plus a root entry point:
```
Semanty/
├── backend/          # FastAPI REST API (port 8000)
├── frontend/         # React 19 + TypeScript + Vite (port 5173)
├── cli/              # Standalone Python CLI engine
├── cli.py            # Root CLI wrapper
├── setup.bat         # Windows automated setup script
└── run.bat           # Windows runtime launcher
```

```
                     ┌────────────────────────────────┐
                     │    Frontend (React 19/Vite)    │
                     │         Port: 5173             │
                     └───────────────┬────────────────┘
                                     │ HTTP (Proxied /api/*)
                                     ▼
                     ┌────────────────────────────────┐
                     │     Backend (FastAPI/Uvicorn)  │
                     │         Port: 8000             │
                     └───────┬───────────────┬────────┘
                             │               │
            ┌────────────────┴──────┐        │
            ▼                       ▼        ▼
┌──────────────────────┐ ┌──────────────┐ ┌────────────────┐
│   FAISS Vector DB    │ │  BM25 Index  │ │ SQLite (WAL)   │
│ (backend/data/*.faiss│ │ (*.pkl)      │ │ (findit.db)    │
└──────────────────────┘ └──────────────┘ └────────────────┘

═════════════════════════════ DISCONNECTED ══════════════════════════════════

┌──────────────────────────────────────────────────────────────────────────┐
│                             CLI Subsystem                                │
│ (cli.py -> cli/pipeline.py -> cli/storage/ -> cli/.index_data/*)         │
│  - Has its own metadata.db (SQLite)                                      │
│  - Has its own faiss_index.bin (FAISS)                                   │
│  - Has its own bm25_index.bin (BM25)                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Subsystem Breakdown

### 3.1 Backend (`backend/app/`)
The backend is a FastAPI application exposing REST endpoints to manage directories, trigger background scans, and execute searches.

#### A. Database Layer (`app/db/`)
* **Engine:** SQLite with `PRAGMA journal_mode = WAL;`, `PRAGMA foreign_keys = ON;`, `PRAGMA synchronous = NORMAL;`.
* **Path:** `backend/data/findit.db`.
* **Tables:**
  1. `directories`: Approved folder roots added by the user (`directory_id`, `canonical_path`, `sync_status`).
  2. `documents`: Discovered files (`document_id`, `canonical_path`, `file_type`, `size_bytes`, `modified_time`, `content_fingerprint`).
  3. `passages`: Chunked passages (`chunk_id`, `document_id`, `chunk_ordinal`, `text`, `page_number`, `slide_number`, `start_line`, `end_line`, `vector_id`).
  4. `index_jobs`: Asynchronous indexing jobs (`job_id`, `directory_id`, `status`, `stage`, `files_processed`, `passages_created`).

#### B. Document Extraction Layer (`app/extractors/`)
* **ExtractorFactory (`factory.py`):** Inspects file extensions and instantiates the appropriate parser:
  * `PDFExtractor`: Uses `fitz` (`PyMuPDF`) to extract text per page, preserving 1-indexed `page_number`.
  * `DOCXExtractor`: Uses `python-docx` to extract text by paragraph and heading styles.
  * `PPTXExtractor`: Uses `python-pptx` to extract text per slide and shape, preserving 1-indexed `slide_number`.
  * `TextExtractor`: Reads UTF-8 code/text files, tracking 1-indexed `start_line`, `end_line`, and markdown `#` headings.

#### C. Chunking Layer (`app/chunking/`)
* **StructureAwareChunker (`chunker.py`):**
  * Target passage size: ~350 tokens (using heuristic word regex `\w+|[^\w\s]`).
  * Overlap: ~50 tokens.
  * Preserves hard boundaries: PPTX slides are chunked independently without bleeding across slides.

#### D. Embedding & Vector Index (`app/embeddings/`, `app/indexing/faiss_index.py`)
* **Model:** `sentence-transformers/all-MiniLM-L6-v2` producing 384-dimensional dense vectors.
* **Device Selection:** Auto-detects CUDA GPU; falls back to CPU.
* **Vector Normalization:** Strict unit L2 normalization ($v / \|v\|_2$).
* **FAISS Index:** `faiss.IndexIDMap2(faiss.IndexFlatIP(384))`. Using Inner Product on L2-normalized vectors guarantees exact Cosine Similarity while allowing arbitrary 64-bit integer IDs (`vector_id`) matching SQLite.

#### E. Lexical Search Index (`app/indexing/bm25_index.py`)
* **Model:** `RobustBM25Okapi` with Lucene-standard positive-smoothed IDF:
  $$\text{IDF}(w) = \ln\left(1 + \frac{N - n + 0.5}{n + 0.5}\right)$$
  (Prevents negative or 0.0 scores when a term occurs in $\ge 50\%$ of small corpora).
* **Tokenizer:** Identifier-aware regex parser splitting camelCase, snake_case, and file paths while preserving exact unified tokens.

#### F. Retrieval & Reciprocal Rank Fusion (`app/services/search_service.py`)
* Retrieves top $M=50$ candidates from FAISS (dense) and top $M=50$ from BM25 (lexical).
* Calculates RRF score:
  $$\text{RRF}(d) = \sum_{m \in \{\text{semantic}, \text{lexical}\}} \frac{1}{60 + \text{rank}_m(d)}$$
* Hydrates top candidates by querying SQLite to pull document path, filename, and coordinate badge (`"Slide 3"`, `"Page 4"`, `"Lines 12–45"`).

#### G. Sync & Background Worker (`app/sync/`)
* **SyncWorker (`worker.py`):** Spawns a background thread queue executing the pipeline:
  1. `SCANNING`: Traverses registered directories, checks file mtime/size.
  2. `EXTRACTING`: Runs format extractors.
  3. `CHUNKING`: Generates passages.
  4. `EMBEDDING`: Generates vectors in batches.
  5. `INDEXING`: Atomically commits SQLite passages, FAISS vectors, and BM25 index.

---

### 3.2 Frontend (`frontend/src/`)
A single-page React 19 application built with TypeScript, TailwindCSS, and Vite.
* **`App.tsx`:** Monolithic main component (733 lines) managing all state:
  * Active view: Hero search view vs. Results split view.
  * Modals: Directory management modal, Passage inspector modal.
  * Real-time sync polling: Polls `/api/sync/jobs` every 2 seconds when sync is active.
* **`services/api.ts`:** Axios/fetch client communicating with backend via Vite dev server reverse proxy (`/api/*` $\to$ `http://127.0.0.1:8000`).

---

### 3.3 CLI Subsystem (`cli/`)
A standalone terminal interface intended for terminal power-users.
* **`cli_app.py`:** Argument parser for commands: `index`, `search`, `interactive`, `stats`, `evaluate`, `clear`.
* **`pipeline.py` (`DocumentSearchEngine`):** Facade coordinating parsing, chunking, storage, and search.
* Uses the **Rich** Python library for terminal UI, colored tables, and progress bars.

---

## 4. Comprehensive Analysis of Flaws, Bugs & Redundancies

### 🔴 Critical Flaw 1: Split-Brain Architecture (CLI and Backend Disconnected)
**Description:** The project has two completely isolated, incompatible search engines existing in parallel within the same repository.
* The CLI writes and reads from: `cli/.index_data/metadata.db`, `cli/.index_data/faiss_index.bin`, and `cli/.index_data/bm25_index.bin`.
* The Backend writes and reads from: `backend/data/findit.db`, `backend/data/index.faiss`, and `backend/data/bm25.pkl`.
* **Incompatible Schemas:**
  * CLI SQLite schema has only 2 tables: `documents` and `chunks`.
  * Backend SQLite schema has 4 tables: `directories`, `documents`, `passages`, and `index_jobs`.
* **Incompatible Chunkers & Parsers:**
  * Backend produces rich metadata: `start_line`, `end_line`, `page_number`, `slide_number`, `section_heading`.
  * CLI produces basic `location_type` / `location_value` strings.

**Impact:** Documents indexed via the CLI are completely invisible to the Web UI. Documents indexed via the Web UI are completely invisible to the CLI. A user running both thinks the system has failed or lost data.

---

### 🔴 Critical Flaw 2: Blocking Sync Handlers in `directories.py` Freeze Uvicorn
**Location:** [`backend/app/api/directories.py`](file:///c:/Users/Gopi/Dev%20shit/Personal/Findit/Semanty/backend/app/api/directories.py)
**Code:**
```python
@router.post("/{directory_id}/sync")
def sync_directory_endpoint(directory_id: str):
    worker = get_sync_worker()
    job_id = worker.start_sync(directory_id=directory_id, background=False)  # <-- BLOCKS
    return {"message": "Sync completed", "job_id": job_id}
```
**Impact:** `background=False` runs file scanning, PDF extraction, and heavy PyTorch embedding synchronously inside the FastAPI request thread. Because Uvicorn handles requests in an event loop or worker thread, this freezes the server for minutes, causing health checks and search queries from the frontend to time out. The correct non-blocking version exists in `api/sync.py`, making the endpoint in `directories.py` a dangerous trap.

---

### 🟠 Major Flaw 3: Inconsistent Ranking Logic & Redundant Double-Sort
**Location:** [`frontend/src/App.tsx`](file:///c:/Users/Gopi/Dev%20shit/Personal/Findit/Semanty/frontend/src/App.tsx)
**Code:**
1. In the **Hero View** (line 462):
   ```tsx
   onClick={() => setSortBy('semantic')} // Only sets state, DOES NOT query backend!
   ```
2. In the **Results View** (line 544):
   ```tsx
   onClick={() => handleRankingModeChange('hybrid')} // Triggers re-fetch from backend
   ```
3. **Double-Sort Redundancy:**
   The backend's `search_service.py` executes FAISS and BM25, calculates RRF scores, sorts items descending, and returns them in rank order.
   However, the frontend ignores this pre-computed order and runs a client-side `useMemo` (`sortedResults`) to sort the array *again* using `item.semantic_rank` or `item.lexical_rank`. If the mode is `hybrid`, it re-sorts by `item.hybrid_rank`. This client-side re-sort is redundant and creates split-brain ranking rules between server and client.

---

### 🟠 Major Flaw 4: Incompatible Mode Terminology (Semantic vs Dense, Lexical vs BM25)
* In `cli/cli_app.py`: Valid modes are `--mode dense`, `--mode bm25`, `--mode hybrid`.
* In `backend/app/services/search_service.py`: Valid modes are `"semantic"`, `"lexical"`, `"hybrid"`.
* In `frontend/src/types/index.ts`: Modes are `'hybrid' | 'semantic' | 'lexical'`.
**Impact:** A developer or user writing scripts or switching between CLI and API encounters confusing errors (`ValueError: Unknown mode 'dense'`).

---

### 🟠 Major Flaw 5: Fragile Prefix Detection for File Operations
**Location:** [`frontend/src/services/api.ts`](file:///c:/Users/Gopi/Dev%20shit/Personal/Findit/Semanty/frontend/src/services/api.ts#L277)
**Code:**
```ts
const isDocId = pathOrDocumentId.startsWith('doc_');
const payload = isDocId ? { document_id: pathOrDocumentId } : { path: pathOrDocumentId };
```
**Impact:** The frontend deduces whether an argument is a database ID or an absolute filesystem path purely by checking if the string starts with `"doc_"`. If a user indexes a folder or file named `doc_report.pdf` or `c:\documents\doc_2024\`, the system misinterprets the real filesystem path as an ID, fails the database lookup, and refuses to open the folder in Windows Explorer.

---

### 🟡 Moderate Flaw 6: Search Errors Silently Swallowed
**Location:** [`frontend/src/App.tsx`](file:///c:/Users/Gopi/Dev%20shit/Personal/Findit/Semanty/frontend/src/App.tsx#L88-L96)
**Code:**
```tsx
try {
  const data = await searchPassages(searchTerm.trim(), 20, 0, mode);
  setResults(data.results);
} catch {
  // Empty catch block!
} finally {
  setIsLoading(false);
}
```
**Impact:** If the backend crashes, PyTorch runs out of memory, or SQLite hits a busy timeout, the frontend catches the error and does nothing. The user is presented with a blank results page with zero error messages or indicators.

---

### 🟡 Moderate Flaw 7: Backend Implements Pagination, Frontend Ignores It
* The backend search endpoint accepts `limit` and `offset` and returns:
  `SearchResponse(total_available=..., results=..., next_offset=...)`.
* In `frontend/src/App.tsx`:
  The query is hard-coded to:
  ```ts
  searchPassages(searchTerm.trim(), 20, 0, mode);
  ```
* There is no "Next Page", no "Load More", and no infinite scrolling implemented. If a search matches 150 passages across 30 documents, the user is permanently locked to seeing only the top 20.

---

### 🟡 Moderate Flaw 8: Directory Registration Creates Orphaned Documents
**Location:** [`backend/app/services/directory_service.py`](file:///c:/Users/Gopi/Dev%20shit/Personal/Findit/Semanty/backend/app/services/directory_service.py)
**Mechanism:**
When a directory is registered, `register_directory()` performs a quick scan and inserts documents with `extraction_status = 'PENDING'` and a generated `document_id`.
Later, when `SyncWorker` runs full indexing, it scans files again and issues:
```sql
INSERT INTO documents (...) VALUES (...)
ON CONFLICT(canonical_path) DO UPDATE SET document_id = excluded.document_id;
```
Updating the `document_id` of an existing document record breaks foreign key linkage (`FOREIGN KEY (document_id) REFERENCES documents(document_id)`) to any passages previously extracted, potentially leaving orphaned records in the database.

---

### 🟡 Moderate Flaw 9: CLI Progress Bar Visual Corruption
**Location:** [`cli/pipeline.py`](file:///c:/Users/Gopi/Dev%20shit/Personal/Findit/Semanty/cli/pipeline.py#L140)
**Code:**
```python
self._rebuild_search_indices(
    status_callback=lambda msg: print(f"\n[SearchEngine] {msg}", flush=True)
)
```
**Impact:** Inside the Rich progress display context (`rich.progress.Progress`), invoking standard Python `print()` prints raw newline characters to stdout, breaking ANSI cursor positions and causing the progress bars to duplicate and smear across the terminal screen.

---

### 🟡 Moderate Flaw 10: Hard-Coded CLI Paths (No `--data-dir` Flag)
**Location:** [`cli/config.py`](file:///c:/Users/Gopi/Dev%20shit/Personal/Findit/Semanty/cli/config.py)
**Impact:** `data_dir` is statically defined relative to `__file__`. There is no CLI flag to specify a custom storage directory or point the CLI directly at `backend/data/findit.db`.

---

### 🟢 Minor Flaw 11: Misleading Coordinate Label Format
**Location:** [`backend/app/services/search_service.py`](file:///c:/Users/Gopi/Dev%20shit/Personal/Findit/Semanty/backend/app/services/search_service.py#L107)
**Code:**
```python
if end_page is not None and end_page != page_number:
    return f"Page {page_number} of {end_page}"
```
**Impact:** If a passage spans from page 4 to page 6, `build_location_label` outputs `"Page 4 of 6"`. To an end user, this reads like *"Page 4 out of 6 total pages in the PDF"*, when it actually means *"spanning across pages 4 to 6"*. It should be formatted as `"Pages 4–6"`.

---

### 🟢 Minor Flaw 12: Monolithic Frontend State Management
**Location:** [`frontend/src/App.tsx`](file:///c:/Users/Gopi/Dev%20shit/Personal/Findit/Semanty/frontend/src/App.tsx)
**Impact:** `App.tsx` contains 733 lines handling modals, search submission, debouncing, polling interval cleanup, keyboard shortcuts, and view switching. It lacks modularity and should be decomposed into dedicated custom hooks (`useSearch`, `useDirectorySync`, `usePassageDetail`).

---

### 🟢 Minor Flaw 13: Windows Script Path Failure with Spaces
**Location:** [`setup.bat`](file:///c:/Users/Gopi/Dev%20shit/Personal/Findit/Semanty/setup.bat)
**Code:**
```bat
set "PROJECT_ROOT=%~dp0.."
cd /d %PROJECT_ROOT%\backend
```
**Impact:** On Windows, if the repository path contains a space (such as `C:\Users\Gopi\Dev shit\Personal\...`), the trailing backslash from `%~dp0` concatenated with `..` causes command parsing in `cmd.exe` to fail with `from was unexpected at this time`.

---

## 5. Architectural Comparison Matrix (Backend vs. CLI)

| Feature / Dimension | Backend (`backend/`) | CLI (`cli/`) | Recommended Unified Standard |
| :--- | :--- | :--- | :--- |
| **Primary Interface** | FastAPI REST + React 19 Web UI | Python `argparse` + Rich Console | CLI should call Backend REST or share unified library |
| **Data Directory** | `backend/data/` | `cli/.index_data/` | Single unified directory configurable via ENV / Flag |
| **Database File** | `findit.db` | `metadata.db` | Single SQLite database |
| **Database Schema** | 4 Tables (`directories`, `documents`, `passages`, `index_jobs`) | 2 Tables (`documents`, `chunks`) | The 4-table schema (supports background jobs & roots) |
| **Vector Index File** | `index.faiss` | `faiss_index.bin` | Single FAISS index |
| **Lexical Index File**| `bm25.pkl` | `bm25_index.bin` | Single BM25 index |
| **Ranking Mode Names**| `semantic`, `lexical`, `hybrid` | `dense`, `bm25`, `hybrid` | `semantic`, `lexical`, `hybrid` (or aliases for both) |
| **Location Coordinates**| Rich (Pages, Slides, Lines, Headings) | Basic string | Rich coordinates |
| **Chunking Engine** | `StructureAwareChunker` | `TextChunker` | `StructureAwareChunker` |

---

## 6. How to Unify and Resolve All Issues (Roadmap)

1. **Unify Storage & Engine Core:**
   Move `extractors`, `chunking`, `embeddings`, `indexing`, and `db` into a top-level shared package `core/` (or have `cli/` directly import from `backend/app/`).
2. **Make the CLI Share the Backend Store:**
   Update `cli/config.py` to default its paths to `backend/data/` (or accept an `--api` flag to query the backend over HTTP).
3. **Remove Blocking Routes:**
   Delete the synchronous sync routes in `backend/app/api/directories.py` and enforce usage of the async worker endpoints in `backend/app/api/sync.py`.
4. **Fix Frontend Ranking:**
   Remove client-side sorting (`sortedResults`) in `App.tsx` and trust the backend's pre-computed hybrid RRF ordering. Wire the Hero view mode buttons to properly update search parameters.
5. **Implement Pagination & Error Handling:**
   Add infinite scroll or a "Load More" button in `App.tsx` utilizing `next_offset`, and add a toast / error alert in the search catch block.
6. **Correct Location Formatting:**
   Update `build_location_label` in `search_service.py` to return `Pages {start}–{end}` instead of `Page {start} of {end}`.
