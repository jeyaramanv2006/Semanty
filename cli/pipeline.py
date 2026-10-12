import hashlib
from pathlib import Path
from typing import Callable, List, Optional
import numpy as np

from cli.chunking.text_chunker import TextChunker
from cli.config import DEFAULT_CONFIG, SearchConfig
from cli.models import ChunkMetadata, DocumentMetadata, IndexStats, SearchResult
from cli.parsers.factory import ParserFactory
from cli.retrieval.dense import DenseRetriever
from cli.retrieval.embeddings import EmbeddingGenerator
from cli.retrieval.evaluator import RetrievalEvaluator
from cli.retrieval.hybrid import HybridSearchPipeline
from cli.retrieval.lexical import LexicalRetriever
from cli.storage.bm25_store import BM25LexicalStore
from cli.storage.db import SQLiteMetadataStore
from cli.storage.vector_store import FAISSVectorStore


class DocumentSearchEngine:
    """
    Unified high-level facade for Document Ingestion, Indexing, and Search.
    Can be used by both the Terminal CLI and web backends.
    """

    def __init__(self, config: SearchConfig = DEFAULT_CONFIG):
        self.config = config
        self.config.ensure_data_dir()

        # Storage components
        self.db = SQLiteMetadataStore(config)
        self.vector_store = FAISSVectorStore(config)
        self.bm25_store = BM25LexicalStore(config)

        # Ingestion components
        self.parser_factory = ParserFactory()
        self.chunker = TextChunker(config)

        # Retrieval components
        self.embeddings = EmbeddingGenerator(config)
        self.dense_retriever = DenseRetriever(self.vector_store, self.embeddings)
        self.lexical_retriever = LexicalRetriever(self.bm25_store)
        self.hybrid_pipeline = HybridSearchPipeline(
            dense_retriever=self.dense_retriever,
            lexical_retriever=self.lexical_retriever,
            db_store=self.db,
            config=config,
        )
        self.evaluator = RetrievalEvaluator(self.hybrid_pipeline, self.db)

    def index_path(
        self,
        target_path: Path,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        docs_only: bool = False,
    ) -> int:
        """
        Index a file or directory recursively.
        Returns the number of documents indexed.
        """
        target = Path(target_path).resolve()
        if not target.exists():
            raise FileNotFoundError(f"Path does not exist: {target}")

        target_exts = {".pdf", ".docx", ".pptx", ".txt", ".md", ".markdown"} if docs_only else self.config.supported_extensions

        files_to_index: List[Path] = []
        if target.is_file():
            if target.suffix.lower() in target_exts:
                files_to_index.append(target)
        else:
            for p in target.rglob("*"):
                # Skip hidden files, data directory, and ignored folders
                if any(part.startswith(".") for part in p.parts):
                    continue
                if any(ignored in p.parts for ignored in self.config.ignored_directories):
                    continue
                if p.is_file() and p.suffix.lower() in target_exts:
                    try:
                        if p.stat().st_size <= self.config.max_file_size_bytes:
                            files_to_index.append(p)
                    except OSError:
                        continue

        total_files = len(files_to_index)
        if total_files == 0:
            return 0

        new_docs: List[DocumentMetadata] = []
        new_chunks: List[ChunkMetadata] = []

        for idx, file_path in enumerate(files_to_index, start=1):
            if progress_callback:
                progress_callback(file_path.name, idx, total_files)

            parser = self.parser_factory.get_parser(file_path)
            if not parser:
                continue

            try:
                sections = parser.parse(file_path)
            except Exception:
                continue

            if not sections:
                continue

            doc_id = hashlib.md5(str(file_path).encode("utf-8")).hexdigest()[:12]
            try:
                stat = file_path.stat()
                mtime = stat.st_mtime
                size = stat.st_size
            except OSError:
                mtime = 0.0
                size = 0

            doc_meta = DocumentMetadata(
                doc_id=doc_id,
                file_path=str(file_path),
                filename=file_path.name,
                file_type=file_path.suffix.lower(),
                size_bytes=size,
                modified_at=mtime,
                chunk_count=0,
            )

            chunks = self.chunker.chunk_sections(doc_id, sections)
            if not chunks:
                continue

            if len(chunks) > self.config.max_chunks_per_doc:
                chunks = chunks[:self.config.max_chunks_per_doc]

            doc_meta.chunk_count = len(chunks)
            self.db.upsert_document(doc_meta)
            self.db.insert_chunks(chunks)
            new_docs.append(doc_meta)
            new_chunks.extend(chunks)

        self._rebuild_search_indices(status_callback=lambda msg: print(f"\n[SearchEngine] {msg}", flush=True))
        return len(new_docs)

    def _rebuild_search_indices(self, status_callback: Optional[Callable[[str], None]] = None) -> None:
        """Reconstruct FAISS and BM25 indices to guarantee exact ordering."""
        all_chunks = self.db.get_all_chunks()
        if not all_chunks:
            self.vector_store.clear()
            self.bm25_store.clear()
            return

        chunk_ids = [c.chunk_id for c in all_chunks]
        chunk_texts = [c.text for c in all_chunks]
        total_chunks = len(chunk_texts)

        # 1. Build & Persist BM25 Index (Section 3.3)
        if status_callback:
            status_callback(f"Building BM25 lexical index for {total_chunks:,} chunks...")
        self.bm25_store.build_index(chunk_ids, chunk_texts)
        self.bm25_store.save()

        # 2. Build & Persist FAISS Index
        if status_callback:
            status_callback(f"Generating FAISS dense embeddings for {total_chunks:,} chunks...")
        vectors = self.embeddings.encode(chunk_texts, batch_size=128, show_progress_bar=True)
        self.vector_store.clear()
        self.vector_store.add(vectors, chunk_ids)
        self.vector_store.save()
        if status_callback:
            status_callback(f"FAISS and BM25 indexing complete!")

    def search(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10,
    ) -> List[SearchResult]:
        """Search documents using hybrid, dense, or bm25 mode."""
        return self.hybrid_pipeline.search(query=query, mode=mode, top_k=top_k)

    def get_stats(self) -> IndexStats:
        """Retrieve overview metrics and index sizes."""
        return self.db.get_stats()

    def clear(self) -> None:
        """Wipe database and all index files."""
        self.db.clear()
        self.vector_store.clear()
        self.bm25_store.clear()
