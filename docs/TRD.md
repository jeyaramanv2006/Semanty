# Technical Requirements Document (TRD) — FindIT

> **Document Status**: `APPROVED` | **Version**: 1.0  
> **Last Synchronized**: Based on Comprehensive Research & Technical Analysis  

---

## 1. Technical Architecture & Component Stack

- **Primary interactive client**: Python Textual TUI over the documented loopback REST API.
- **Supported secondary client**: React + TypeScript browser client using the same API contracts.
- **Authoritative engine boundary**: FastAPI owns SQLite, FAISS, BM25, indexing, synchronization, and security; clients do not open index files directly.

| Subsystem | Selected Technology | Technical Rationale & Role |
| :--- | :--- | :--- |
| **Frontend Framework** | React 18+ & TypeScript | Componentized UI, strict type-checking, responsive state machine. |
| **Frontend Build Tool** | Vite | Instant HMR, lightweight bundle output, fast developer experience. |
| **Backend Framework** | Python 3.10+ / FastAPI | High-performance asynchronous API, native integration with ML/vector libraries. |
| **Embedding Engine** | Sentence Transformers (`all-MiniLM-L6-v2`) | Generates high-quality 384-dimensional dense semantic vectors locally. |
| **Vector Search Engine** | FAISS (`IndexFlatIP`) | Exact inner-product search on unit-normalized vectors ($IP \equiv \text{Cosine Sim}$). |
| **Lexical Search Engine**| BM25 (In-memory / Rank-BM25 or FTS5) | Term frequency/inverse document frequency keyword matching. |
| **Metadata & Text Store**| SQLite 3 (WAL mode) | Relational persistence for directories, documents, passages, and job status. |
| **UI Design System** | Custom CSS / Styled tokens | Warm ivory theme, terracotta contours, seamless in-place state animation. |

---

## 2. Text Extraction & Source Location Specifications

### 2.1 Format-Specific Extractors & Location Mapping
Text extraction must capture structural location coordinates during file parsing:

| File Format | Primary Parser | Extracted Metadata Fields | Formatting in UI | Notes & Constraints |
| :--- | :--- | :--- | :--- | :--- |
| **PDF** | `pypdf` / `pymupdf` (fitz) | `page_number`, `page_count`, `start_page`, `end_page` | `Page 18` / `Pages 18–20` | Preserve page boundaries during chunking. If chunk spans pages, record both. |
| **PPTX** | `python-pptx` | `slide_number`, `slide_title` | `Slide 7` | Segment at slide boundaries; slide title prefixes passage text. |
| **Markdown** | `markdown-it-py` / Custom AST | `heading_path`, `start_line`, `end_line` | `Lines 45–80` / `Section: Setup` | Capture heading hierarchy (e.g. `Architecture > Storage`) for context. |
| **Plain Text** | Native UTF-8 Reader | `start_line`, `end_line` | `Lines 112–138` | Strict 1-indexed line counts matching source file. |
| **DOCX** | `python-docx` | `section_heading`, `paragraph_index` | `Section: Access Control` | Avoid fabricating page numbers (DOCX has no fixed page concept). |
| **Source Code** | Regex / AST parsers | `start_line`, `end_line`, `symbol_name` | `Lines 15–42 (verify_token)` | Preserve exact indentation, punctuation, and identifier casing. |
| **Config (JSON/YAML)**| Standard parsers | `start_line`, `end_line`, `key_path` | `Lines 20–35 (database.pool)`| Maintain key context for isolated lexical search. |
| **Scanned PDF** | Fallback Handler | `extraction_status: "no_text"` | *(Flagged in job log)* | If no text layer exists, mark file without failing job. (OCR deferred). |

### 2.2 Extracted Text Fidelity
- **Display Fidelity**: The raw, unnormalized extracted text must be stored in SQLite `passages.text` to guarantee faithful reproduction (case, spacing, punctuation) in the in-app Passage Inspector.
- **Retrieval Text**: Text passed to the embedding model or BM25 index may undergo standardized whitespace normalization and lowercasing without altering the stored display text.

---

## 3. Chunking & Passage Indexing Specifications

### 3.1 Structural Chunking Constraints
- **Target Chunk Size**: ~200 to 400 words (approx. 250–500 tokens).
- **Overlap Window**: 20% sliding window (approx. 40–60 words) to avoid splitting semantic sentences across chunk boundaries.
- **Boundary Sensitivity**:
  - Chunks must prioritize paragraph and section boundaries.
  - Chunks should never span across distinct PPTX slides.
  - For PDF documents, chunks should remain within single pages when feasible; if a paragraph spans across a page break, `start_page` and `end_page` must both be recorded.

### 3.2 Canonical Identifiers
- `document_id`: Deterministic hash (e.g., SHA-256 of `canonical_path` + creation salt) or auto-incrementing UUID.
- `chunk_id`: Deterministic ID formatted as `{document_id}_{chunk_ordinal}`.
- `vector_id`: 64-bit integer representing the internal index position in the FAISS index, mapped 1-to-1 to `chunk_id` in SQLite.

---

## 4. Dense Semantic Vector Retrieval Specifications

### 4.1 Embedding Generation
- **Model**: `sentence-transformers/all-MiniLM-L6-v2`.
- **Vector Dimension**: Exactly **384 dimensions**.
- **Normalization**: All passage vectors and query vectors must be L2-normalized ($||\mathbf{v}||_2 = 1.0$) prior to insertion or query.
- **Hardware Acceleration**: Automatic device binding (`cuda` if NVIDIA GPU is detected via `torch.cuda.is_available()`, with graceful fallback to `cpu`). Overrideable via `FINDIT_EMBEDDING_DEVICE`.
- **Model Versioning**: Document metadata must record `embedding_model_version`. If the model is upgraded, all vectors must be recomputed; vectors from disparate models must never coexist in the same index.

