# Semanty CLI — Document Search & Retrieval Engine

The dedicated command-line interface for **Semanty** (FindIT).
Provides independent terminal-based indexing, hybrid semantic search, BM25Okapi lexical retrieval, and information retrieval evaluation benchmarks without needing the React frontend or web browser.

---

## ⚡ Quick Start

From the `Semanty/` root directory:

```powershell
# 1. Index sample documents or any folder
python cli.py index sample_docs

# 2. Search immediately
python cli.py search "What CGPA do I need to pass?"

# 3. Or launch the live interactive terminal shell
python cli.py interactive
```

---

## 💻 Available Commands

### 1. `python cli.py index <path>`
Index any file or folder recursively:
```powershell
# Index demo coursework documents
python cli.py index sample_docs

# Index your Downloads or Documents folder (only human-readable PDFs, DOCX, PPTX, TXT, MD)
python cli.py index Downloads --docs-only

# Clear previous index and index fresh
python cli.py index "C:\path\to\documents" --clear-first
```

### 2. `python cli.py search "<query>"`
Run search queries with rank breakdown and matched passage snippets:
```powershell
# Default Hybrid RRF search (Dense semantic + BM25Okapi)
python cli.py search "What CGPA do I need to pass?"

# Pure dense semantic vector retrieval
python cli.py search "minimum degree requirements" --mode dense

# Pure lexical keyword matching
python cli.py search "attendance penalties" --mode bm25

# Retrieve custom top-K results
python cli.py search "quiet hours" --top-k 3
```

### 3. `python cli.py interactive`
Interactive search console:
- Enter any question or phrase to search.
- `/mode hybrid`, `/mode dense`, or `/mode bm25` to switch modes on the fly.
- `/topk 10` to adjust results limit.
- `/stats` to view database stats.
- `exit` or `quit` to exit.

### 4. `python cli.py stats`
View total indexed documents, chunks, tokens, and storage size of SQLite, FAISS, and BM25.

### 5. `python cli.py evaluate`
Runs IR benchmark comparison across **TF-IDF, BM25, Dense Semantic, and Hybrid RRF** on **Precision@K, Recall@K, MRR, and NDCG@K**.

### 6. `python cli.py clear`
Wipes the CLI index and database.

---

## 📂 Data Storage

The CLI stores its database and indices in `Semanty/cli/.index_data/`:
- `metadata.db`: SQLite 3 database with WAL mode and foreign keys enabled.
- `faiss_index.bin`: FAISS `IndexFlatIP` 384-dimensional dense vector index.
- `bm25_index.bin`: Persisted `BM25Okapi` ($k_1=1.5, b=0.75$) tokenized corpus and chunk ID mapping.

This directory is completely separate from `Semanty/backend/data/` to prevent any data corruption or conflict with the FastAPI web app.
