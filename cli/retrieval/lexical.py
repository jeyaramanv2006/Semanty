from typing import List, Tuple

from cli.storage.bm25_store import BM25LexicalStore


class LexicalRetriever:
    """Performs lexical BM25 retrieval using BM25Okapi."""

    def __init__(self, bm25_store: BM25LexicalStore):
        self.bm25_store = bm25_store

    def retrieve(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """Tokenize query and return top-k (chunk_id, bm25_score)."""
        return self.bm25_store.search(query, top_k=top_k)
