from pathlib import Path
import pickle
import re
from typing import Dict, List, Optional, Tuple
from rank_bm25 import BM25Okapi

from cli.config import DEFAULT_CONFIG, SearchConfig


class BM25LexicalStore:
    """
    Lexical search store implementing BM25Okapi according to Section 3.3.
    Persists tokenized corpus and reconstructs index on load for robustness.
    """

    def __init__(self, config: SearchConfig = DEFAULT_CONFIG):
        self.config = config
        self.index_path = config.bm25_index_path
        self.bm25: Optional[BM25Okapi] = None
        self.chunk_ids: List[str] = []
        self.tokenized_corpus: List[List[str]] = []
        self.load()

    def tokenize(self, text: str) -> List[str]:
        """
        Section 3.3.2: Lowercase alphanumeric token extraction:
        re.findall(r"\\b\\w+\\b", text.lower())
        """
        return re.findall(self.config.tokenizer_regex, text.lower())

    def build_index(self, chunk_ids: List[str], texts: List[str]) -> None:
        """
        Build BM25Okapi index from ordered list of chunk_ids and passages.
        The chunk ID ordering matches the BM25 corpus ordering exactly.
        """
        if len(chunk_ids) != len(texts):
            raise ValueError("chunk_ids and texts lists must have identical lengths")

        self.chunk_ids = list(chunk_ids)
        self.tokenized_corpus = [self.tokenize(t) for t in texts]

        if self.tokenized_corpus:
            self.bm25 = BM25Okapi(
                self.tokenized_corpus,
                k1=self.config.bm25_k1,
                b=self.config.bm25_b,
            )
        else:
            self.bm25 = None

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """
        Search lexical index using BM25Okapi.
        Returns ordered list of (chunk_id, bm25_score) tuples.
        """
        if self.bm25 is None or not self.chunk_ids:
            return []

        tokenized_query = self.tokenize(query)
        if not tokenized_query:
            return []

        scores = self.bm25.get_scores(tokenized_query)
        
        scored_pairs = [(self.chunk_ids[i], float(score)) for i, score in enumerate(scores)]
        scored_pairs.sort(key=lambda x: x[1], reverse=True)

        non_zero = [p for p in scored_pairs if p[1] > 0.0]
        return non_zero[:top_k] if non_zero else scored_pairs[:top_k]

    def save(self) -> None:
        """
        Section 3.3.3: Persist in bm25_index.bin:
        - Reconstructable corpus representation
        - Ordered list of corresponding chunk_id values
        - Tokenizer and index-format version
        """
        self.config.ensure_data_dir()
        data = {
            "version": self.config.bm25_version,
            "tokenizer": "re.findall(r'\\b\\w+\\b', text.lower())",
            "k1": self.config.bm25_k1,
            "b": self.config.bm25_b,
            "chunk_ids": self.chunk_ids,
            "tokenized_corpus": self.tokenized_corpus,
        }
        with open(self.index_path, "wb") as f:
            pickle.dump(data, f)

    def load(self) -> bool:
        """Load persisted index and reconstruct BM25Okapi instance."""
        if not self.index_path.exists():
            return False

        try:
            with open(self.index_path, "rb") as f:
                data = pickle.load(f)

            self.chunk_ids = data.get("chunk_ids", [])
            self.tokenized_corpus = data.get("tokenized_corpus", [])
            k1 = data.get("k1", self.config.bm25_k1)
            b = data.get("b", self.config.bm25_b)

            if self.tokenized_corpus and self.chunk_ids:
                self.bm25 = BM25Okapi(self.tokenized_corpus, k1=k1, b=b)
                return True
            else:
                self.bm25 = None
                return False
        except Exception:
            self.bm25 = None
            self.chunk_ids = []
            self.tokenized_corpus = []
            return False

    def clear(self) -> None:
        """Clear BM25 index and remove persisted file."""
        self.bm25 = None
        self.chunk_ids = []
        self.tokenized_corpus = []
        if self.index_path.exists():
            self.index_path.unlink()
