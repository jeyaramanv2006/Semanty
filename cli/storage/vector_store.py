from pathlib import Path
import pickle
from typing import List, Optional, Tuple
import faiss
import numpy as np

from cli.config import DEFAULT_CONFIG, SearchConfig


class FAISSVectorStore:
    """Dense semantic vector store using FAISS IndexFlatIP with L2-normalized embeddings."""

    def __init__(self, config: SearchConfig = DEFAULT_CONFIG):
        self.config = config
        self.dimension = config.embedding_dimension
        self.index_path = config.faiss_index_path
        self.mapping_path = config.data_dir / "faiss_id_map.pkl"
        
        self.index: faiss.IndexFlatIP = faiss.IndexFlatIP(self.dimension)
        self.id_map: List[str] = []
        
        self.load()

    def add(self, embeddings: np.ndarray, chunk_ids: List[str]) -> None:
        """Add L2-normalized vectors and corresponding chunk IDs."""
        if len(chunk_ids) == 0:
            return

        if embeddings.dtype != np.float32:
            embeddings = embeddings.astype(np.float32)

        if self.config.normalize_embeddings:
            faiss.normalize_L2(embeddings)

        self.index.add(embeddings)
        self.id_map.extend(chunk_ids)

    def search(self, query_vector: np.ndarray, top_k: int = 10) -> List[Tuple[str, float]]:
        """Search top-k nearest chunks using Inner Product (cosine similarity)."""
        if self.index.ntotal == 0:
            return []

        if query_vector.ndim == 1:
            query_vector = np.expand_dims(query_vector, axis=0)

        if query_vector.dtype != np.float32:
            query_vector = query_vector.astype(np.float32)

        if self.config.normalize_embeddings:
            faiss.normalize_L2(query_vector)

        k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query_vector, k)

        results: List[Tuple[str, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx != -1 and idx < len(self.id_map):
                results.append((self.id_map[idx], float(score)))

        return results

    def save(self) -> None:
        """Persist FAISS index and chunk_id mapping."""
        self.config.ensure_data_dir()
        faiss.write_index(self.index, str(self.index_path))
        with open(self.mapping_path, "wb") as f:
            pickle.dump(self.id_map, f)

    def load(self) -> bool:
        """Load FAISS index and mapping from disk if available."""
        if self.index_path.exists() and self.mapping_path.exists():
            try:
                self.index = faiss.read_index(str(self.index_path))
                with open(self.mapping_path, "rb") as f:
                    self.id_map = pickle.load(f)
                return True
            except Exception:
                self.index = faiss.IndexFlatIP(self.dimension)
                self.id_map = []
                return False
        return False

    def clear(self) -> None:
        """Clear the in-memory and on-disk index."""
        self.index = faiss.IndexFlatIP(self.dimension)
        self.id_map = []
        if self.index_path.exists():
            self.index_path.unlink()
        if self.mapping_path.exists():
            self.mapping_path.unlink()
