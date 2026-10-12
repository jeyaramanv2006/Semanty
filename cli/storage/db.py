from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional

from cli.config import DEFAULT_CONFIG, SearchConfig
from cli.models import ChunkMetadata, DocumentMetadata, IndexStats


class SQLiteMetadataStore:
    """Relational SQLite metadata store with WAL mode and foreign keys enabled."""

    def __init__(self, config: SearchConfig = DEFAULT_CONFIG):
        self.config = config
        self.db_path = config.db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        self.config.ensure_data_dir()
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # Requirement: WAL mode and foreign keys enabled
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id TEXT PRIMARY KEY,
                    file_path TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    modified_at REAL NOT NULL,
                    indexed_at TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    location_type TEXT NOT NULL,
                    location_value TEXT NOT NULL,
                    char_length INTEGER NOT NULL,
                    token_count INTEGER NOT NULL,
                    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
                );
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);")
            conn.commit()

    def upsert_document(self, doc: DocumentMetadata) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO documents (doc_id, file_path, filename, file_type, size_bytes, modified_at, indexed_at, chunk_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    doc_id=excluded.doc_id,
                    filename=excluded.filename,
                    file_type=excluded.file_type,
                    size_bytes=excluded.size_bytes,
                    modified_at=excluded.modified_at,
                    indexed_at=excluded.indexed_at,
                    chunk_count=excluded.chunk_count;
            """, (
                doc.doc_id,
                doc.file_path,
                doc.filename,
                doc.file_type,
                doc.size_bytes,
                doc.modified_at,
                doc.indexed_at,
                doc.chunk_count,
            ))
            conn.commit()

    def insert_chunks(self, chunks: List[ChunkMetadata]) -> None:
        if not chunks:
            return
        with self._get_connection() as conn:
            doc_id = chunks[0].doc_id
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.executemany("""
                INSERT INTO chunks (chunk_id, doc_id, chunk_index, text, location_type, location_value, char_length, token_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (c.chunk_id, c.doc_id, c.chunk_index, c.text, c.location_type, c.location_value, c.char_length, c.token_count)
                for c in chunks
            ])
            conn.commit()

    def get_document_by_path(self, file_path: str) -> Optional[DocumentMetadata]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM documents WHERE file_path = ?", (file_path,)).fetchone()
            if row:
                return DocumentMetadata(
                    doc_id=row["doc_id"],
                    file_path=row["file_path"],
                    filename=row["filename"],
                    file_type=row["file_type"],
                    size_bytes=row["size_bytes"],
                    modified_at=row["modified_at"],
                    indexed_at=row["indexed_at"],
                    chunk_count=row["chunk_count"],
                )
        return None

    def get_all_documents(self) -> List[DocumentMetadata]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY indexed_at DESC").fetchall()
            return [
                DocumentMetadata(
                    doc_id=r["doc_id"],
                    file_path=r["file_path"],
                    filename=r["filename"],
                    file_type=r["file_type"],
                    size_bytes=r["size_bytes"],
                    modified_at=r["modified_at"],
                    indexed_at=r["indexed_at"],
                    chunk_count=r["chunk_count"],
                )
                for r in rows
            ]

    def get_chunks_by_ids(self, chunk_ids: List[str]) -> Dict[str, ChunkMetadata]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM chunks WHERE chunk_id IN ({placeholders})", chunk_ids
            ).fetchall()
            return {
                r["chunk_id"]: ChunkMetadata(
                    chunk_id=r["chunk_id"],
                    doc_id=r["doc_id"],
                    chunk_index=r["chunk_index"],
                    text=r["text"],
                    location_type=r["location_type"],
                    location_value=r["location_value"],
                    char_length=r["char_length"],
                    token_count=r["token_count"],
                )
                for r in rows
            }

    def get_all_chunks(self) -> List[ChunkMetadata]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM chunks ORDER BY doc_id, chunk_index").fetchall()
            return [
                ChunkMetadata(
                    chunk_id=r["chunk_id"],
                    doc_id=r["doc_id"],
                    chunk_index=r["chunk_index"],
                    text=r["text"],
                    location_type=r["location_type"],
                    location_value=r["location_value"],
                    char_length=r["char_length"],
                    token_count=r["token_count"],
                )
                for r in rows
            ]

    def get_stats(self) -> IndexStats:
        with self._get_connection() as conn:
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            token_count = conn.execute("SELECT COALESCE(SUM(token_count), 0) FROM chunks").fetchone()[0]
            last_indexed = conn.execute("SELECT MAX(indexed_at) FROM documents").fetchone()[0]

            type_rows = conn.execute(
                "SELECT file_type, COUNT(*) as cnt FROM documents GROUP BY file_type"
            ).fetchall()
            file_types = {r["file_type"]: r["cnt"] for r in type_rows}

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        faiss_size = self.config.faiss_index_path.stat().st_size if self.config.faiss_index_path.exists() else 0
        bm25_size = self.config.bm25_index_path.stat().st_size if self.config.bm25_index_path.exists() else 0

        return IndexStats(
            total_documents=doc_count,
            total_chunks=chunk_count,
            total_tokens=token_count,
            db_size_bytes=db_size,
            faiss_size_bytes=faiss_size,
            bm25_size_bytes=bm25_size,
            file_types=file_types,
            last_indexed_at=last_indexed,
        )

    def clear(self) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM chunks;")
            conn.execute("DELETE FROM documents;")
            conn.commit()
            conn.execute("VACUUM;")
