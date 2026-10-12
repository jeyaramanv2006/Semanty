"""
FindIT Unit & Integration Tests:
Hybrid Search (RRF), Passage Inspector API & Native OS Launcher.
"""

import os
import tempfile
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import init_db, get_db
from app.embeddings.embedder import EmbeddingEngine, DEFAULT_DIMENSION
from app.indexing.faiss_index import FaissIndex
from app.indexing.bm25_index import BM25Index
from app.services.search_service import (
    SearchService,
    compute_rrf_scores,
    build_location_label,
    create_passage_preview,
    format_display_path,
    RRF_K,
)
from app.services.os_service import OSService, SecurityBoundaryError


@pytest.fixture
def mock_search_env():
    """
    Creates an isolated temporary environment with:
    - Dedicated SQLite database with directories, documents, passages
    - Dedicated FAISS index
    - Dedicated BM25 index
    - Mock files on disk
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_file = tmp_path / "findit_test.db"
        faiss_file = tmp_path / "index_test.faiss"
        bm25_file = tmp_path / "bm25_test.pkl"
        docs_dir = tmp_path / "approved_docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        # 1. Initialize SQLite
        init_db(db_file)

        # 2. Create sample files on disk
        doc1_file = docs_dir / "Architecture_Spec.docx"
        doc1_file.write_text("FAISS vector indexing and SQLite persistence with local loopback binding.", encoding="utf-8")

        doc2_file = docs_dir / "Security_Notes.md"
        doc2_file.write_text("Authentication architecture and bearer token verification guidelines.", encoding="utf-8")

        doc3_file = docs_dir / "Slides.pptx"
        doc3_file.write_text("Presentation on storage architecture and indexing.", encoding="utf-8")

        # 3. Insert records into SQLite
        with get_db(db_file) as conn:
            cursor = conn.cursor()
            # Directory
            cursor.execute(
                """
                INSERT INTO directories (directory_id, canonical_path, display_name, added_at, sync_status)
                VALUES (?, ?, ?, datetime('now'), 'IDLE');
                """,
                ("dir_1", str(docs_dir.resolve()), "Approved Docs"),
            )

            # Documents
            cursor.execute(
                """
                INSERT INTO documents (document_id, directory_id, canonical_path, filename, extension, file_type, size_bytes, modified_time, extraction_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                ("doc_1", "dir_1", str(doc1_file.resolve()), "Architecture_Spec.docx", ".docx", "docx", 1024, 1000, "OK"),
            )
            cursor.execute(
                """
                INSERT INTO documents (document_id, directory_id, canonical_path, filename, extension, file_type, size_bytes, modified_time, extraction_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                ("doc_2", "dir_1", str(doc2_file.resolve()), "Security_Notes.md", ".md", "md", 2048, 2000, "OK"),
            )

            # Passages
            cursor.execute(
                """
                INSERT INTO passages (chunk_id, document_id, chunk_ordinal, text, section_heading, vector_id)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                ("chunk_1_0", "doc_1", 0, "The system utilizes FAISS for vector indexing and enforces SQLite persistence for metadata.", "Storage Architecture & Indexing", 1),
            )
            cursor.execute(
                """
                INSERT INTO passages (chunk_id, document_id, chunk_ordinal, text, section_heading, vector_id)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                ("chunk_1_1", "doc_1", 1, "Next section discusses local loopback binding and process-isolated authentication.", "Network Security", 2),
            )
            cursor.execute(
                """
                INSERT INTO passages (chunk_id, document_id, chunk_ordinal, text, start_line, end_line, vector_id)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                ("chunk_2_0", "doc_2", 0, "Authentication architecture relies on short-lived bearer tokens verified locally.", 1, 25, 3),
            )

        # 4. Initialize FAISS index
        faiss_idx = FaissIndex(dimension=DEFAULT_DIMENSION, index_path=faiss_file)
        np.random.seed(42)
        v1 = np.random.randn(DEFAULT_DIMENSION).astype(np.float32)
        v2 = np.random.randn(DEFAULT_DIMENSION).astype(np.float32)
        v3 = np.random.randn(DEFAULT_DIMENSION).astype(np.float32)
        vectors = np.stack([v1, v2, v3])
        faiss_idx.add_vectors(vectors, [1, 2, 3], ["chunk_1_0", "chunk_1_1", "chunk_2_0"])

        # 5. Initialize BM25 index
        bm25_idx = BM25Index(index_path=bm25_file)
        bm25_idx.add_documents(
            ["chunk_1_0", "chunk_1_1", "chunk_2_0"],
            [
                "The system utilizes FAISS for vector indexing and enforces SQLite persistence for metadata.",
                "Next section discusses local loopback binding and process-isolated authentication.",
                "Authentication architecture relies on short-lived bearer tokens verified locally.",
            ],
        )

        yield {
            "tmp_path": tmp_path,
            "db_file": db_file,
            "docs_dir": docs_dir,
            "doc1_file": doc1_file,
            "doc2_file": doc2_file,
            "faiss_idx": faiss_idx,
            "bm25_idx": bm25_idx,
        }


