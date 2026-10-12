# Semantic Search Engine Specification (FindIT / Semanty)

> **Purpose:** This specification details the complete core search and retrieval architecture of the project. It is self-contained and designed specifically for an AI agent or engineer to implement as a standalone **Jupyter Python Notebook (`.ipynb`)**. It excludes web servers, CLI arguments, and frontend code, focusing purely on the data pipeline, indexing, and retrieval algorithms.

---

## 1. Architecture & Pipeline Overview

The system is a **Local Hybrid Document Retrieval Engine** combining:
1. **Format-Aware Ingestion:** Extracts text from multi-format files while preserving structural coordinates (pages, slides, line numbers).
2. **Structure-Aware Chunking:** Segments text into sliding-window passages (~350 tokens, ~50 token overlap) without crossing hard structural boundaries.
3. **SQLite Metadata Store:** Relational store tracking document metadata, chunk text, and source coordinates with WAL mode.
4. **Dense Vector Search (FAISS):** 384-dimensional embeddings generated with `sentence-transformers/all-MiniLM-L6-v2`, strictly L2-normalized, indexed via `IndexIDMap2(IndexFlatIP)`.
5. **Lexical Search (BM25):** Custom Lucene-smoothed `BM25Okapi` equipped with an identifier-aware tokenizer (handles camelCase, snake_case, and file paths).
6. **Reciprocal Rank Fusion (RRF):** Fuses dense and sparse candidate pools with smoothing constant $k=60$.

```
[Raw Files: PDF, DOCX, PPTX, MD, PY, TXT]
                    │
                    ▼
       1. Format-Specific Extraction (PyMuPDF, docx, pptx)
                    │
                    ▼
       2. Structure-Aware Chunking (350 tokens, 50 overlap)
                    │
       ┌────────────┴────────────┬────────────────────────┐
       ▼                         ▼                        ▼
3. SQLite Store          4. FAISS Dense Index    5. BM25 Sparse Index
(passages + metadata)    (MiniLM-L6-v2, 384D)     (Lucene-smoothed IDF)
       ▲                         │                        │
       │                         ▼                        ▼
       │               Top-50 Dense Candidates   Top-50 Lexical Candidates
       │                         │                        │
       │                         └───────────┬────────────┘
       │                                     ▼
       │                          6. RRF Fusion (k=60)
       │                                     │
       └─────────────────────────────────────┤ (Hydrate text & coordinates)
                                             ▼
                               7. Final Ranked Results
```

---

## 2. Dependencies

```python
# Required packages for the Jupyter Notebook
!pip install -q \
    sentence-transformers \
    faiss-cpu \
    rank-bm25 \
    pymupdf \
    python-docx \
    python-pptx \
    numpy
```

---

## 3. Document Extraction Layer

Extractors ingest raw files and return standardized blocks containing text and format-specific location coordinates.

### 3.1 Supported File Types
* **PDF (`.pdf`):** Extracted page-by-page using `fitz` (`PyMuPDF`).
* **Word (`.docx`):** Extracted by paragraphs, heading sections, and tables using `python-docx`.
* **PowerPoint (`.pptx`):** Extracted slide-by-slide and shape-by-shape using `python-pptx`.
* **Code / Markdown / Text (`.py`, `.js`, `.ts`, `.md`, `.txt`, `.json`, `.yaml`):** Extracted with 1-indexed line numbers and heading tracking.

### 3.2 Extractor Data Model
```python
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class ExtractedBlock:
    text: str
    page_number: Optional[int] = None       # PDF (1-indexed)
    slide_number: Optional[int] = None      # PPTX (1-indexed)
    start_line: Optional[int] = None        # Code/Text (1-indexed)
    end_line: Optional[int] = None
    section_heading: Optional[str] = None   # Markdown/DOCX heading
    paragraph_index: Optional[int] = None   # DOCX paragraph index

@dataclass
class ExtractedDocument:
    file_path: str
    file_type: str
    blocks: List[ExtractedBlock]
```

