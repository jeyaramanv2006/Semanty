# FindIT

> **"Find what you remember. Whatever you remember, find where it belongs."**

[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Node: 18+](https://img.shields.io/badge/Node.js-18%2B-green.svg)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/Frontend-React_19_+_Vite-61DAFB.svg)](https://vitejs.dev/)
[![Privacy: Local-First](https://img.shields.io/badge/Privacy-Local--First-success.svg)](#security-and-privacy)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

**FindIT** is a local-first, privacy-preserving document search engine designed to run entirely on your local machine. Its primary interactive client is a keyboard-first Textual TUI; a supported React client remains available for browser-based local use.

The FastAPI backend is the single source of truth for indexing, SQLite metadata, FAISS vectors, BM25 retrieval, synchronization, and security boundaries. All clients use its local REST API and display one unified hybrid-ranked result list.

### The Problem
Knowledge workers, researchers, and developers accumulate thousands of local files—research PDFs, presentation slide decks, technical specifications, Markdown notes, source code, and configuration files. Traditional desktop search tools (such as Windows Search, macOS Spotlight, or command-line `grep`) fail because they demand exact filename recall or verbatim keyword matches.

Human memory does not work in exact strings; it works through **associative concepts, themes, and fragmented recollections**:
- *"The PDF where I read about token rotation and session invalidation."*
- *"The presentation slide explaining our load-balancing tiers and reverse proxy."*
- *"The config file setting up the isolated database network binding."*
- *"The note where we debated local vector indexing versus SQLite full-text search."*

### The Solution
FindIT bridges human memory with your local storage. You select the local folders to index. FindIT extracts and segments their content into semantic passages, pairs dense vector embeddings (`all-MiniLM-L6-v2` via FAISS) with lexical keyword matching (`BM25`), and unifies them using **Reciprocal Rank Fusion (RRF)** into a single ranked list.

### Core Promise
- **Search by meaning**: Find files using natural descriptions and conceptual recall.
- **Exact source coordinates**: Every result pinpoints the exact `Page X`, `Pages X–Y`, `Slide N`, `Lines X–Y`, or `Section Heading`.
- **Zero hallucinations**: FindIT returns the actual extracted passage, never generative AI summaries.
- **Private & Local**: Embeddings, indices, and database files remain strictly on your machine (`127.0.0.1`). Zero cloud APIs, zero tracking, and zero telemetry.
- **Strictly Non-Destructive**: FindIT is an index, not a file manager. Your original files are never modified, moved, or deleted.

---

## Table of Contents

- [Visual Demo](#visual-demo)
- [Features](#features)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Prerequisites and Installation](#prerequisites-and-installation)
- [Usage and Quickstart](#usage-and-examples)
- [Project Structure](#project-structure)
- [Testing and Quality Assurance](#testing-and-quality-assurance)
- [Configuration](#configuration)
- [Security and Privacy](#security-and-privacy)
- [Project Status & Roadmap](#project-status--roadmap)
- [Known Limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)

---

## Visual Demo

### 1. Hybrid Search & Ranked Passage Results
![FindIT Search Results](./docs/assets/findit-results.png)
*Results view featuring a persistent header, authoritative hybrid-ranked passage cards with precise physical coordinates, and native OS folder reveal.*

### 2. Search Canvas & Hero Interface
![FindIT Search Homepage](./docs/assets/findit-home.png)
*Minimalist search canvas with real-time index telemetry, folder count badges, and terracotta contour background.*

### 3. Indexed Folders Management
![FindIT Directories Modal](./docs/assets/findit-directories.png)
*Directory manager dialog supporting native OS directory selection, real-time background sync progress, and document counters.*

---

## Features

- **Primary Textual TUI**: Search, inspect passages, manage approved directories, monitor real indexing jobs, open source files, and recover from errors without leaving the terminal.

- **Hybrid Semantic + Lexical Retrieval**:
  - **Dense Vector Search**: Powered by `sentence-transformers/all-MiniLM-L6-v2` and `FAISS` (`IndexFlatIP`) for concept-based and associative recall.
  - **Lexical Keyword Search**: Powered by `BM25` for exact token matches, snake_case symbols, variable names, and configuration keys.
  - **Reciprocal Rank Fusion (RRF, $k=60$)**: Dynamically fuses semantic and lexical candidate pools into a single unified ranked list.
  - **Live Ranking Strategy Toggles**: Filter and re-sort search results on the fly between **Hybrid (RRF)**, **Pure Semantic**, or **Pure Lexical** modes.
- **Granular Passage-Level Provenance**:
  - Highlights the exact portion of the document where your concept lives.
  - Formats physical location coordinates:
    - **PDF**: `Page X` or `Pages X–Y` (e.g., `Pages 18–20`)
    - **PowerPoint**: `Slide N` (e.g., `Slide 7`)
    - **Markdown / Plain Text / Code**: `Lines X–Y` (e.g., `Lines 112–138`)
    - **Word Documents (DOCX)**: `Section: <Heading>`
- **Native OS File Explorer Integration**:
  - Dedicated **"Open in folder"** action commands the native operating system file manager (`explorer.exe` on Windows, `open -R` on macOS, `xdg-open` on Linux) to reveal and highlight the exact file.
  - Optional **"Open file"** action launches the document in the user's default system reader.
- **In-App Passage Inspector**:
  - Inspect the full, unvarnished extracted text inside a modal with search query highlighting and surrounding chunk context before opening the host application.
- **Indexed Directory Manager & Native Picker**:
  - Register folders via manual path entry or using the native OS directory selection dialog.
  - Monitor real-time background sync progress across pipeline stages: `SCANNING` &rarr; `EXTRACTING` &rarr; `EMBEDDING` &rarr; `INDEXING` &rarr; `IDLE`.
- **Multi-Format Document Parsing**:
  - Built-in extractors for **PDF** (`PyMuPDF`), **DOCX** (`python-docx`), **PPTX** (`python-pptx`), **Markdown** (`.md`), **Plain Text** (`.txt`), **Source Code** (`.py`, `.ts`, `.js`, `.tsx`, `.jsx`, `.html`, `.css`), and **Config Files** (`.json`, `.yaml`, `.yml`, `.toml`).
- **Zero Cloud Leakage & Non-Destructive**:
  - All inference runs locally on CPU or NVIDIA GPU via CUDA.
  - Directory registrations and removals affect **only** FindIT's internal SQLite and vector indices—original documents on disk are never altered or deleted.

---

## Architecture

FindIT is architected as a modular, local-first client-service system designed for single-user desktop operation. All computation, model inference, indexing, and persistent storage occur strictly on the user's workstation over the local loopback network (`127.0.0.1`).


### Component Architecture & Responsibilities

1. **Presentation Tier (React 19 + TypeScript)**: Morphs the centered hero input into a sticky header on query submission, presents passage cards with location badges, and provides an in-app text inspector.
2. **Local Backend Service (FastAPI)**: Enforces loopback security (`127.0.0.1`), canonicalizes file paths, orchestrates document extractors, chunks passages, executes embedding inference, and fuses search results.
3. **Persistence Tier (`backend/data/`)**: SQLite 3 in WAL mode persists folder registrations, document metadata, unedited passage texts, and job state. Vectors are indexed in FAISS (`IndexFlatIP`), while keyword tokens are stored in an inverted BM25 index.

> For in-depth architectural specifications, sequence diagrams, and lifecycle documentation, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DATABASE.md](docs/DATABASE.md).

---

## Technology Stack

| Component | Technology | Role & Justification |
| :--- | :--- | :--- |
| **Frontend Framework** | **React 19 & TypeScript** | Componentized UI with strict type safety and responsive state machines. |
| **Frontend Tooling** | **Vite** | Fast local development server, instant Hot Module Replacement (HMR). |
| **Styling & Icons** | **Tailwind CSS & Lucide React** | Warm ivory/terracotta aesthetic, custom contour canvas, accessible icon set. |
| **Backend API** | **FastAPI (Python 3.10+)** | High-performance asynchronous REST API bound strictly to loopback (`127.0.0.1`). |
| **Web Server** | **Uvicorn** | ASGI server handling concurrent local requests. |
| **Dense Vector Model** | **Sentence Transformers (`all-MiniLM-L6-v2`)** | Lightweight (384-dimensional) high-quality semantic embeddings running locally. |
| **Vector Search Engine**| **FAISS (`IndexFlatIP`)** | Exact cosine inner-product nearest neighbor search on L2-normalized vectors. |
| **Lexical Engine** | **Rank-BM25** | Exact keyword and code identifier matching. |
| **Rank Fusion** | **Reciprocal Rank Fusion (RRF)** | Rank-based combination formula ($k=60$) combining FAISS and BM25 candidate pools. |
| **Relational Metadata** | **SQLite 3 (WAL mode)** | Single-file transactional database tracking folders, document state, passages, and sync jobs. |
| **Document Parsers** | **PyMuPDF, python-docx, python-pptx** | High-fidelity text and structural coordinate extraction across office and document formats. |

> For comprehensive technical requirements and dependency rationale, see [docs/TRD.md](docs/TRD.md).

---

## Prerequisites and Installation

### System Requirements
- **Operating System**: Windows 10/11, macOS, or Linux.
- **Python**: Version `3.10` or higher (`python --version`).
- **Node.js**: Version `18+` LTS and npm (`node --version`).
- **Hardware (Optional)**: NVIDIA GPU with CUDA drivers for accelerated vector embeddings (CPU fallback is automatic).

---

### Option A: One-Click Launch (Windows)

FindIT includes automated batch runners that detect missing environments, install dependencies, and launch the primary terminal client:

1. Clone or download the repository:
   ```bash
   git clone https://github.com/jeyaramanv2006/FindIT.git
   cd FindIT
   ```

2. Run the universal launcher:
   ```cmd
   run.bat
   ```
   *On first run, `run.bat` automatically invokes `scripts\setup.bat`, sets up the Python virtual environment, installs backend and TUI packages (auto-detecting CUDA), installs frontend dependencies, and launches the Textual client. The TUI starts the backend only when it is not already running.*

---

### Option B: Manual Setup & Execution

#### 1. Backend Setup

```bash
cd backend

# Create and activate Python virtual environment
python -m venv .venv

# Windows activation:
.venv\Scripts\activate
# macOS/Linux activation:
# source .venv/bin/activate

# Upgrade pip and install backend dependencies
pip install --upgrade pip
pip install -r requirements.txt

# (Optional) Install PyTorch with CUDA acceleration if using an NVIDIA GPU:
# pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# Start the primary Textual client from the repository root
cd ..
python -m tui
```

#### 2. Optional Browser Client

In a new terminal:

```bash
cd frontend

# Install npm dependencies
npm install

# Start Vite local development server
npm run dev
```

The frontend will start at **`http://localhost:5173`**.

---

## Usage and Examples

### TUI Workflow

1. Run `run.bat` or `scripts\start-tui.bat`.
2. Press `a` to select and register an approved folder; indexing runs in the background.
3. Type a remembered concept and press `Enter` to search the unified hybrid index.
4. Use arrow keys or `j`/`k` to select a passage; press `Enter` to inspect it.
5. Press `o` to open the source document or `f` to reveal it in the native file manager.
6. Press `s` to sync the selected source, `S` to sync all, `?` for help, and `q` to exit.

The browser client remains available for development with `scripts\start-web.bat`.

---

## Project Structure

```text
FindIT/
├── .agents/                   # Local AI agent guidelines and execution rules
├── backend/                   # Python FastAPI Backend Service
│   ├── app/
│   │   ├── api/               # REST API endpoints (health, search, directories, passages, sync)
│   │   ├── chunking/          # Structure-aware passage chunking algorithms
│   │   ├── core/              # Global configuration, path resolvers, constants
│   │   ├── db/                # SQLite connection manager, WAL config, schema.sql
│   │   ├── embeddings/        # SentenceTransformer embedding engine (all-MiniLM-L6-v2)
│   │   ├── extractors/        # Parsers for PDF, DOCX, PPTX, Markdown, Code, Config
│   │   ├── indexing/          # FAISS vector store and BM25 lexical inverted index managers
│   │   ├── services/          # Hybrid search coordinator, RRF fusion algorithm
│   │   ├── sync/              # Background directory scanner and job state engine
│   │   └── main.py            # FastAPI application factory and exception handlers
│   ├── data/                  # Local persistent data directory (git-ignored)
│   │   ├── findit.db          # SQLite database (metadata, passages, jobs)
│   │   ├── index.faiss        # FAISS vector index (384D normalized float32)
│   │   └── bm25.pkl           # Pickled BM25 lexical index
│   ├── tests/                 # Automated pytest test suite
│   ├── requirements.txt       # Python dependencies
│   └── run.py                 # Backend startup entrypoint script
├── docs/                      # Authoritative project specifications & documentation
│   ├── assets/                # Application UI screenshots and preview images
│   ├── API.md                 # Full REST API contract
│   ├── ARCHITECTURE.md        # Technical topology, data flow, component boundaries
│   ├── DATABASE.md            # SQLite schema, tables, and index lifecycles
│   ├── DECISIONS.md           # Architectural Decision Records (ADRs)
│   ├── PRD.md                 # Product Requirements Document
│   ├── REQUIREMENTS.md        # Functional and non-functional requirements
│   ├── RISKS.md               # Risk register and mitigations
│   ├── ROADMAP.md             # Project milestones and delivery phases
│   ├── SECURITY.md            # Security architecture and threat model
│   └── TRD.md                 # Technical Requirements Document
├── frontend/                  # React 19 + TypeScript Frontend (Vite)
│   ├── src/
│   │   ├── components/        # UI components (Result cards, modals, canvas)
│   │   │   ├── DirectoriesModal.tsx     # Folder registration & sync modal
│   │   │   ├── PassageInspectorModal.tsx# In-app full passage viewer
│   │   │   ├── SearchResultCard.tsx     # Result card with location badges
│   │   │   ├── TerracottaCanvas.tsx     # Custom contour line background
│   │   ├── services/          # API client communicating with backend
│   │   ├── types/             # TypeScript data contracts and interfaces
│   │   ├── App.tsx            # Main app shell & view state transition choreography
│   │   └── index.css          # Design system tokens and styling
│   ├── package.json           # Frontend dependencies & scripts
│   └── vite.config.ts         # Vite build configuration
├── scripts/                   # Helper automation scripts
│   ├── setup.bat              # Automated environment and dependencies installer
│   ├── start-tui.bat          # Primary Textual client launcher
│   ├── start-backend.bat      # Dedicated backend launcher
│   ├── start-frontend.bat     # Dedicated frontend launcher
│   └── start-web.bat          # Browser development launcher
├── tui/                       # Primary Textual terminal client
│   ├── api.py                 # Local REST client
│   ├── process.py             # Backend process ownership
│   ├── app.py                 # Search workspace and interactions
│   └── tests/                 # TUI state and layout tests
├── run.bat                    # Universal one-click application launcher
├── AGENTS.md                  # Development principles and workflow protocols
└── README.md                  # Project documentation overview
```

---

## Testing and Quality Assurance

### Automated Testing

The backend includes a comprehensive `pytest` test suite covering extraction, chunking, indexing, hybrid retrieval, OS actions, and directory synchronization:

```bash
cd backend
.venv\Scripts\activate

# Run all backend tests
pytest -v

# Run a specific test suite
pytest tests/test_search.py -v
pytest tests/test_extractors.py -v
pytest tests/test_e2e.py -v
```

For the frontend, verify code quality and build integrity:

```bash
cd frontend

# Run code linter
npm run lint

# Validate TypeScript compilation and production build
npm run build
```

For the primary terminal client:

```bash
cd ..
python -m pytest tui/tests -q
python -m tui
```

---

## Configuration

All configuration settings have local-first defaults defined in [backend/app/core/config.py](backend/app/core/config.py). You can override them via environment variables:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `FINDIT_HOST` | `127.0.0.1` | Network interface to bind (strict loopback recommended). |
| `FINDIT_PORT` | `8000` | Port for the FastAPI backend service. |
| `FINDIT_EMBEDDING_DEVICE`| `cuda` (if available), else `cpu` | Hardware acceleration device (`cuda` or `cpu`). |
| `FINDIT_MAX_FILE_SIZE_BYTES` | `52428800` (50 MB) | Maximum single file size allowed for extraction and indexing. |

---

## Security and Privacy

FindIT enforces a local defense-in-depth model:

1. **Strict Loopback Binding**: The FastAPI backend binds exclusively to `127.0.0.1` and `[::1]`. Binding to `0.0.0.0` is strictly rejected.
2. **CORS Isolation**: Cross-origin requests are restricted to local development origins (`http://localhost:5173`, `http://127.0.0.1:5173`).
3. **Path Traversal & Boundary Containment**: Endpoints never accept arbitrary filesystem paths. Physical paths are resolved via internal IDs and verified to reside inside user-registered directory roots.
4. **Shell Injection Prevention**: OS actions ("Open in folder") invoke platform-specific APIs with `shell=False`.
5. **Zero Document Modification Guarantee**: Source files are accessed in read-only mode (`"rb"` or `"r"`). FindIT possesses no file rename, move, or delete routines.
6. **Zero External Data Egress**: All text extraction, chunking, embedding generation, indexing, and ranking execute locally on your machine. No document text, queries, or telemetry are ever sent over the network.

> For the comprehensive threat model and security specifications, see [docs/SECURITY.md](docs/SECURITY.md).

---

## Project Status & Roadmap

FindIT is currently at **`v0.1.0`** status with a unified backend, primary Textual TUI, supported React client, and full local-first hybrid search capabilities.

### Roadmap Milestones
- [x] **v0.1.0 (Current)**: Local hybrid retrieval (FAISS + BM25 + RRF), format extractors (PDF, PPTX, DOCX, MD, Code, Config), continuous header transition UI, in-app passage inspector, and native folder revelation.
- [ ] **v0.2.0 (Planned)**: Local OCR support via Tesseract for scanned PDFs and embedded document images.
- [ ] **v0.3.0 (Planned)**: File-type filtering, date-range filtering, and favorite/bookmark passage collections.
- [ ] **v0.4.0 (Planned)**: Native desktop packaging (Tauri / Electron wrapper) for standalone system tray integration.

> To track detailed milestone progress and architectural decisions, see [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/CHANGELOG.md](docs/CHANGELOG.md).

---

## Known Limitations

- **Scanned PDFs**: Documents without an embedded text layer (pure scanned images) are flagged as `NO_TEXT` without failing the sync job; OCR extraction is planned for v0.2.0.
- **Single-User Scope**: Designed strictly for a single user operating locally; multi-user authentication, roles, and remote network access are intentionally out of scope.
- **File Size Upper Bound**: Files exceeding 50 MB are skipped by default to prevent memory exhaustion; configurable via `FINDIT_MAX_FILE_SIZE_BYTES`.
- **Active Document Editing**: Live file watching is not implemented in v0.1.0; directory resyncs are triggered manually via the UI or API.

> For known technical and operational risks, see [docs/RISKS.md](docs/RISKS.md).

---

## Contributing

Contributions, feedback, and issue reports are welcome! When contributing to FindIT:

1. Ensure all changes include corresponding unit or integration tests under `backend/tests/`.
2. Verify that all backend tests pass (`pytest -v`) and the frontend builds cleanly (`npm run build`).
3. Keep documentation in `docs/` synchronized with architectural or API modifications.

---
