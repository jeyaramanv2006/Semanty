# System Architecture & Technical Design — FindIT

> **Document Status**: `APPROVED` | **Version**: 1.0  
> **Last Synchronized**: Based on Comprehensive Research & Technical Analysis  

---

## 1. System Topology & Architectural Overview

FindIT is architected as a **local-first desktop search engine** with a Python Textual TUI as its primary interactive client and a supported React + Vite client. Both communicate via HTTP/REST with one local Python + FastAPI backend service. The backend is the sole owner of indexing, storage, retrieval, and security policy.

```mermaid
graph TB
    subgraph UI_Client ["Interactive Clients"]
        TUI["Textual TUI (Primary)"]
        HomeView["Home Search View"]
        ResultsView["Results & Passage View"]
        ModalManager["Indexed Directories Modal"]
        StateEngine["Search & Async Job State Engine"]
    end

    subgraph Local_Backend ["Local Python Backend (FastAPI @ 127.0.0.1)"]
        APIGateway["REST API Router & Security Boundary"]
        JobManager["Background Indexing & Sync Engine"]
        SearchPipeline["Hybrid Search & Rank Fusion Pipeline"]
        ExtractorPool["Format Extractors & Chunking Pool"]
        OSBridge["OS File & Folder Integration Bridge"]
    end

    subgraph Storage_Layer ["Persistent Storage Layer"]
        SQLiteDB[("SQLite 3 (WAL)\nMetadata, Passages, Jobs")]
        FAISSStore[("FAISS IndexFlatIP\n384D Normalized Vectors")]
        BM25Store[("BM25 Lexical Store\nInverted Term Index")]
    end

    subgraph User_FS ["User Local Filesystem"]
        ApprovedRoots["User-Approved Directory Roots\n(PDF, PPTX, MD, DOCX, Code, etc.)"]
    end

    TUI -->|HTTP / JSON via Loopback| APIGateway
    UI_Client -->|HTTP / JSON via Loopback| APIGateway
    APIGateway --> SearchPipeline
    APIGateway --> JobManager
    APIGateway --> OSBridge
    JobManager --> ExtractorPool
    ExtractorPool -->|Read Only| ApprovedRoots
    ExtractorPool --> SQLiteDB
    ExtractorPool --> FAISSStore
    ExtractorPool --> BM25Store
    SearchPipeline --> FAISSStore
    SearchPipeline --> BM25Store
    SearchPipeline --> SQLiteDB
    OSBridge -->|Native File Explorer| ApprovedRoots
```

---

## 2. Component Boundaries & Responsibilities

### 2.1 Frontend Client (React + TypeScript)
- **UI State Machine**: Orchestrates the view transitions between the homepage and the results view.
- **Continuous Header Animation**: Smoothly morphs the centered search input and logo into a compact persistent header upon submission.
- **Passage Inspector**: Presents faithful extracted text with query highlights and location coordinates.
- **Directory Manager Modal**: Manages registered folder roots, triggers sync operations, and monitors real backend job telemetry.
- **Concurrency & Race Condition Guard**: Uses `AbortController` and sequential request IDs to ensure older queries never overwrite newer search results.

### 2.2 Backend Service (FastAPI)
- **Security Boundary**: Enforces loopback binding (`127.0.0.1`), validates path canonicalization, and ensures requests remain within approved directory boundaries.
- **Document Extractors**: Modular parser suite extracting raw text and line/page/slide coordinates across supported formats.
- **Chunking Engine**: Segments extracted documents into location-aware passages (~250–500 tokens) with 20% overlap.
- **Embedding Service**: Executes local inference with `sentence-transformers/all-MiniLM-L6-v2`, returning 384-dimensional normalized vectors.
- **Retrieval & Fusion Engine**: Queries FAISS and BM25 concurrently, merges candidate pools using Reciprocal Rank Fusion ($k=60$), and hydrates metadata from SQLite.
- **OS Integration Bridge**: Dispatches native OS commands (e.g., `explorer.exe /select,` on Windows, `open -R` on macOS, `xdg-open` on Linux) to safely reveal files in their host directories.

### 2.3 Textual TUI (Primary Interactive Client)
- Uses the REST API only; it does not open the backend database or index files directly.
- Presents a persistent source/job context, hybrid result list, and selected-passage inspector on wide terminals, with navigable overlays/views on narrow terminals.
- Owns keyboard routing and focus, request identity/cancellation, selection by stable chunk ID, pagination, and recovery from backend or job errors.
- Starts and stops a backend child process only when it owns that process; an already-running backend is never terminated by the TUI.

---

## 3. Data Flow Pipelines

### 3.1 Indexing Pipeline Flow
```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Frontend Client
    participant API as FastAPI Backend
    participant Worker as Background Indexer
    participant Extractor as Text Extractor & Chunker
    participant ML as all-MiniLM-L6-v2
    participant DB as SQLite DB
    participant Indices as FAISS & BM25

    User->>UI: Selects Directory to Add
    UI->>API: POST /api/directories (canonical_path)
    API->>DB: Record Directory Entry (status: PENDING)
    API-->>UI: 201 Created (directory_id, job_id)
    API->>Worker: Dispatch Indexing Task

    loop Directory Scanning & Processing
        Worker->>Worker: Validate Path Boundary & Scan Files
        Worker->>Extractor: Extract Text & Structural Coordinates
        Extractor-->>Worker: Raw Text + Location Metadata
        Worker->>Worker: Structure-Aware Chunking (Passages)
        Worker->>ML: Generate 384D Embeddings (Batched)
        ML-->>Worker: Normalized Float32 Vectors
        Worker->>DB: Insert Documents & Passages (Batch)
        Worker->>Indices: Append FAISS Vectors & BM25 Postings
        Worker->>DB: Update Job Progress (Files Processed / Total)
    end

    Worker->>DB: Update Directory (status: IDLE, last_sync_at)
    UI->>API: Poll GET /api/jobs/{job_id}
    API-->>UI: 200 OK (status: COMPLETED, counts)
```