class TestRRFCalculation:
    """Tests for Reciprocal Rank Fusion (Phase 9)."""

    def test_rrf_scoring_formula(self):
        """Verifies exact RRF formula: 1 / (60 + rank)."""
        semantic_pool = ["chunk_a", "chunk_b"]
        lexical_pool = ["chunk_a", "chunk_c"]

        results = compute_rrf_scores(semantic_pool, lexical_pool, k=60)

        assert len(results) == 3
        # chunk_a is rank 1 in both: score = 1/61 + 1/61 = 0.03278
        assert results[0]["chunk_id"] == "chunk_a"
        assert results[0]["semantic_rank"] == 1
        assert results[0]["lexical_rank"] == 1
        assert results[0]["hybrid_rank"] == 1
        expected_score = round(1.0 / 61 + 1.0 / 61, 5)
        assert results[0]["rrf_score"] == expected_score

        # chunk_b (rank 2 semantic only) vs chunk_c (rank 2 lexical only)
        assert results[1]["rrf_score"] == round(1.0 / 62, 5)
        assert results[2]["rrf_score"] == round(1.0 / 62, 5)

    def test_rrf_missing_rank_handling(self):
        """Candidate present in only one retriever has None for the missing rank."""
        results = compute_rrf_scores(["chunk_only_sem"], ["chunk_only_lex"], k=60)

        cand_sem = next(r for r in results if r["chunk_id"] == "chunk_only_sem")
        assert cand_sem["semantic_rank"] == 1
        assert cand_sem["lexical_rank"] is None

        cand_lex = next(r for r in results if r["chunk_id"] == "chunk_only_lex")
        assert cand_lex["semantic_rank"] is None
        assert cand_lex["lexical_rank"] == 1


class TestSearchService:
    """Tests for SearchService orchestration (Phase 9 & 10)."""

    def test_search_service_hybrid_query(self, mock_search_env):
        """Queries SearchService and validates returned fields and location badges."""
        service = SearchService(
            faiss_index=mock_search_env["faiss_idx"],
            bm25_index=mock_search_env["bm25_idx"],
            db_path=mock_search_env["db_file"],
        )

        resp = service.search(query="FAISS vector indexing", limit=10)

        assert resp.total_available >= 1
        assert len(resp.results) >= 1
        top = resp.results[0]

        assert top.chunk_id == "chunk_1_0"
        assert top.filename == "Architecture_Spec.docx"
        assert top.file_type == "docx"
        assert top.location_label == "Section: Storage Architecture & Indexing"
        assert "FAISS for vector indexing" in top.passage_preview
        assert top.hybrid_rank == 1
        assert top.rrf_score > 0.0

    def test_search_service_pagination(self, mock_search_env):
        """Verifies limit and offset pagination."""
        service = SearchService(
            faiss_index=mock_search_env["faiss_idx"],
            bm25_index=mock_search_env["bm25_idx"],
            db_path=mock_search_env["db_file"],
        )

        resp_page1 = service.search(query="authentication", limit=1, offset=0)
        assert len(resp_page1.results) == 1
        assert resp_page1.next_offset == 1

        resp_page2 = service.search(query="authentication", limit=1, offset=1)
        assert len(resp_page2.results) >= 1
        assert resp_page2.results[0].chunk_id != resp_page1.results[0].chunk_id

    def test_get_passage_detail_with_context(self, mock_search_env):
        """Verifies retrieval of full passage text and surrounding context."""
        service = SearchService(db_path=mock_search_env["db_file"])

        detail = service.get_passage_detail("chunk_1_0")
        assert detail is not None
        assert detail.chunk_id == "chunk_1_0"
        assert detail.filename == "Architecture_Spec.docx"
        assert "FAISS for vector indexing" in detail.text
        assert detail.section_heading == "Storage Architecture & Indexing"
        assert detail.surrounding_context_before is None
        # Next chunk text should be present
        assert detail.surrounding_context_after is not None
        assert "local loopback binding" in detail.surrounding_context_after

    def test_get_passage_detail_nonexistent(self, mock_search_env):
        service = SearchService(db_path=mock_search_env["db_file"])
        assert service.get_passage_detail("nonexistent_chunk") is None


