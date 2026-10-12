import math
from typing import Dict, List, Optional, Set
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from cli.models import ChunkMetadata, EvaluationMetrics
from cli.retrieval.hybrid import HybridSearchPipeline
from cli.storage.db import SQLiteMetadataStore


class RetrievalEvaluator:
    """
    Evaluates IR methods (TF-IDF, BM25, Dense, Hybrid RRF) against benchmark queries.
    Computes Precision@K, Recall@K, Mean Reciprocal Rank (MRR), and NDCG@K.
    """

    def __init__(self, pipeline: HybridSearchPipeline, db_store: SQLiteMetadataStore):
        self.pipeline = pipeline
        self.db_store = db_store

    def evaluate_benchmark(
        self,
        test_cases: List[Dict[str, any]],
        k_values: List[int] = [1, 3, 5],
    ) -> Dict[str, List[EvaluationMetrics]]:
        all_chunks = self.db_store.get_all_chunks()
        if not all_chunks:
            return {}

        methods = ["tfidf", "bm25", "dense", "hybrid"]
        results: Dict[str, List[EvaluationMetrics]] = {m: [] for m in methods}

        corpus_texts = [c.text for c in all_chunks]
        corpus_ids = [c.chunk_id for c in all_chunks]
        tfidf_vec = TfidfVectorizer(token_pattern=r"(?u)\b\w+\b")
        tfidf_matrix = tfidf_vec.fit_transform(corpus_texts)

        for k in k_values:
            for method in methods:
                precisions: List[float] = []
                recalls: List[float] = []
                mrrs: List[float] = []
                ndcgs: List[float] = []

                for case in test_cases:
                    query = case["query"]
                    gold_ids = set(case.get("relevant_chunk_ids", []))
                    
                    if not gold_ids and "relevant_keywords" in case:
                        kw = case["relevant_keywords"]
                        gold_ids = {
                            c.chunk_id for c in all_chunks
                            if any(k.lower() in c.text.lower() for k in kw)
                        }

                    if not gold_ids:
                        continue

                    retrieved_ids: List[str] = []
                    if method == "tfidf":
                        q_vec = tfidf_vec.transform([query])
                        sims = cosine_similarity(q_vec, tfidf_matrix)[0]
                        top_indices = np.argsort(sims)[::-1][:k]
                        retrieved_ids = [corpus_ids[i] for i in top_indices]
                    elif method == "bm25":
                        hits = self.pipeline.search(query, mode="bm25", top_k=k)
                        retrieved_ids = [h.chunk_id for h in hits]
                    elif method == "dense":
                        hits = self.pipeline.search(query, mode="dense", top_k=k)
                        retrieved_ids = [h.chunk_id for h in hits]
                    elif method == "hybrid":
                        hits = self.pipeline.search(query, mode="hybrid", top_k=k)
                        retrieved_ids = [h.chunk_id for h in hits]

                    hits_in_k = [1 if cid in gold_ids else 0 for cid in retrieved_ids]
                    num_hits = sum(hits_in_k)

                    precision = num_hits / k if k > 0 else 0.0
                    precisions.append(precision)

                    recall = num_hits / len(gold_ids) if len(gold_ids) > 0 else 0.0
                    recalls.append(recall)

                    mrr = 0.0
                    for rank_idx, hit in enumerate(hits_in_k, start=1):
                        if hit == 1:
                            mrr = 1.0 / rank_idx
                            break
                    mrrs.append(mrr)

                    dcg = sum(hit / math.log2(idx + 1) for idx, hit in enumerate(hits_in_k, start=1))
                    ideal_hits = [1] * min(len(gold_ids), k)
                    idcg = sum(1.0 / math.log2(idx + 1) for idx in range(1, len(ideal_hits) + 1))
                    ndcg = (dcg / idcg) if idcg > 0 else 0.0
                    ndcgs.append(ndcg)

                avg_p = float(np.mean(precisions)) if precisions else 0.0
                avg_r = float(np.mean(recalls)) if recalls else 0.0
                avg_mrr = float(np.mean(mrrs)) if mrrs else 0.0
                avg_ndcg = float(np.mean(ndcgs)) if ndcgs else 0.0

                results[method].append(
                    EvaluationMetrics(
                        method=method.upper(),
                        k=k,
                        precision_at_k=round(avg_p, 4),
                        recall_at_k=round(avg_r, 4),
                        mrr=round(avg_mrr, 4),
                        ndcg=round(avg_ndcg, 4),
                    )
                )

        return results
