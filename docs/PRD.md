# Product Requirements Document (PRD) — FindIT

> **Product Name**: FindIT  
> **Tagline**: *"Find what you remember."*  
> **Supporting Line**: *"Whatever you remember, find where it belongs."*  
> **Document Status**: `APPROVED` | **Target Release**: v0.1.0 MVP  

---

## 1. Executive Summary & Vision

### 1.1 The Core Problem
Knowledge workers, researchers, and developers accumulate thousands of local files—PDFs, research papers, slide decks, Markdown notes, reports, source code, and configuration files. When attempting to retrieve a specific piece of information, standard desktop search tools (e.g., Windows Search, macOS Spotlight, basic grep) fail because they demand exact keyword recall or filenames.

Human memory works through associative meaning, contextual fragments, and thematic recall rather than verbatim strings:
- *"The PDF where I read about token-based authentication and refresh token rotation."*
- *"The slide that explained the system architecture and load balancing tiers."*
- *"The meeting notes where we discussed local vector embeddings and SQLite indexing."*
- *"The config file containing the isolated database network binding."*

When users cannot remember the exact filename, path, or precise syntax, existing tools fail.

### 1.2 The Solution
**FindIT** is a local-first, single-user document search application whose primary interactive client is a keyboard-first Textual TUI, with a supported local React browser client. Users register approved local directories; FindIT extracts text, segments it into semantic passages while preserving precise source-location metadata, and builds both a semantic vector index (FAISS) and a lexical index (BM25).

When a user searches using conversational or partial recollections, FindIT retrieves matching passages using hybrid retrieval fused via Reciprocal Rank Fusion (RRF), presenting a single, unified list of the most relevant passages.

### 1.3 Core Promise
> **"Search by remembered meaning, inspect the exact passage that matched, and locate the original file—without ever uploading documents to a cloud service."**

---

## 2. Target Audience & Primary Persona

### 2.1 Primary User
- **Profile**: A professional, student, researcher, or developer managing a growing collection of local reference documents, notes, specifications, and code across disparate directories.
- **Key Pain Point**: Wasting minutes or hours opening multiple PDFs or slide decks searching for a known concept or diagram.
- **Privacy Requirements**: Unwilling or unable to upload proprietary company files, private research notes, or personal documents to cloud-hosted AI search tools.

### 2.2 Core User Scenarios
1. **Contextual Retrieval**: The user remembers an architectural concept discussed in a document 6 months ago. They enter a conceptual query, review the top passage matches, and immediately verify the excerpt in the in-app viewer.
2. **Provenance & Inspection**: The user finds a relevant code snippet or passage and needs to open the actual file in its host folder to continue work.
3. **Curated Scope Management**: The user registers project-specific directories (e.g., `~/Developer/specs`, `~/Documents/Papers`) and excludes noisy or unrelated personal folders.
4. **Resilient Synchronization**: The user updates local documents and triggers a sync, seeing accurate real-time progress while source files remain completely untouched.

---

## 3. Product Principles

1. **Search by Remembered Context**: Optimize for natural-language descriptions, semantic intent, and fuzzy conceptual queries rather than strict Boolean syntax.
2. **Show Empirical Evidence**: Deliver actual extracted passages in an in-app inspector—never generate hallucinations, AI summaries, or synthetic text.
3. **Preserve Exact Provenance**: Every search result must link directly to its physical file and provide precise location metadata (Page X or Pages X–Y, Slide N, Line ranges, or Section heading).
4. **Local-First & Zero-Cloud Dependency**: Indexing, embedding generation, ranking, and search execution occur 100% locally on the user's workstation.
5. **One Unified, Ranked List**: Abstract ranking complexity into a single hybrid list ordered by Reciprocal Rank Fusion (RRF). Avoid dividing the UI into confusing technical tabs (semantic vs. lexical).
6. **Honest System Transparency**: Never fabricate mock progress bars, estimated scores, or artificial confidence percentages. Display real backend status, counts, and errors.
7. **Strict Immutability of Source Documents**: FindIT is an index, not a file manager. Indexing, updating, and removing directory registrations must never modify, move, or delete original files.
8. **Minimalist, Distraction-Free Interaction**: Maintain an elegant, focused interface centered purely on the search interaction and passage inspection.

---

## 4. User Experience & Interaction Design

### 4.1 Visual Design Language
- **Background Palette**: Warm ivory/cream background accented with delicate terracotta / muted brick-red contour lines framing the viewport.
- **Typography**: Clean, restrained typography with strong visual hierarchy.
- **Result Presentation**: Near-white horizontal result cards with subtle warm borders, generous whitespace, and minimal elevation shadows.
- **Aesthetic Feel**: Thoughtful, refined, and calm—distinct from generic enterprise SaaS portals.