### 3.3 Core Extractor Logic
* **PDF (PyMuPDF):**
  ```python
  import fitz  # PyMuPDF

  def extract_pdf(file_path: str) -> List[ExtractedBlock]:
      doc = fitz.open(file_path)
      blocks = []
      for page_idx, page in enumerate(doc, start=1):
          text = page.get_text("text").strip()
          if text:
              blocks.append(ExtractedBlock(text=text, page_number=page_idx))
      return blocks
  ```

* **PPTX (python-pptx):**
  ```python
  from pptx import Presentation

  def extract_pptx(file_path: str) -> List[ExtractedBlock]:
      prs = Presentation(file_path)
      blocks = []
      for slide_idx, slide in enumerate(prs.slides, start=1):
          texts = []
          for shape in slide.shapes:
              if shape.has_text_frame:
                  for para in shape.text_frame.paragraphs:
                      t = para.text.strip()
                      if t:
                          texts.append(t)
          if texts:
              blocks.append(ExtractedBlock(text="\n".join(texts), slide_number=slide_idx))
      return blocks
  ```

* **DOCX (python-docx):**
  ```python
  from docx import Document

  def extract_docx(file_path: str) -> List[ExtractedBlock]:
      doc = Document(file_path)
      blocks = []
      current_heading = None
      for idx, p in enumerate(doc.paragraphs):
          t = p.text.strip()
          if not t:
              continue
          if p.style.name.startswith("Heading"):
              current_heading = t
          blocks.append(ExtractedBlock(text=t, section_heading=current_heading, paragraph_index=idx))
      return blocks
  ```

* **Code / Markdown / Plain Text:**
  ```python
  def extract_text_file(file_path: str) -> List[ExtractedBlock]:
      with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
          lines = f.readlines()
      blocks = []
      current_heading = None
      for idx, line in enumerate(lines, start=1):
          stripped = line.strip()
          if stripped.startswith("#"):
              current_heading = stripped.lstrip("#").strip()
          if stripped:
              blocks.append(ExtractedBlock(text=stripped, start_line=idx, end_line=idx, section_heading=current_heading))
      return blocks
  ```

---

## 4. Structure-Aware Chunking Engine

Splits extracted blocks into chunks suited for dense and sparse models while preserving precise source coordinates.

### 4.1 Hyperparameters
* **Target Token Count:** `350 tokens` (~1,400 characters)
* **Overlap:** `50 tokens` (~200 characters)
* **Token Estimator:** Regex heuristic `\w+|[^\w\s]` (~1.3 tokens per word).

### 4.2 Structural Rules
1. **PPTX:** Chunks **never cross slide boundaries**. Each slide is chunked independently.
2. **PDF:** Chunks track `page_number` or span `(start_page, end_page)`.
3. **Code/Text:** Chunks aggregate lines and track `(start_line, end_line)` of the chunked window.
4. **Coordinate Label Formatter:**
   - Slide: `"Slide X"`
   - PDF: `"Page X"` or `"Page X of Y"`
   - Lines: `"Line X"` or `"Lines X–Y"`
   - Heading: `"Section: <Heading>"`

```python
@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    chunk_ordinal: int
    text: str
    token_count: int
    location_label: str
    page_number: Optional[int] = None
    slide_number: Optional[int] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
```

---

## 5. Relational SQLite Store

SQLite serves as the single source of truth for metadata, chunk text, and vector mappings.

### 5.1 Pragmas
* `PRAGMA journal_mode = WAL;` (Fast concurrent reads/writes)
* `PRAGMA foreign_keys = ON;` (Cascading cleanup)
* `PRAGMA synchronous = NORMAL;`

