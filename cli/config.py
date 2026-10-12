from dataclasses import dataclass, field
from pathlib import Path
from typing import Set


@dataclass(frozen=True)
class SearchConfig:
    """CLI Search System configuration parameters."""
    
    # Storage paths (isolated in cli/.index_data)
    data_dir: Path = Path(__file__).resolve().parent / ".index_data"
    db_path: Path = Path(__file__).resolve().parent / ".index_data" / "metadata.db"
    faiss_index_path: Path = Path(__file__).resolve().parent / ".index_data" / "faiss_index.bin"
    bm25_index_path: Path = Path(__file__).resolve().parent / ".index_data" / "bm25_index.bin"
    
    # Embedding Model
    embedding_model_name: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    normalize_embeddings: bool = True
    
    # BM25 Parameters (Section 3.3)
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    bm25_version: str = "1.0.0"
    tokenizer_regex: str = r"\b\w+\b"
    
    # Reciprocal Rank Fusion (RRF Section 3.4)
    rrf_k: int = 60
    
    # Chunking Strategy
    chunk_size: int = 500  # Target character length per chunk
    chunk_overlap: int = 80  # Character overlap between adjacent chunks
    
    # Supported File Extensions
    supported_extensions: Set[str] = field(default_factory=lambda: {
        ".pdf",
        ".docx",
        ".pptx",
        ".txt",
        ".md",
        ".markdown",
        ".py",
        ".json",
        ".csv",
        ".log",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".js",
        ".ts",
        ".html",
        ".css",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
    })

    # Ignored directory names (e.g., package managers, builds, caches)
    ignored_directories: Set[str] = field(default_factory=lambda: {
        "node_modules",
        ".git",
        "venv",
        ".venv",
        "env",
        "__pycache__",
        "dist",
        "build",
        ".idea",
        ".vscode",
        "site-packages",
        "target",
        "vendor",
        ".gradle",
        "AppData",
        "bin",
        "obj",
    })

    # Limits
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MB limit per file
    max_chunks_per_doc: int = 1500  # Safety threshold per document

    def ensure_data_dir(self) -> None:
        """Create data directory if it does not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


DEFAULT_CONFIG = SearchConfig()