### 4.2 Homepage State
- Central FindIT brand identity and logo.
- Primary Title: *"Find what you remember."*
- Supporting Subtitle: *"Whatever you remember, find where it belongs."*
- Prominent central search input with keyboard focus.
- Folder icon triggering the **Indexed Directories Management** modal.
- Clean canvas free of cluttered dashboards, metrics panels, or sidebars.

### 4.3 Seamless Homepage-to-Results Transition
- **Interaction**: Pressing `Enter` initiates an in-place transformation without a full-page reload or view replacement.
- **Choreography (350–500ms)**:
  1. The central FindIT logo and search bar animate smoothly into a compact header at the top of the viewport.
  2. The large title and subtitle gracefully fade out.
  3. The query text remains preserved and editable inside the header search bar.
  4. The background canvas and contour line pattern remain visually stable.
  5. The results summary (e.g., *"7 matching passages across 5 files"*) and hybrid result list slide/fade into view.
- **Accessibility**: Full support for `prefers-reduced-motion`—disabling motion transforms and providing instant state transitions.

### 4.4 Result Rows & Passage Inspection
- **Row Attributes**:
  - File-type icon (PDF, PPTX, MD, Code, TXT, DOCX).
  - Prominent filename.
  - Granular location badge (`Pages 18–20`, `Slide 7`, `Lines 112–138`, `Section: Access Control`).
  - Abbreviated directory path.
  - Independent **"Open in folder"** icon button.
- **Passage-Level Granularity**: Multiple distinct, highly-ranked passages from the same document appear independently. Results are not prematurely collapsed by file.
- **Passage Inspector Modal**:
  - Clicking a result card body opens the in-app Passage Inspector.
  - Displays the full, unvarnished extracted text of the passage with query term highlights.
  - Clearly displays document metadata, location, and canonical path.
  - Provides an optional "Open file" action.
- **Independent Folder Navigation**:
  - Clicking the "Open in folder" action reveals the containing folder in the OS file manager (and selects/highlights the file where supported).
  - Clicking this action never accidentally triggers the passage inspection modal.

### 4.5 Indexed Directories Modal
- Accessible via the folder icon in the navigation header.
- **Header Summary**: Total registered directories, total indexed document count, and a global **"Sync all"** action.
- **Directory Row Items**:
  - Directory display name and abbreviated local path.
  - File count and last-synced timestamp.
  - Per-directory **Sync** action.
  - Per-directory **Remove** action.
- **Action Semantics**:
  - "Add Directory": Triggers an OS directory picker to register a new approved root.
  - "Remove Directory": Clears FindIT's internal SQLite, FAISS, and BM25 index records only. Clearly clarifies that original files are untouched.
- **Progress Tracking**: Real-time feedback reflecting actual pipeline stages (Scanning, Extracting, Embedding, Indexing) and file counts.

### 4.6 Primary Textual TUI
- The TUI provides search, pagination, passage inspection, native file actions, directory management, sync monitoring, health, and recovery through the local REST API.
- Wide terminals use stable source/job, results, and inspector panels. Narrow terminals collapse secondary panels without losing selection or scroll state.
- `/`, Enter, arrows/`j`/`k`, `o`, `f`, `a`, `d`, `s`, `S`, `?`, Escape, and `q` are discoverable through contextual help and the footer.
- The TUI displays factual job stages, counts, and durable errors without technical ranking toggles or synthetic confidence values.

---

## 5. Scope & Roadmap Boundaries

### 5.1 MVP Scope (v1.0)
- Single-user local desktop application (React + Vite frontend, Python + FastAPI backend).
- Loopback binding (`127.0.0.1`) with strict directory-boundary isolation.
- Support for PDF, Markdown, Plain Text, DOCX, PPTX, and standard code/config files.
- Location-aware text extraction and chunking.
- Local dense embeddings (`sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions).
- Dense vector retrieval via FAISS (`IndexFlatIP` baseline).
- Lexical retrieval via BM25.
- Hybrid ranking via Reciprocal Rank Fusion (RRF, $k=60$).
- Unified passage search results with batch pagination (Top 10 initially + "Show more").
- In-app passage inspection modal.
- OS-level "Open containing folder" integration.
- Directory management modal with real-time sync status and index-only removal.

### 5.2 Explicit Non-Goals for v1.0
- **No User Accounts or Multi-Tenancy**: Single-user desktop scope; no authentication or login gates.
- **No Cloud Document Uploads**: Zero remote AI API processing or external data egress.
- **No File Modification or Management**: FindIT will never rename, move, write to, or delete user files.
- **No Generative AI Summarization / Q&A**: FindIT acts as an exact retrieval engine, not a generative chatbot.
- **No OCR in Initial Release**: Scanned PDFs without an embedded text layer report "No extractable text" rather than executing heavy local OCR pipelines.
- **No Separate Technical Search Modes**: The user UI will not feature separate "Semantic Only" or "Lexical Only" toggles.
