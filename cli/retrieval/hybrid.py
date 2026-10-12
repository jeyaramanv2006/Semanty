from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from cli.config import DEFAULT_CONFIG, SearchConfig
from cli.models import ChunkMetadata, DocumentMetadata, SearchResult
from cli.retrieval.dense import DenseRetriever
from cli.retrieval.lexical import LexicalRetriever
from cli.storage.db import SQLiteMetadataStore


class HybridSearchPipeline:
    """
    Hybrid Retrieval Pipeline (Section 3.4).
    Executes dense and lexical retrieval independently and concurrently,
    combining ranked outputs using Reciprocal Rank Fusion (RRF).
    """

    def __init__(
        self,
        dense_retriever: DenseRetriever,
        lexical_retriever: LexicalRetriever,
        db_store: SQLiteMetadataStore,
        config: SearchConfig = DEFAULT_CONFIG,
    ):
        self.dense_retriever = dense_retriever
        self.lexical_retriever = lexical_retriever
        self.db_store = db_store
        self.config = config

    def search(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10,
        fetch_k: Optional[int] = None,
    ) -> List[SearchResult]:
        """Search documents using mode: 'hybrid', 'dense', or 'bm25'."""
        if fetch_k is None:
            fetch_k = max(top_k * 3, 30)

        if mode == "dense":
            dense_results = self.dense_retriever.retrieve(query, top_k=top_k)
            return self._build_results_from_dense(dense_results)
        elif mode == "bm25":
            bm25_results = self.lexical_retriever.retrieve(query, top_k=top_k)
            return self._build_results_from_bm25(bm25_results)
        elif mode == "hybrid":
            return self._search_hybrid_rrf(query, top_k=top_k, fetch_k=fetch_k)
        else:
            raise ValueError(f"Unknown search mode '{mode}'. Choose 'hybrid', 'dense', or 'bm25'.")

    def _search_hybrid_rrf(self, query: str, top_k: int, fetch_k: int) -> List[SearchResult]:
        """Concurrently execute dense and lexical retrieval, then apply RRF."""
        with ThreadPoolExecutor(max_workers=2) as executor:
            dense_future = executor.submit(self.dense_retriever.retrieve, query, fetch_k)
            bm25_future = executor.submit(self.lexical_retriever.retrieve, query, fetch_k)
            dense_hits: List[Tuple[str, float]] = dense_future.result()
            bm25_hits: List[Tuple[str, float]] = bm25_future.result()

        rrf_scores: Dict[str, float] = {}
        dense_ranks: Dict[str, int] = {}
        dense_scores_map: Dict[str, float] = {}
        bm25_ranks: Dict[str, int] = {}
        bm25_scores_map: Dict[str, float] = {}

        k = self.config.rrf_k

        for rank, (chunk_id, score) in enumerate(dense_hits, start=1):
            dense_ranks[chunk_id] = rank
            dense_scores_map[chunk_id] = score
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + (1.0 / (k + rank))

        for rank, (chunk_id, score) in enumerate(bm25_hits, start=1):
            bm25_ranks[chunk_id] = rank
            bm25_scores_map[chunk_id] = score
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + (1.0 / (k + rank))

        sorted_chunk_ids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)[:top_k]
        if not sorted_chunk_ids:
            return []

        chunks = self.db_store.get_chunks_by_ids(sorted_chunk_ids)
        doc_ids = list({c.doc_id for c in chunks.values()})
        docs = {d.doc_id: d for d in self.db_store.get_all_documents() if d.doc_id in doc_ids}

        results: List[SearchResult] = []
        for cid in sorted_chunk_ids:
            chunk = chunks.get(cid)
            if not chunk:
                continue
            doc = docs.get(chunk.doc_id)
            filename = doc.filename if doc else "Unknown"
            file_path = doc.file_path if doc else ""

            results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    filename=filename,
                    file_path=file_path,
                    location=chunk.location_value,
                    text=chunk.text,
                    score=rrf_scores[cid],
                    dense_rank=dense_ranks.get(cid),
                    bm25_rank=bm25_ranks.get(cid),
                    dense_score=dense_scores_map.get(cid),
                    bm25_score=bm25_scores_map.get(cid),
                )
            )

        return results

    def _build_results_from_dense(self, dense_hits: List[Tuple[str, float]]) -> List[SearchResult]:
        if not dense_hits:
            return []
        chunk_ids = [cid for cid, _ in dense_hits]
        chunks = self.db_store.get_chunks_by_ids(chunk_ids)
        doc_ids = list({c.doc_id for c in chunks.values()})
        docs = {d.doc_id: d for d in self.db_store.get_all_documents() if d.doc_id in doc_ids}

        results: List[SearchResult] = []
        for rank, (cid, score) in enumerate(dense_hits, start=1):
            chunk = chunks.get(cid)
            if not chunk:
                continue
            doc = docs.get(chunk.doc_id)
            results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    filename=doc.filename if doc else "Unknown",
                    file_path=doc.file_path if doc else "",
                    location=chunk.location_value,
                    text=chunk.text,
                    score=score,
                    dense_rank=rank,
                    dense_score=score,
                )
            )
        return results

    def _build_results_from_bm25(self, bm25_hits: List[Tuple[str, float]]) -> List[SearchResult]:
        if not bm25_hits:
            return []
        chunk_ids = [cid for cid, _ in bm25_hits]
        chunks = self.db_store.get_chunks_by_ids(chunk_ids)
        doc_ids = list({c.doc_id for c in chunks.values()})
        docs = {d.doc_id: d for d in self.db_store.get_all_documents() if d.doc_id in doc_ids}

        results: List[SearchResult] = []
        for rank, (cid, score) in enumerate(bm25_hits, start=1):
            chunk = chunks.get(cid)
            if not chunk:
                continue
            doc = docs.get(chunk.doc_id)
            results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    filename=doc.filename if doc else "Unknown",
                    file_path=doc.file_path if doc else "",
                    location=chunk.location_value,
                    text=chunk.text,
                    score=score,
                    bm25_rank=rank,
                    bm25_score=score,
                )
            )
        return results
