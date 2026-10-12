from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class DocumentMetadata:
    """Metadata for an indexed document file."""
    doc_id: str
    file_path: str
    filename: str
    file_type: str
    size_bytes: int
    modified_at: float
    indexed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    chunk_count: int = 0


@dataclass
class ChunkMetadata:
    """Metadata for a discrete document passage/chunk."""
    chunk_id: str
    doc_id: str
    chunk_index: int
    text: str
    location_type: str  # "page", "slide", "lines", "heading"
    location_value: str  # e.g., "Page 3", "Slide 5", "Lines 1-45", "Section: Introduction"
    char_length: int
    token_count: int


@dataclass
class SearchResult:
    """Unified search result entry."""
    chunk_id: str
    doc_id: str
    filename: str
    file_path: str
    location: str
    text: str
    score: float
    dense_rank: Optional[int] = None
    bm25_rank: Optional[int] = None
    dense_score: Optional[float] = None
    bm25_score: Optional[float] = None


@dataclass
class IndexStats:
    """Summary statistics for the current index and database."""
    total_documents: int
    total_chunks: int
    total_tokens: int
    db_size_bytes: int
    faiss_size_bytes: int
    bm25_size_bytes: int
    file_types: Dict[str, int] = field(default_factory=dict)
    last_indexed_at: Optional[str] = None


@dataclass
class EvaluationMetrics:
    """Evaluation metrics for information retrieval comparison."""
    method: str
    k: int
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg: float
