"""
FindIT Hybrid Search & Reciprocal Rank Fusion (RRF) Service
Orchestrates dense semantic search (FAISS) and lexical term search (BM25),
fuses candidate ranks using Reciprocal Rank Fusion (k=60), and enriches
passages with metadata and precise source locations from SQLite.
"""

import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel

from app.core import config
from app.db.database import get_db
from app.embeddings.embedder import get_embedder, EmbeddingEngine
from app.indexing.faiss_index import get_faiss_index, FaissIndex
from app.indexing.bm25_index import get_bm25_index, BM25Index

logger = logging.getLogger("findit.search_service")

RRF_K = 60  # Empirically proven smoothing constant
DEFAULT_CANDIDATE_POOL = 50  # Top M candidates from each retriever


class SearchResultItem(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    canonical_path: str
    display_path: str
    file_type: str
    location_label: str
    passage_preview: str
    hybrid_rank: int
    semantic_rank: Optional[int] = None
    lexical_rank: Optional[int] = None
    rrf_score: float


class SearchResponse(BaseModel):
    query: str
    total_available: int
    results: List[SearchResultItem]
    next_offset: Optional[int] = None


class PassageDetailResponse(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    canonical_path: str
    display_path: str
    file_type: str
    location_label: str
    text: str
    page_number: Optional[int] = None
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    slide_number: Optional[int] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    section_heading: Optional[str] = None
    paragraph_index: Optional[int] = None
    chunk_ordinal: int
    surrounding_context_before: Optional[str] = None
    surrounding_context_after: Optional[str] = None


def format_display_path(canonical_path: str) -> str:
    """
    Formats the parent folder path cleanly, shortening the user home directory to '~'.
    Example: 'C:/Users/User/Documents/Projects/file.pdf' -> '~/Documents/Projects'
    """
    try:
        p = Path(canonical_path)
        parent = p.parent
        home = Path.home()
        try:
            rel = parent.relative_to(home)
            formatted = f"~/{str(rel).replace('\\', '/')}"
            return formatted
        except ValueError:
            return str(parent).replace("\\", "/")
    except Exception:
        return os.path.dirname(canonical_path).replace("\\", "/")


def build_location_label(row: Dict[str, Any]) -> str:
    """
    Constructs a trustworthy, human-readable source location coordinate badge.
    """
    page_number = row.get("page_number")
    start_page = row.get("start_page")
    end_page = row.get("end_page")
    slide_number = row.get("slide_number")
    start_line = row.get("start_line")
    end_line = row.get("end_line")
    section_heading = row.get("section_heading")
    chunk_ordinal = row.get("chunk_ordinal", 0)

    if slide_number is not None:
        return f"Slide {slide_number}"

    if page_number is not None:
        if end_page is not None and end_page != page_number:
            return f"Pages {page_number}–{end_page}"
        return f"Page {page_number}"

    if start_page is not None:
        if end_page is not None and end_page != start_page:
            return f"Pages {start_page}–{end_page}"
        return f"Page {start_page}"

    if start_line is not None:
        if end_line is not None and end_line != start_line:
            return f"Lines {start_line}–{end_line}"
        return f"Line {start_line}"

    if section_heading:
        return f"Section: {section_heading}"

    return f"Passage {int(chunk_ordinal) + 1}"


def create_passage_preview(text: str, max_chars: int = 240) -> str:
    """
    Creates a clean, single-paragraph text preview snippet with ellipsis if truncated.
    """
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "..."


def compute_rrf_scores(
    semantic_chunk_ids: List[str],
    lexical_chunk_ids: List[str],
    k: int = RRF_K,
) -> List[Dict[str, Any]]:
    """
    Computes Reciprocal Rank Fusion scores across candidate pools:
    RRF(d) = sum_{r in R} 1 / (k + rank_r(d))
    """
    merged: Dict[str, Dict[str, Any]] = {}

    for rank_idx, chunk_id in enumerate(semantic_chunk_ids):
        sem_rank = rank_idx + 1
        if chunk_id not in merged:
            merged[chunk_id] = {
                "chunk_id": chunk_id,
                "semantic_rank": sem_rank,
                "lexical_rank": None,
                "rrf_score": 0.0,
            }
        else:
            merged[chunk_id]["semantic_rank"] = sem_rank

        merged[chunk_id]["rrf_score"] += 1.0 / (k + sem_rank)

    for rank_idx, chunk_id in enumerate(lexical_chunk_ids):
        lex_rank = rank_idx + 1
        if chunk_id not in merged:
            merged[chunk_id] = {
                "chunk_id": chunk_id,
                "semantic_rank": None,
                "lexical_rank": lex_rank,
                "rrf_score": 0.0,
            }
        else:
            merged[chunk_id]["lexical_rank"] = lex_rank

        merged[chunk_id]["rrf_score"] += 1.0 / (k + lex_rank)

    # Sort descending by fused RRF score
    ranked_candidates = list(merged.values())
    ranked_candidates.sort(key=lambda x: x["rrf_score"], reverse=True)

    # Assign 1-indexed hybrid rank
    for h_rank, cand in enumerate(ranked_candidates, start=1):
        cand["hybrid_rank"] = h_rank
        # Round score to 5 decimal places for clean representation
        cand["rrf_score"] = round(cand["rrf_score"], 5)

    return ranked_candidates


class SearchService:
    """
    Executes hybrid search pipeline:
    1. Query embedding via SentenceTransformer
    2. Dense candidate retrieval via FAISS (top M)
    3. Lexical candidate retrieval via BM25 (top M)
    4. Reciprocal Rank Fusion calculation (k=60)
    5. Database hydration & pagination
    """

    def __init__(
        self,
        embedder: Optional[EmbeddingEngine] = None,
        faiss_index: Optional[FaissIndex] = None,
        bm25_index: Optional[BM25Index] = None,
        db_path: Optional[Path] = None,
        faiss_idx: Optional[FaissIndex] = None,
        bm25_idx: Optional[BM25Index] = None,
    ):
        self._embedder = embedder
        self._faiss_index = faiss_index or faiss_idx
        self._bm25_index = bm25_index or bm25_idx
        self.db_path = db_path

    @property
    def embedder(self) -> EmbeddingEngine:
        return self._embedder or get_embedder()

    @property
    def faiss_index(self) -> FaissIndex:
        return self._faiss_index or get_faiss_index()

    @property
    def bm25_index(self) -> BM25Index:
        return self._bm25_index or get_bm25_index()

    def search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        pool_size: int = DEFAULT_CANDIDATE_POOL,
    ) -> SearchResponse:
        """
        Executes end-to-end hybrid retrieval for a search query.
        Always returns the backend's unified RRF ordering. Retriever ranks remain
        available internally for diagnostics and tests.
        """
        stripped_query = query.strip()
        if not stripped_query:
            return SearchResponse(query=query, total_available=0, results=[], next_offset=None)

        # 1. FAISS dense candidate retrieval
        query_vector = self.embedder.embed_query(stripped_query)
        faiss_candidates = self.faiss_index.search(query_vector, top_k=pool_size)

        semantic_chunk_ids: List[str] = []
        for cand in faiss_candidates:
            if cand.chunk_id:
                semantic_chunk_ids.append(cand.chunk_id)

        # 2. BM25 lexical candidate retrieval
        bm25_candidates = self.bm25_index.search(stripped_query, top_k=pool_size)
        lexical_chunk_ids = [c.chunk_id for c in bm25_candidates]

        # 3. Reciprocal Rank Fusion (RRF)
        fused_candidates = compute_rrf_scores(
            semantic_chunk_ids=semantic_chunk_ids,
            lexical_chunk_ids=lexical_chunk_ids,
            k=RRF_K,
        )

        total_available = len(fused_candidates)
        if total_available == 0:
            return SearchResponse(query=query, total_available=0, results=[], next_offset=None)

        # 4. Preserve fusion order. Clients must not re-rank by retriever.
        ranked_candidates = fused_candidates

        # 5. Paginate candidates
        paginated_candidates = ranked_candidates[offset : offset + limit]
        target_chunk_ids = [c["chunk_id"] for c in paginated_candidates]

        # 5. Hydrate from SQLite
        metadata_map: Dict[str, Dict[str, Any]] = {}
        if target_chunk_ids:
            with get_db(self.db_path) as conn:
                cursor = conn.cursor()
                placeholders = ",".join("?" for _ in target_chunk_ids)
                query_sql = f"""
                    SELECT p.chunk_id, p.document_id, p.chunk_ordinal, p.text,
                           p.page_number, p.start_page, p.end_page, p.slide_number,
                           p.start_line, p.end_line, p.section_heading, p.paragraph_index,
                           d.filename, d.canonical_path, d.file_type
                    FROM passages p
                    JOIN documents d ON p.document_id = d.document_id
                    WHERE p.chunk_id IN ({placeholders});
                """
                cursor.execute(query_sql, target_chunk_ids)
                rows = cursor.fetchall()
                for r in rows:
                    metadata_map[r["chunk_id"]] = dict(r)

        # 6. Assemble final enriched result objects
        results: List[SearchResultItem] = []
        for cand in paginated_candidates:
            cid = cand["chunk_id"]
            db_row = metadata_map.get(cid, {})

            filename = db_row.get("filename", f"{cid}.txt")
            canonical_path = db_row.get("canonical_path", "")
            file_type = db_row.get("file_type", "txt")
            text = db_row.get("text", "")

            results.append(
                SearchResultItem(
                    chunk_id=cid,
                    document_id=db_row.get("document_id", "doc_unknown"),
                    filename=filename,
                    canonical_path=canonical_path,
                    display_path=format_display_path(canonical_path) if canonical_path else "",
                    file_type=file_type,
                    location_label=build_location_label(db_row),
                    passage_preview=create_passage_preview(text) if text else "",
                    hybrid_rank=cand["hybrid_rank"],
                    semantic_rank=cand["semantic_rank"],
                    lexical_rank=cand["lexical_rank"],
                    rrf_score=cand["rrf_score"],
                )
            )

        next_offset = (offset + limit) if (offset + limit < total_available) else None

        return SearchResponse(
            query=query,
            total_available=total_available,
            results=results,
            next_offset=next_offset,
        )

    def get_passage_detail(self, chunk_id: str) -> Optional[PassageDetailResponse]:
        """
        Retrieves full raw passage text, document metadata, and surrounding passage context.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT p.chunk_id, p.document_id, p.chunk_ordinal, p.text,
                       p.page_number, p.start_page, p.end_page, p.slide_number,
                       p.start_line, p.end_line, p.section_heading, p.paragraph_index,
                       d.filename, d.canonical_path, d.file_type
                FROM passages p
                JOIN documents d ON p.document_id = d.document_id
                WHERE p.chunk_id = ?;
                """,
                (chunk_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            p_data = dict(row)
            doc_id = p_data["document_id"]
            ordinal = p_data["chunk_ordinal"]

            # Query surrounding context (previous and next chunk in same document)
            context_before = None
            context_after = None

            if ordinal > 0:
                cursor.execute(
                    "SELECT text FROM passages WHERE document_id = ? AND chunk_ordinal = ?;",
                    (doc_id, ordinal - 1),
                )
                prev_row = cursor.fetchone()
                if prev_row:
                    context_before = prev_row["text"]

            cursor.execute(
                "SELECT text FROM passages WHERE document_id = ? AND chunk_ordinal = ?;",
                (doc_id, ordinal + 1),
            )
            next_row = cursor.fetchone()
            if next_row:
                context_after = next_row["text"]

        canonical_path = p_data["canonical_path"]
        return PassageDetailResponse(
            chunk_id=chunk_id,
            document_id=doc_id,
            filename=p_data["filename"],
            canonical_path=canonical_path,
            display_path=format_display_path(canonical_path),
            file_type=p_data["file_type"],
            location_label=build_location_label(p_data),
            text=p_data["text"],
            page_number=p_data["page_number"],
            start_page=p_data["start_page"],
            end_page=p_data["end_page"],
            slide_number=p_data["slide_number"],
            start_line=p_data["start_line"],
            end_line=p_data["end_line"],
            section_heading=p_data["section_heading"],
            paragraph_index=p_data["paragraph_index"],
            chunk_ordinal=ordinal,
            surrounding_context_before=context_before,
            surrounding_context_after=context_after,
        )


# Global singleton instance
_SEARCH_SERVICE_INSTANCE: Optional[SearchService] = None


def get_search_service() -> SearchService:
    global _SEARCH_SERVICE_INSTANCE
    if _SEARCH_SERVICE_INSTANCE is None:
        _SEARCH_SERVICE_INSTANCE = SearchService()
    return _SEARCH_SERVICE_INSTANCE