class TestOSService:
    """Tests for OS Integration and Security Confinement (Phase 11)."""

    def test_open_containing_folder_confinement_allowed(self, mock_search_env):
        """File inside approved registered directory passes confinement check."""
        target_file = mock_search_env["doc1_file"]
        revealed = OSService.open_containing_folder(
            target_file,
            validate_confinement=True,
            db_path=mock_search_env["db_file"],
            dry_run=True,
        )
        assert Path(revealed).resolve() == target_file.resolve()

    def test_open_containing_folder_confinement_denied(self, mock_search_env):
        """File outside approved registered directory raises SecurityBoundaryError."""
        outside_file = mock_search_env["tmp_path"] / "outside.txt"
        outside_file.write_text("Unauthorized file content", encoding="utf-8")

        with pytest.raises(SecurityBoundaryError):
            OSService.open_containing_folder(
                outside_file,
                validate_confinement=True,
                db_path=mock_search_env["db_file"],
                dry_run=True,
            )

    def test_open_containing_folder_nonexistent_file(self, mock_search_env):
        """Non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            OSService.open_containing_folder(
                mock_search_env["docs_dir"] / "missing.txt",
                validate_confinement=True,
                db_path=mock_search_env["db_file"],
                dry_run=True,
            )


class TestAPIEndpoints:
    """Tests for FastAPI HTTP routers (search, passages, os_actions)."""

    def test_search_api_post_and_get(self, mock_search_env, monkeypatch):
        """Tests POST /api/search and GET /api/search endpoints."""
        service = SearchService(
            faiss_index=mock_search_env["faiss_idx"],
            bm25_index=mock_search_env["bm25_idx"],
            db_path=mock_search_env["db_file"],
        )
        monkeypatch.setattr("app.api.search.get_search_service", lambda: service)

        client = TestClient(app)

        # POST /api/search
        resp_post = client.post("/api/search", json={"query": "architecture", "limit": 10})
        assert resp_post.status_code == 200
        data_post = resp_post.json()
        assert "results" in data_post
        assert data_post["query"] == "architecture"

        # Technical ranking modes are no longer part of the user-facing contract.
        resp_mode = client.post("/api/search", json={"query": "architecture", "limit": 10, "ranking_mode": "semantic"})
        assert resp_mode.status_code == 422

        # GET /api/search remains a hybrid-only query-string endpoint.
        resp_get = client.get("/api/search?q=architecture&limit=5")
        assert resp_get.status_code == 200
        data_get = resp_get.json()
        assert "results" in data_get
        assert len(data_get["results"]) <= 5
        resp_get_mode = client.get("/api/search?q=architecture&ranking_mode=lexical")
        assert resp_get_mode.status_code == 422

    def test_passage_detail_api(self, mock_search_env, monkeypatch):
        """Tests GET /api/passages/{chunk_id}."""
        service = SearchService(db_path=mock_search_env["db_file"])
        monkeypatch.setattr("app.api.passages.get_search_service", lambda: service)

        client = TestClient(app)

        # Valid chunk
        resp = client.get("/api/passages/chunk_1_0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chunk_id"] == "chunk_1_0"
        assert data["filename"] == "Architecture_Spec.docx"

        # 404 for invalid chunk
        resp_404 = client.get("/api/passages/invalid_chunk_999")
        assert resp_404.status_code == 404

    def test_open_location_api_confinement(self, mock_search_env, monkeypatch):
        """Tests POST /api/open-location with valid, unauthorized, and missing paths."""
        monkeypatch.setattr("app.core.config.DATABASE_PATH", mock_search_env["db_file"])
        monkeypatch.setattr("subprocess.Popen", lambda args: None)

        client = TestClient(app)

        # 1. Valid path inside registered directory
        valid_path = str(mock_search_env["doc1_file"].resolve())
        resp = client.post("/api/open-location", json={"path": valid_path})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 2. Path outside registered directory -> 403 Forbidden
        outside_path = str(mock_search_env["tmp_path"] / "outside.txt")
        Path(outside_path).write_text("outside", encoding="utf-8")
        resp_403 = client.post("/api/open-location", json={"path": outside_path})
        assert resp_403.status_code == 403

        # 3. Nonexistent path -> 404 Not Found
        missing_path = str(mock_search_env["docs_dir"] / "nonexistent.docx")
        resp_404 = client.post("/api/open-location", json={"path": missing_path})
        assert resp_404.status_code == 404

        # 4. By document_id -> 200
        resp_doc = client.post("/api/documents/doc_1/open-folder")
        assert resp_doc.status_code == 200
        assert resp_doc.json()["success"] is True