### 4.2 FAISS Index Baseline
- **Index Type**: `faiss.IndexFlatIP` (Flat Inner Product).
- **Mathematical Equivalence**: For L2-normalized vectors:
  $$\text{Inner Product}(\mathbf{u}, \mathbf{v}) = \sum_{i=1}^{384} u_i v_i = \cos(\theta)$$
- **Execution**: Performs an exhaustive brute-force search delivering exact nearest neighbors.
- **Scalability Baseline**: For collections under 100,000 passages, `IndexFlatIP` provides sub-millisecond query latency and zero recall degradation. Approximate graph indices (`IndexHNSWFlat`) or inverted file indices (`IndexIVFFlat`) are deferred until empirical profiling justifies their complexity.

---

## 5. Lexical Retrieval & Rank Fusion Specifications

### 5.1 BM25 Lexical Retrieval
- **Tokenization**: Alphanumeric splitting with support for programming identifiers (preserving snake_case, camelCase, and dotted keys).
- **Index Scope**: Inverted index built over all passage texts.
- **Candidate Pool**: Returns top $M$ candidates (default: $M = 50$) ordered by BM25 relevance score.

### 5.2 Reciprocal Rank Fusion (RRF) Algorithm
Raw cosine similarity scores ($[-1.0, 1.0]$) and BM25 scores ($[0, \infty)$) reside on fundamentally different scales and cannot be directly summed. FindIT employs rank-based fusion:

$$RRF(d) = \sum_{r \in \mathcal{R}} \frac{1}{k + \text{rank}_r(d)}$$

Where:
- $d$: A candidate passage.
- $\mathcal{R}$: The set of retrievers ($\mathcal{R} = \{\text{FAISS}, \text{BM25}\}$).
- $\text{rank}_r(d)$: The 1-indexed rank of document $d$ in retriever $r$'s candidate pool.
- $k$: The smoothing constant, set to **$60$** (empirically proven standard).

### 5.3 Missing Rank Handling
- If candidate $d$ appears in FAISS's top 50 but does not appear in BM25's top 50, it receives an RRF contribution only from FAISS.
- In developer diagnostics, the missing rank is rendered as `—` (not zero).

---

## 6. Incremental Synchronization & Lifecycle

### 6.1 Change Detection Protocol
When a registered directory syncs, the backend executes:
1. **Directory Walk**: Scans all files within the approved directory boundary.
2. **State Comparison**:
   - Compares file `canonical_path`, `size_bytes`, and `modified_time` against SQLite `documents` records.
   - For files with matching size and timestamp, parsing and embedding are skipped.
   - For files with updated timestamps, an optional content hash (SHA-256 fingerprint) is computed.
3. **Re-indexing Updated Files**:
   - Deletes existing passages for the document from SQLite, removes or marks vectors in FAISS, and re-extracts/re-embeds the updated content.
4. **Pruning Deleted Files**:
   - Identifies documents in SQLite that no longer exist on disk within the registered root, purging their passages, vectors, and BM25 postings.

### 6.2 Atomic Index Updates & Persistence
- SQLite operates in WAL mode (`PRAGMA journal_mode=WAL`) to allow concurrent reads during background index writes.
- FAISS vectors are persisted to disk via `faiss.write_index()` following batch commits.
- Index rebuild mechanism: If the FAISS or BM25 index becomes corrupted, the system must be capable of reconstructing them entirely from the stored passages in SQLite.

---

## 7. Performance Targets & Benchmarks

| Metric | Target | Verification Method |
| :--- | :--- | :--- |
| **Search Latency (10k chunks)** | $< 350\text{ ms}$ | Query embedding generation + FAISS search + BM25 search + RRF fusion. |
| **UI Interaction Transition** | $350–500\text{ ms}$ | CSS transition duration from Home to Results state. |
| **Indexing Throughput** | $> 15\text{ docs/sec}$ (text/MD), $> 3\text{ docs/sec}$ (PDF) | Measured on standard 4-core consumer CPU. |
| **Memory Footprint (Idle)** | $< 250\text{ MB}$ (Backend), $< 120\text{ MB}$ (Frontend) | Process resident set size (RSS). |
| **Index Disk Overhead** | $\approx 1.8\text{ KB}$ per passage | SQLite passage record + 384 float32 vector (1,536 bytes) + BM25 posting. |

---

## 8. Evaluation & Diagnostics

### 8.1 Test Query Evaluation Set
The search pipeline must be evaluated against a curated suite of 8 query archetypes:
1. **Exact Technical Keyword**: `"all-MiniLM-L6-v2"` (BM25 prioritized).
2. **Semantic Paraphrase**: `"checking user credentials with bearer tokens"` (FAISS prioritized).
3. **Rare Identifier**: `"verify_jwt_token_signature"` (BM25 prioritized).
4. **Short / Ambiguous Query**: `"indexing architecture"` (Balanced hybrid).
5. **Section-Specific Query**: `"Chapter 4 system deployment"` (Metadata + semantic match).
6. **Divergent Ranking Query**: Queries where semantic top-1 and lexical top-1 differ.
7. **Multi-Passage Document Query**: Queries matching multiple pages of a single PDF.
8. **Negative / Zero-Match Query**: `"xenon quantum flux capacitor"` (Evaluates score floor).

### 8.2 Developer Diagnostics
While hidden from standard users, the API supports a diagnostic query flag returning:
- `semantic_rank`, `semantic_cosine_score`
- `lexical_rank`, `bm25_score`
- `rrf_score`, `final_hybrid_rank`