### 5.2 Schema
```sql
CREATE TABLE IF NOT EXISTS documents (
    document_id         TEXT PRIMARY KEY,
    canonical_path      TEXT UNIQUE NOT NULL,
    filename            TEXT NOT NULL,
    file_type           TEXT NOT NULL,
    size_bytes          INTEGER NOT NULL,
    modified_time       REAL NOT NULL,
    indexed_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS passages (
    chunk_id            TEXT PRIMARY KEY,
    document_id         TEXT NOT NULL,
    chunk_ordinal       INTEGER NOT NULL,
    text                TEXT NOT NULL,
    location_label      TEXT NOT NULL,
    page_number         INTEGER,
    slide_number        INTEGER,
    start_line          INTEGER,
    end_line            INTEGER,
    vector_id           INTEGER UNIQUE, -- Maps 1:1 to FAISS index row ID
    FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_passages_doc ON passages(document_id);
CREATE INDEX IF NOT EXISTS idx_passages_vec ON passages(vector_id);
```

---

## 6. Dense Vector Index (FAISS + SentenceTransformers)

### 6.1 Embedding Configuration
* **Model:** `sentence-transformers/all-MiniLM-L6-v2`
* **Embedding Dimension ($d$):** `384`
* **Normalization:** Unit L2 norm along axis `-1`:
  $$\mathbf{v}_{\text{norm}} = \frac{\mathbf{v}}{\max(\|\mathbf{v}\|_2, 10^{-12})}$$

### 6.2 FAISS Index Setup
Using `IndexIDMap2` wrapping `IndexFlatIP`:
* **Inner Product on L2-normalized vectors** is mathematically identical to **Cosine Similarity**:
  $$\langle \mathbf{u}_{\text{norm}}, \mathbf{v}_{\text{norm}} \rangle = \cos(\theta)$$
* `IndexIDMap2` allows custom explicit 64-bit integer IDs (`vector_id`) matching SQLite:

```python
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

class DenseIndex:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)
        self.dimension = 384
        # IndexFlatIP + IndexIDMap2
        self.index = faiss.IndexIDMap2(faiss.IndexFlatIP(self.dimension))

    def embed(self, texts: List[str]) -> np.ndarray:
        vectors = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
        return vectors / np.maximum(norms, 1e-12)

    def add(self, texts: List[str], vector_ids: List[int]):
        vecs = self.embed(texts).astype(np.float32)
        ids = np.array(vector_ids, dtype=np.int64)
        self.index.add_with_ids(vecs, ids)

    def search(self, query: str, top_k: int = 50) -> List[Tuple[int, float]]:
        q_vec = self.embed([query]).astype(np.float32)
        scores, ids = self.index.search(q_vec, top_k)
        results = []
        for vid, score in zip(ids[0], scores[0]):
            if vid != -1:
                results.append((int(vid), float(score)))
        return results
```

---

## 7. Lexical Search Index (Rank-BM25)

### 7.1 Identifier-Aware Tokenizer
Standard whitespace/punctuation tokenizers break programming identifiers (`get_user_by_id`, `CamelCase`, `app.core.config`). The custom tokenizer preserves both the unified token and split components:
1. Matches words, dots, dashes, underscores: `r"[a-zA-Z0-9_\-\.\/]+"`
2. Retains the full token (lowercased).
3. Splits on dots/slashes (paths).
4. Splits on underscores and camelCase boundaries.

```python
import re

def tokenize(text: str) -> List[str]:
    tokens = []
    candidates = re.findall(r"[a-zA-Z0-9_\-\.\/]+", text)
    for cand in candidates:
        cand_lower = cand.lower().strip(".-/")
        if not cand_lower:
            continue
        tokens.append(cand_lower)
        # Split on paths/dots
        for part in re.split(r"[/.]+", cand):
            part_lower = part.lower().strip("_-")
            if part_lower and part_lower != cand_lower:
                tokens.append(part_lower)
            # Split on underscore/hyphen
            for sub in re.split(r"[_\-]+", part):
                if sub and sub.lower() not in tokens:
                    tokens.append(sub.lower())
    return tokens
```

### 7.2 Lucene Positive-Smoothed BM25Okapi
Standard BM25Okapi can assign negative or zero IDF scores when a term occurs in $\ge 50\%$ of documents in small corpora. The engine uses Lucene-standard positive-smoothed IDF:
$$\text{IDF}(q_i) = \ln\left(1 + \frac{N - n(q_i) + 0.5}{n(q_i) + 0.5}\right)$$

