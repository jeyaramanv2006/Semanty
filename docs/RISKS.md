# Project Risks & Mitigations — FindIT

> **Document Status**: `ACTIVE` | **Version**: 1.0  
> **Risk Review Cadence**: Per Milestone Release  

---

## 1. Risk Assessment Matrix

| Risk ID | Risk Category | Description | Likelihood | Impact | Severity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `RSK-001` | **Algorithmic** | Scanned PDFs lack embedded text layers, resulting in 0 extracted passages. | High | Medium | **HIGH** | `Mitigated` |
| `RSK-002` | **Data Integrity**| Index and metadata desynchronization if process terminates during batch sync. | Medium | High | **HIGH** | `Mitigated` |
| `RSK-003` | **Security** | Malicious web page exploits local API to read files outside approved roots. | Medium | Critical| **HIGH** | `Mitigated` |
| `RSK-004` | **Performance** | High CPU consumption and thermal throttling during bulk embedding of large corpora. | Medium | Medium | **MEDIUM** | `Mitigated` |
| `RSK-005` | **Data Quality** | Format extractors fail to capture accurate line or page numbers in complex layouts. | Medium | Medium | **MEDIUM** | `Mitigated` |
| `RSK-006` | **Concurrency** | Concurrent sync operations cause SQLite lock contention or race conditions in FAISS. | Low | High | **MEDIUM** | `Mitigated` |
| `RSK-007` | **UX / Frontend**| Out-of-order network responses cause results from Query A to overwrite Query B. | Medium | Low | **LOW** | `Mitigated` |
| `RSK-008` | **Scalability** | Flat inner product FAISS search degrades in latency when corpus exceeds 200k chunks. | Low | Medium | **LOW** | `Accepted` |

---

## 2. Risk Details & Mitigation Strategies

### `RSK-001`: Scanned PDFs Lacking Embedded Text Layers
- **Context**: Users frequently save scanned documents, receipts, or photographed book pages as PDFs. In v1.0, OCR is deferred to avoid heavy local model weights (Tesseract / EasyOCR).
- **Impact**: The user expects a scanned PDF to be searchable, but FindIT extracts zero text, causing search misses.
- **Mitigation Strategy**:
  - The PDF extractor checks whether any text characters were extracted.
  - If a PDF yields no text, it is explicitly flagged with `extraction_status: "NO_TEXT"` in SQLite.
  - The indexing job log and directory status report: *"Warning: Scanned document without embedded text layer (OCR not supported in v1.0)"*.
  - Prevents silent indexing failures and sets honest user expectations.

---

### `RSK-002`: Index & Metadata Desynchronization on Crash
- **Context**: If the backend process crashes or is killed while updating SQLite, FAISS, and BM25, the vector index and database could fall out of parity (e.g., SQLite has chunk records with no corresponding vectors in FAISS, or vice-versa).
- **Impact**: Search returns broken or orphaned result IDs; vector search points to wrong passage text.
- **Mitigation Strategy**:
  - SQLite operates in WAL mode with transactional batch commits.
  - Temporary staged index files (`vector_index.faiss.tmp`) are written and atomically renamed upon batch completion.
  - Automated Index Rebuild Endpoint: The backend provides an automated repair routine that reconstructs the FAISS index and BM25 index directly from SQLite `passages` table without re-reading source files on disk.

---

### `RSK-003`: Local API Exploitation by Malicious Web Pages
- **Context**: A user visits an external website that attempts cross-origin requests (`fetch('http://127.0.0.1:8000/api/...')`) to scan local file paths or inspect indexed documents.
- **Impact**: Unauthorized local file access or leakage of private document titles.
- **Mitigation Strategy**:
  - Strict loopback binding (`127.0.0.1`).
  - Strict CORS allowlisting restricting origins exclusively to `http://localhost:5173`.
  - Host header verification ensuring `Host` matches `127.0.0.1` or `localhost`.
  - Directory boundary assertions: All file accesses are resolved against canonical registered directory paths (`Path.resolve().relative_to(root)`).
  - API never accepts arbitrary client-supplied paths; all actions require registered `document_id` references.

---

### `RSK-004`: High CPU Consumption During Initial Bulk Embeddings
- **Context**: When a user registers a directory containing thousands of pages, generating 384D embeddings for 20,000+ passages on CPU can saturate cores and cause system fan noise or latency.
- **Impact**: Sluggish UI responsiveness and poor initial onboarding experience.
- **Mitigation Strategy**:
  - Background worker thread with bounded concurrency (e.g., `max_workers = os.cpu_count() - 1` or priority queuing).
  - Batched inference (batch size: 32 or 64 passages) utilizing optimized SIMD/ONNX runtime.
  - Incremental sync skips unchanged files using `size_bytes` and `modified_time` timestamps, ensuring heavy embedding only occurs for new content.

---

### `RSK-005`: Inaccurate Location Labels in Variable Document Layouts
- **Context**: DOCX and dynamic reflowable formats have no fixed physical page concepts. Fabricating page numbers creates misleading search results.
- **Impact**: User tries to locate a passage in an external viewer using an incorrect page number.
- **Mitigation Strategy**:
  - Strict rule against fabricating coordinates:
    - DOCX uses `Section: [Heading]` and paragraph indices.
    - Plain text and code use 1-indexed line numbers.
    - PPTX uses slide numbers.
    - PDF strictly verifies page bounds.
  - Location labels reflect true format capabilities; missing metadata remains gracefully omitted.

---

### `RSK-006`: Concurrency Conflicts During Multi-Directory Sync
- **Context**: User clicks "Sync All" with 5 registered directories while simultaneously submitting search queries.
- **Impact**: SQLite `database is locked` errors or thread safety violations in FAISS.
- **Mitigation Strategy**:
  - SQLite WAL mode allows concurrent readers while one writer commits.
  - JobManager enqueues sync tasks in a coordinated worker queue rather than launching unbounded parallel threads.
  - Search queries read the committed FAISS index in memory without blocking on background worker updates.

---

### `RSK-007`: Stale Search Responses Overwriting Active UI
- **Context**: User rapidly types Query A, hits enter, immediately re-types Query B, and hits enter. Query A returns after Query B.
- **Impact**: UI displays results for Query A while the search bar shows Query B.
- **Mitigation Strategy**:
  - Frontend client increments an `activeRequestId` on every search submission.
  - In-flight requests are aborted using `AbortController`.
  - Responses returning with a stale request ID are discarded before updating React state.

---

### `RSK-010`: Client Divergence During Engine Unification
- **Context**: Multiple clients or a legacy CLI can maintain different storage, ranking, or pagination behavior.
- **Impact**: Users see inconsistent results and fixes apply to only one interface.
- **Mitigation Strategy**:
  - Route the TUI and supported React client through the FastAPI API only.
  - Remove the independent CLI engine after TUI parity.
  - Test API contracts and client request identity against one hybrid result order.

### `RSK-011`: TUI Terminal Capability Differences
- **Context**: SSH, multiplexers, narrow terminals, `NO_COLOR`, and Unicode/font differences can change layout and input behavior.
- **Impact**: Lost focus, clipped passages, unreadable status, or terminal state not restored on exit.
- **Mitigation Strategy**:
  - Use Textual's buffered rendering and capability-aware fallbacks.
  - Keep labels and focus indicators meaningful without color.
  - Test narrow/wide layouts, reduced color, paste, resize, PTY exit, and error recovery.

Release note: automated backend and Textual checks pass. A real interactive PTY smoke test remains a machine/terminal-specific manual check and is not represented as an automated pass.
