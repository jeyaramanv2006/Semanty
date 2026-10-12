# Architectural Decision Records (ADRs) — FindIT

> **Document Status**: `ACTIVE` | **Last Synchronized**: 2026-10-11  
> **Standard**: Michael Nygard ADR Format  

---

## Overview
This document records all fundamental architectural, technological, and algorithmic decisions made for FindIT. Each record captures the context, decision, alternatives evaluated, and resulting trade-offs.

---

## Index of Decisions

- [ADR-001: Local-First Single-User Architecture over Cloud-Hosted Search](#adr-001-local-first-single-user-architecture-over-cloud-hosted-search)
- [ADR-002: Passage-Level Retrieval with Structural Location Metadata](#adr-002-passage-level-retrieval-with-structural-location-metadata)
- [ADR-003: Hybrid Retrieval (Dense Vector + BM25) Fused with Reciprocal Rank Fusion (RRF)](#adr-003-hybrid-retrieval-dense-vector--bm25-fused-with-reciprocal-rank-fusion-rrf)
- [ADR-004: Unified Hybrid Results Presentation over Multi-Mode UI Columns](#adr-004-unified-hybrid-results-presentation-over-multi-mode-ui-columns)
- [ADR-005: 384-Dimensional Embeddings (`all-MiniLM-L6-v2`) with `IndexFlatIP` Baseline](#adr-005-384-dimensional-embeddings-all-minilm-l6-v2-with-indexflatip-baseline)
- [ADR-006: In-Place Homepage-to-Results Transition over Multi-Route Navigation](#adr-006-in-place-homepage-to-results-transition-over-multi-route-navigation)
- [ADR-007: Index-Only Directory Removal Guaranteeing Source File Immutability](#adr-007-index-only-directory-removal-guaranteeing-source-file-immutability)
- [ADR-008: Real Backend Job Telemetry over Synthetic Animated Progress Bars](#adr-008-real-backend-job-telemetry-over-synthetic-animated-progress-bars)
- [ADR-009: Strict Loopback Binding (`127.0.0.1`) and Approved-Root Boundary Confinement](#adr-009-strict-loopback-binding-127001-and-approved-root-boundary-confinement)
- [ADR-010: Adaptive GPU Hardware Acceleration (CUDA) with CPU Fallback](#adr-010-adaptive-gpu-hardware-acceleration-cuda-with-cpu-fallback)

---

### ADR-001: Local-First Single-User Architecture over Cloud-Hosted Search

- **Date**: 2026-10-06
- **Status**: `Accepted`
- **Context**:  
  Personal document search involves proprietary specifications, research papers, financial records, and private notes. Relying on cloud APIs (e.g., OpenAI embeddings, Pinecone) introduces recurring API costs, internet dependency, latency, and privacy risks unacceptable to many users.
- **Decision**:  
  Architect FindIT as a 100% local-first, single-user desktop application. Text extraction, embedding inference, vector indexing, and query execution execute entirely on the user's local machine.
- **Alternatives Considered**:  
  - *Cloud-hosted SaaS*: High ongoing hosting/API costs and severe document privacy concerns.  
  - *Hybrid Cloud Embeddings*: Privacy leakage of passage text sent across public network.
- **Consequences**:  
  - **Positive**: Complete user privacy, zero subscription fees, offline functionality, instant response times.  
  - **Negative**: Constrained to local hardware compute (CPU/local GPU) for embedding throughput.

---

### ADR-002: Passage-Level Retrieval with Structural Location Metadata

- **Date**: 2026-10-06
- **Status**: `Accepted`
- **Context**:  
  Traditional search tools return whole files (e.g. `Architecture_Spec.pdf`). In large 50-page documents, the user is still forced to manually search within the file. Furthermore, averaging a whole document into a single vector dilutes specific concepts.
- **Decision**:  
  Segment documents into location-aware passages (~250–500 tokens). Capture and persist exact structural coordinates during extraction: page numbers for PDFs, slide numbers for PPTX, line numbers for code/text, and heading paths for Markdown/DOCX.
- **Alternatives Considered**:  
  - *Document-level embeddings*: Fast to index, but poor retrieval precision for multi-topic documents.  
  - *Pure line-by-line chunking*: Destroys semantic paragraph coherence and context.
- **Consequences**:  
  - **Positive**: Pinpoints the exact page/slide/line where the remembered topic resides; allows multiple distinct passages from one document to appear.  
  - **Negative**: Larger vector database size (multiple vectors per document) and more complex extraction logic.

---

### ADR-003: Hybrid Retrieval (Dense Vector + BM25) Fused with Reciprocal Rank Fusion (RRF)

- **Date**: 2026-10-07
- **Status**: `Accepted`
- **Context**:  
  Dense semantic vectors excel at capturing conceptual meaning and paraphrasing, but often struggle with exact identifiers, code symbols, configuration keys, or rare technical terms. Pure keyword search (BM25) has the inverse trade-off. Furthermore, cosine similarity and BM25 scores exist on non-comparable mathematical scales.
- **Decision**:  
  Execute hybrid retrieval using FAISS for dense semantic vectors and BM25 for lexical keywords. Fuse top candidate pools ($M=50$) using Reciprocal Rank Fusion:
  $$RRF(d) = \sum_{r \in \mathcal{R}} \frac{1}{k + \text{rank}_r(d)} \quad (k=60)$$
- **Alternatives Considered**:  
  - *Vector-Only Search*: Misses exact code symbols and specific function names.  
  - *Linear Score Combination*: Requires delicate, fragile score normalization that fails across varying corpus distributions.
- **Consequences**:  
  - **Positive**: Best-of-both-worlds retrieval accuracy across both conceptual and exact keyword queries.  
  - **Negative**: Requires maintaining two distinct index structures (FAISS and BM25).

---

### ADR-004: Unified Hybrid Results Presentation over Multi-Mode UI Columns

- **Date**: 2026-10-07
- **Status**: `Accepted`
- **Context**:  
  An early UI mockup featured three side-by-side columns: "Hybrid Results", "Semantic Results", and "Lexical Results". User testing revealed this confused users, exposed internal algorithmic details, and duplicated result cards.
- **Decision**:  
  Present a single, unified list ordered strictly by RRF hybrid relevance. Keep technical diagnostics (individual semantic/lexical ranks and scores) isolated to developer views.
- **Alternatives Considered**:  
  - *Three-column layout*: Cluttered viewport and forced users to evaluate internal search mechanics.  
  - *User-selectable mode tabs*: Forced users to guess whether their query was "semantic" or "lexical".
- **Consequences**:  
  - **Positive**: Clean, serene search experience focused on relevant answers.  
  - **Negative**: Developers must use explicit diagnostic flags to inspect raw retriever ranks.

---

### ADR-005: 384-Dimensional Embeddings (`all-MiniLM-L6-v2`) with `IndexFlatIP` Baseline

- **Date**: 2026-10-08
- **Status**: `Accepted`
- **Context**:  
  The system requires an embedding model that balances semantic quality, compact vector dimension, and high CPU inference speed. Furthermore, the vector index must be mathematically sound.
- **Decision**:  
  Adopt `sentence-transformers/all-MiniLM-L6-v2` producing 384-dimensional dense vectors. L2-normalize all vectors and utilize `faiss.IndexFlatIP`.
- **Alternatives Considered**:  
  - *768D / 1536D Models*: High memory footprint and slower CPU inference on consumer laptops.  
  - *Approximate Indexing (HNSW / IVF)*: Unnecessary complexity for personal document corpora (<100k passages) where exact flat search executes in <1ms.
- **Consequences**:  
  - **Positive**: Minimal RAM usage (1,536 bytes per vector), exact nearest neighbor accuracy, fast local CPU inference.  
  - **Negative**: Switching models in the future requires re-embedding existing passages.

---

### ADR-006: In-Place Homepage-to-Results Transition over Multi-Route Navigation

- **Date**: 2026-10-08
- **Status**: `Accepted`
- **Context**:  
  Navigating away from a search homepage to a separate `/search` results page via hard browser routing causes layout flashes, discards search focus, and feels disjointed.
- **Decision**:  
  Implement the homepage and results view as a single continuous React state machine. Upon pressing Enter, the centered search bar and logo animate smoothly (350–500ms) into a compact pinned header while results stream below.
- **Alternatives Considered**:  
  - *Traditional Multi-Page Navigation*: Causes UI flashes and breaks visual spatial continuity.  
  - *Instantaneous Swap*: Feels abrupt and jarring.
- **Consequences**:  
  - **Positive**: Highly polished, fluid desktop application feel.  
  - **Negative**: Requires careful CSS choreography and reduced-motion fallbacks.

---

### ADR-007: Index-Only Directory Removal Guaranteeing Source File Immutability

- **Date**: 2026-10-09
- **Status**: `Accepted`
- **Context**:  
  When users click "Remove Directory" in directory management, ambiguity can arise regarding whether the action deletes files from the operating system.
- **Decision**:  
  Directory removal strictly deletes FindIT's internal SQLite metadata, FAISS vectors, and BM25 postings. Original files on disk are completely immutable and never touched.
- **Alternatives Considered**:  
  - *File manager integration with delete capabilities*: Violates core principle of document safety and introduces severe data-loss risk.
- **Consequences**:  
  - **Positive**: Absolute data safety for user documents.  
  - **Negative**: None. Clear distinction that FindIT is an index, not a file manager.

---

### ADR-008: Real Backend Job Telemetry over Synthetic Animated Progress Bars

- **Date**: 2026-10-09
- **Status**: `Accepted`
- **Context**:  
  Many desktop apps simulate progress using timer-driven percentage increments. This misleads users when large documents take longer to parse or embed.
- **Decision**:  
  Job status endpoints and progress bars reflect real backend pipeline stages (`SCANNING`, `EXTRACTING`, `EMBEDDING`, `INDEXING`) and verified processed file counts.
- **Alternatives Considered**:  
  - *Timer-based progress estimation*: Creates frustration if the timer reaches 99% while heavy indexing continues.
- **Consequences**:  
  - **Positive**: Honest, reliable system transparency.  
  - **Negative**: Progress updates require active polling or status events from the backend.

---

### ADR-009: Strict Loopback Binding (`127.0.0.1`) and Approved-Root Boundary Confinement

- **Date**: 2026-10-10
- **Status**: `Accepted`
- **Context**:  
  Local HTTP services can be targeted by malicious websites executing CSRF or DNS rebinding attacks to scan local files or trigger unapproved system reads.
- **Decision**:  
  Bind the FastAPI server strictly to `127.0.0.1`. Enforce canonical path resolution (`Path.resolve()`) asserting all accessed files reside within registered directory roots. Never expose endpoints accepting arbitrary client-supplied filesystem paths.
- **Alternatives Considered**:  
  - *Binding to `0.0.0.0`*: Exposes the service to the local network without authentication.  
  - *Unrestricted path parameter endpoints*: Vulnerable to directory traversal (`../`).
- **Consequences**:  
  - **Positive**: Robust local security sandbox preventing unauthorized file exposure.  
  - **Negative**: Remote multi-device access is blocked (by design for v1.0).

---

### ADR-010: Adaptive GPU Hardware Acceleration (CUDA) with CPU Fallback

- **Date**: 2026-10-11
- **Status**: `Accepted`
- **Context**:  
  Locally running sentence-transformers embedding generation on pure CPU threads (e.g. `device="cpu"`) constrains indexing throughput to ~40–80 passages/second. Modern personal machines often possess discrete GPUs (e.g. NVIDIA RTX series with Tensor Cores) capable of accelerating vector inference by 10x–15x.
- **Decision**:  
  Enable automatic hardware acceleration in `EmbeddingEngine` and `app.core.config.EMBEDDING_DEVICE`. Automatically query `torch.cuda.is_available()`; bind to `"cuda"` when a capable GPU is detected and seamlessly fall back to `"cpu"` when unavailable, with an optional `FINDIT_EMBEDDING_DEVICE` environment override.
- **Alternatives Considered**:  
  - *Strict CPU-only*: Ensures identical environment behavior everywhere but leaves high-performance local GPUs unutilized.
  - *Hardcoding `"cuda"`*: Fails on systems without discrete NVIDIA GPUs.
- **Consequences**:  
  - **Positive**: Instant 10x–15x acceleration on systems with NVIDIA GPUs; eliminates CPU thermal throttling during batch document indexing.
  - **Negative**: CUDA-enabled PyTorch builds require larger installation footprint (~2GB vs ~200MB).

---

### ADR-011: FastAPI Backend as the Authoritative Search Engine

- **Date**: 2026-10-13
- **Status**: `Accepted`
- **Context**:
  FindIT currently contains a FastAPI engine and an independent CLI engine with separate SQLite, FAISS, BM25, chunking, and retrieval behavior. This creates divergent results and makes fixes impossible to apply consistently.
- **Decision**:
  The FastAPI service and its SQLite/FAISS/BM25 stores are the sole authoritative engine. All interactive clients, including the TUI and React client, use the documented local REST API. The independent CLI engine and its storage format are retired after TUI parity is reached.
- **Consequences**:
  - **Positive**: One indexing lifecycle, one ranking implementation, one security boundary, and consistent results.
  - **Negative**: Existing CLI-specific data must be reindexed through the backend.

---

### ADR-012: Textual TUI as the Primary Interactive Client

- **Date**: 2026-10-13
- **Status**: `Accepted`
- **Context**:
  FindIT needs a focused terminal workflow for search, passage inspection, directory management, and sync monitoring without duplicating the engine or degrading into a command-only REPL.
- **Decision**:
  Build a Python Textual TUI over the local REST API. It becomes the primary interactive client; the React client remains supported at core feature parity. The TUI auto-starts the backend only when it owns that process and stops only processes it started.
- **Consequences**:
  - **Positive**: Keyboard-first workflows, explicit focus, responsive panels, and a reusable API boundary.
  - **Negative**: Textual becomes a required runtime dependency and terminal capability fallbacks must be tested.

---

### ADR-013: Unified Hybrid Ranking for User Interfaces

- **Date**: 2026-10-13
- **Status**: `Accepted`
- **Context**:
  The product requirements define one ranked list, while current clients expose semantic and lexical mode controls and perform client-side re-sorting.
- **Decision**:
  Normal user interfaces show only the backend's hybrid RRF ordering. Ranking diagnostics remain developer/test-only and are never used as user-facing confidence or score decoration.
- **Consequences**:
  - **Positive**: One understandable result order and no client/server ranking divergence.
  - **Negative**: Advanced users lose visible per-retriever mode switching in the standard UI.