```python
import math
from rank_bm25 import BM25Okapi

class RobustBM25(BM25Okapi):
    def _calc_idf(self, nd):
        self.idf = {}
        for word, freq in nd.items():
            self.idf[word] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))
        self.average_idf = sum(self.idf.values()) / max(len(self.idf), 1)
```

---

## 8. Hybrid Retrieval & Reciprocal Rank Fusion (RRF)

### 8.1 Retrieval Flow
1. Take query $Q$.
2. **Dense Search:** Retrieve Top-$M$ (default $M=50$) from FAISS.
3. **Lexical Search:** Retrieve Top-$M$ (default $M=50$) from BM25.
4. **Reciprocal Rank Fusion:**
   For each candidate chunk $d$:
   $$\text{RRF}(d) = \sum_{m \in \{\text{dense}, \text{lexical}\}} \frac{1}{k + \text{rank}_m(d)}$$
   * Smoothing constant: $k = 60$.
   * $\text{rank}_m(d)$ is 1-indexed (1st place $= 1$, 2nd place $= 2$, etc.). If a document is missing from a retriever's top-$M$, that term is omitted.
5. Sort candidates descending by $\text{RRF}(d)$.
6. Hydrate the top results by querying SQLite with `chunk_id` / `vector_id` to attach document title, path, snippet text, and badge coordinates.

### 8.2 RRF Implementation
```python
def compute_rrf(dense_chunk_ids: List[str], lexical_chunk_ids: List[str], k: int = 60):
    scores = {}
    dense_ranks = {}
    lex_ranks = {}

    for rank, cid in enumerate(dense_chunk_ids, start=1):
        dense_ranks[cid] = rank
        scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank))

    for rank, cid in enumerate(lexical_chunk_ids, start=1):
        lex_ranks[cid] = rank
        scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank))

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {
            "chunk_id": cid,
            "rrf_score": score,
            "hybrid_rank": idx,
            "dense_rank": dense_ranks.get(cid),
            "lexical_rank": lex_ranks.get(cid),
        }
        for idx, (cid, score) in enumerate(ranked, start=1)
    ]
```

---

## 9. Python Notebook (`.ipynb`) Cell-by-Cell Structure

To implement this in a single Python Notebook, structure the cells as follows:

1. **Cell 1: Environment & Imports**
   - Install dependencies and import `fitz`, `pptx`, `docx`, `sqlite3`, `numpy`, `faiss`, `sentence_transformers`, `rank_bm25`.
2. **Cell 2: Extraction Utilities**
   - Functions: `extract_pdf`, `extract_docx`, `extract_pptx`, `extract_text_file`.
3. **Cell 3: Chunker Class**
   - Sliding-window tokenizer and `Chunk` generator with location coordinates.
4. **Cell 4: SQLite Database Class**
   - In-memory (`:memory:`) or file-based SQLite database with `documents` and `passages` tables.
5. **Cell 5: Dense Index Class**
   - FAISS `IndexIDMap2` + `all-MiniLM-L6-v2` with unit L2 normalization.
6. **Cell 6: Lexical Index Class**
   - Custom `tokenize()` function + `RobustBM25` with positive smoothed IDF.
7. **Cell 7: Indexing Pipeline Function (`index_directory(path)`)**
   - Scans files, extracts text, chunks passages, inserts records into SQLite, embeds into FAISS, adds tokenized corpus to BM25.
8. **Cell 8: Hybrid Search & RRF Function (`search(query, top_k=10)`)**
   - Queries dense & lexical indices, merges with RRF ($k=60$), hydrates passages from SQLite, prints formatted results table.
9. **Cell 9: Live Demo & Verification**
   - Indexes sample dummy files (e.g. PDF or Markdown) and runs queries demonstrating both semantic matching (synonyms/concepts) and exact keyword matching (code/names).
