from typing import List, Tuple

from cli.retrieval.embeddings import EmbeddingGenerator
from cli.storage.vector_store import FAISSVectorStore


class DenseRetriever:
    """Performs semantic vector retrieval using embeddings and FAISS IndexFlatIP."""

    def __init__(self, vector_store: FAISSVectorStore, embedding_generator: EmbeddingGenerator):
        self.vector_store = vector_store
        self.embedding_generator = embedding_generator

    def retrieve(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """Encode query and return top-k (chunk_id, cosine_similarity_score)."""
        query_vec = self.embedding_generator.encode(query)[0]
        return self.vector_store.search(query_vec, top_k=top_k)
