import tempfile
from pathlib import Path
import pytest

from cli.config import SearchConfig
from cli.models import ChunkMetadata, DocumentMetadata
from cli.parsers.factory import ParserFactory
from cli.storage.bm25_store import BM25LexicalStore
from cli.storage.db import SQLiteMetadataStore


def test_bm25_tokenization_and_search():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = SearchConfig(
            data_dir=Path(tmp_dir),
            bm25_index_path=Path(tmp_dir) / "bm25_index.bin",
            db_path=Path(tmp_dir) / "metadata.db",
            faiss_index_path=Path(tmp_dir) / "faiss_index.bin",
        )

        bm25_store = BM25LexicalStore(config)
        text = "Students must maintain a minimum CGPA of 5.0!"
        tokens = bm25_store.tokenize(text)
        assert tokens == ["students", "must", "maintain", "a", "minimum", "cgpa", "of", "5", "0"]

        corpus_ids = ["chunk_1", "chunk_2"]
        corpus_texts = [
            "Students must obtain a minimum cumulative grade point average of 5.0 to pass.",
            "All campus residents must follow quiet hours during the night.",
        ]
        bm25_store.build_index(corpus_ids, corpus_texts)

        hits = bm25_store.search("cumulative grade point average", top_k=2)
        assert len(hits) > 0
        assert hits[0][0] == "chunk_1"

        bm25_store.save()
        assert config.bm25_index_path.exists()

        new_store = BM25LexicalStore(config)
        assert new_store.load() is True
        assert new_store.chunk_ids == corpus_ids
        assert len(new_store.tokenized_corpus) == 2


def test_sqlite_wal_and_schema():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = SearchConfig(
            data_dir=Path(tmp_dir),
            db_path=Path(tmp_dir) / "metadata.db",
        )
        db = SQLiteMetadataStore(config)
        
        with db._get_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            assert mode.lower() == "wal"

        doc = DocumentMetadata(
            doc_id="doc_1",
            file_path="test.pdf",
            filename="test.pdf",
            file_type=".pdf",
            size_bytes=1024,
            modified_at=1000.0,
            chunk_count=1,
        )
        db.upsert_document(doc)

        chunk = ChunkMetadata(
            chunk_id="chunk_1",
            doc_id="doc_1",
            chunk_index=0,
            text="Hello world test chunk",
            location_type="page",
            location_value="Page 1",
            char_length=22,
            token_count=4,
        )
        db.insert_chunks([chunk])

        stats = db.get_stats()
        assert stats.total_documents == 1
        assert stats.total_chunks == 1


def test_parsers_available():
    factory = ParserFactory()
    assert factory.get_parser(Path("test.pdf")) is not None
    assert factory.get_parser(Path("test.docx")) is not None
    assert factory.get_parser(Path("test.pptx")) is not None
    assert factory.get_parser(Path("test.txt")) is not None
    assert factory.get_parser(Path("test.md")) is not None