---

### 3.2 Query & Hybrid Retrieval Pipeline Flow
```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Search Interface
    participant API as Search API Endpoint
    participant ML as Embedding Model
    participant FAISS as FAISS (IndexFlatIP)
    participant BM25 as BM25 Engine
    participant RRF as Rank Fusion Engine
    participant DB as SQLite Store

    User->>UI: Enters Query & Presses Enter
    UI->>UI: Trigger 350-500ms Transition to Results View
    UI->>API: POST /api/search (query, limit: 10, offset: 0)
    
    par Concurrently Process Retrievers
        API->>ML: Embed Query (384D, Normalized)
        ML-->>API: Query Vector
        API->>FAISS: Search Nearest Neighbors (Top 50)
        FAISS-->>API: Top 50 Vector IDs + Cosine Scores
    and BM25 Term Retrieval
        API->>BM25: Query Inverted Index (Top 50)
        BM25-->>API: Top 50 Chunk IDs + BM25 Scores
    end

    API->>RRF: Compute Reciprocal Rank Fusion (k=60)
    RRF-->>API: Unified Ranked Candidate List
    API->>DB: Hydrate Passages & Document Metadata (Top 10)
    DB-->>API: Hydrated Passage Cards & Source Locations
    API-->>UI: 200 OK (total_available, results: Top 10)
    UI-->>User: Render Unified Hybrid Passage List
```

---

## 4. Frontend Component & State Architecture

### 4.1 Component Hierarchy
```text
App
React client
├── HomeSearch (Visible in "home" mode)
│   ├── LogoBrand
│   ├── TaglineDisplay ("Find what you remember.")
│   └── CenteredSearchInput
├── CompactSearchHeader (Visible in "results" mode)
│   ├── CompactLogo
│   ├── HeaderSearchInput
│   └── DirectoryModalTrigger (Folder Icon)
├── SearchResultsContainer
│   ├── SearchResultsSummary (e.g. "7 matching passages across 5 files")
│   ├── SearchResultsList
│   │   └── SearchResultRow (Repeated per passage)
│   │       ├── FileTypeBadge
│   │       ├── FileMeta (Name, Location Badge, Abbreviated Path)
│   │       ├── PassageSnippetPreview
│   │       └── OpenFolderAction (Stops propagation)
│   ├── ShowMorePaginationControl
│   ├── EmptyResultsState
│   ├── LoadingResultsState
│   └── SearchErrorState
├── PassageInspectorModal (Triggered on row click)
│   ├── ModalHeader (Filename, Location Label, Path)
│   ├── FullPassageText (Query terms highlighted)
│   └── ActionFooter (Close, Open in Folder)
└── IndexedDirectoriesModal (Triggered via folder icon)
    ├── ModalHeader (Summary Counts, Sync All Button)
    ├── DirectoryList
    │   └── DirectoryRow (Sync, Remove, File Count, Status)
    ├── AddDirectoryButton (OS Picker Trigger)
    └── RealtimeJobProgressIndicator

Textual TUI
├── Search input and persistent result list
├── Directory/job context panel
├── Passage inspector view
├── Directory and sync command palette
└── Contextual help and error/recovery overlays
```

### 4.2 State Machine & Transition Logic
1. **View States**:
   - `HOME`: Clean viewport, centered search bar, hero branding.
   - `TRANSITIONING`: In-place animation running for 350–500ms; logo and search bar smoothly translate and scale toward the top header; query preserved; results summary begins fading in.
   - `RESULTS`: Header pinned at top, result stream populated, pagination active.
2. **Race Condition Prevention**:
   - Every submitted query increments an internal `activeRequestId`.
   - Before firing a new query, any running `AbortController.abort()` is executed.
   - When an API response returns, if its request ID does not match the active ID, the payload is silently dropped to prevent stale results from overwriting newer queries.

---

## 5. Storage & Index Lifecycle Architecture

### 5.1 Storage Layout on Disk
FindIT stores all internal application data inside a dedicated local application data directory (e.g., `~/.findit/` or `%APPDATA%/FindIT/`):
```text
~/.findit/
├── findit.db           # SQLite 3 Database (WAL mode)
├── findit.db-wal       # SQLite Write-Ahead Log
├── findit.db-shm       # SQLite Shared Memory
├── vector_index.faiss  # Serialized FAISS IndexFlatIP
├── bm25_index.bin      # Serialized BM25 Inverted Index
└── models/             # Cached sentence-transformers weights
```

### 5.2 Atomic Synchronization & Rebuild Guarantees
- **Index-Only Removal**: When a user removes a directory, SQLite deletes the directory entry, cascade-deleting associated documents and passages. The backend then rebuilds or prunes the FAISS and BM25 indices to maintain strict 1-to-1 parity.
- **Full Index Reconstruction**: In the event of application crash or index file corruption, the backend can rebuild the FAISS vector index and BM25 inverted index directly from the `passages` table in SQLite without re-reading the source files on disk.
