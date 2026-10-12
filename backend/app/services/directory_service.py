import hashlib
import os
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from app.core import config
from app.db.database import get_db

logger = logging.getLogger("findit.directory_service")

# Directories to skip when scanning
IGNORED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".idea",
    ".vscode",
    "dist",
    "build",
    ".pytest_cache",
    ".agents",
}


class DirectoryConflictError(Exception):
    """Raised when a directory is already registered or overlaps with an existing root."""
    pass


class DirectoryNotFoundError(Exception):
    """Raised when a requested directory is not found."""
    pass


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hash of a file efficiently in 64KB chunks."""
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.warning(f"Failed to compute SHA-256 for {file_path}: {e}")
        return ""


class DirectoryService:
    @staticmethod
    def validate_and_canonicalize(raw_path: str, conn) -> Path:
        """
        Validates the path format, existence, system boundary, and ensures
        no overlap with existing registered directories.
        """
        if not raw_path or not raw_path.strip():
            raise ValueError("Directory path cannot be empty.")

        target = Path(raw_path.strip()).expanduser().resolve()

        if not target.exists():
            raise ValueError(f"Path does not exist: '{target}'")

        if not target.is_dir():
            raise ValueError(f"Path is not a directory: '{target}'")

        # Refuse to index root drives (e.g. C:\ or /)
        if target == target.parent or len(target.parts) <= 1:
            raise ValueError(f"Registering entire system root drive '{target}' is prohibited.")

        # Check against existing registered directories
        cursor = conn.cursor()
        cursor.execute("SELECT directory_id, canonical_path FROM directories;")
        existing_rows = cursor.fetchall()

        normalized_target_str = str(target).replace("\\", "/").rstrip("/").lower()

        for row in existing_rows:
            existing_path = Path(row["canonical_path"]).resolve()
            normalized_existing_str = str(existing_path).replace("\\", "/").rstrip("/").lower()

            if normalized_target_str == normalized_existing_str:
                raise DirectoryConflictError(f"Directory is already registered: '{target}'")

            # Check if target is a subdirectory of existing
            try:
                target.relative_to(existing_path)
                raise DirectoryConflictError(
                    f"Path is a subdirectory of already registered directory: '{existing_path}'"
                )
            except ValueError:
                pass

            # Check if existing is a subdirectory of target
            try:
                existing_path.relative_to(target)
                raise DirectoryConflictError(
                    f"Path contains already registered directory '{existing_path}' as a subdirectory."
                )
            except ValueError:
                pass

        return target

    @classmethod
    def scan_files(cls, directory_path: Path, directory_id: str, conn) -> int:
        """
        Recursively scans directory for supported documents, computes metadata,
        and saves discovered files into documents table.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor = conn.cursor()
        discovered_count = 0

        # Collect current file paths on disk
        for root, dirs, files in os.walk(directory_path, followlinks=False):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d not in IGNORED_DIR_NAMES and not d.startswith(".")]

            for file_name in files:
                file_path = Path(root) / file_name

                # Symlink boundary defense: resolve target and verify containment
                if file_path.is_symlink():
                    try:
                        resolved_target = file_path.resolve()
                        resolved_target.relative_to(directory_path)
                    except ValueError:
                        logger.warning(f"Skipping symlink escaping directory boundary: {file_path}")
                        continue

                # Ignore hidden files, system dotfiles, and Office lock files (~$*)
                if file_name.startswith("~$") or file_name.startswith("."):
                    continue

                ext = file_path.suffix.lower()
                if ext not in config.SUPPORTED_EXTENSIONS:
                    continue

                try:
                    stat = file_path.stat()
                    size_bytes = stat.st_size
                    mtime = stat.st_mtime
                    file_type = config.get_file_type(ext)
                    content_hash = compute_sha256(file_path)
                    canonical_file_path = str(file_path.resolve()).replace("\\", "/")

                    # Insert document record
                    doc_id = "doc_" + uuid.uuid4().hex[:12]
                    cursor.execute(
                        """
                        INSERT INTO documents (
                            document_id, directory_id, canonical_path, filename,
                            extension, file_type, size_bytes, modified_time,
                            content_fingerprint, extraction_status, last_indexed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                        ON CONFLICT(canonical_path) DO UPDATE SET
                            size_bytes = excluded.size_bytes,
                            modified_time = excluded.modified_time,
                            content_fingerprint = excluded.content_fingerprint,
                            last_indexed_at = excluded.last_indexed_at
                        """,
                        (
                            doc_id,
                            directory_id,
                            canonical_file_path,
                            file_name,
                            ext,
                            file_type,
                            size_bytes,
                            int(mtime),
                            content_hash,
                            now_iso,
                        ),
                    )
                    discovered_count += 1
                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {e}")
                    continue

        return discovered_count

    @classmethod
    def register_directory(cls, raw_path: str) -> dict:
        """
        Registers a new approved directory root and queues its initial sync.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            target_path = cls.validate_and_canonicalize(raw_path, conn)
            canonical_path_str = str(target_path).replace("\\", "/")
            directory_id = "dir_" + uuid.uuid4().hex[:8]
            display_name = target_path.name or canonical_path_str

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO directories (
                    directory_id, canonical_path, display_name, added_at, sync_status
                ) VALUES (?, ?, ?, ?, 'SYNCING')
                """,
                (directory_id, canonical_path_str, display_name, now_iso),
            )

        # Queue only after the registration transaction commits, so the worker
        # always observes the new directory row.
        from app.sync.worker import get_sync_worker
        initial_job_id = get_sync_worker().start_sync(
            directory_id,
            job_type="INITIAL_INDEX",
            background=True,
        )

        return {
            "directory": {
                "directory_id": directory_id,
                "canonical_path": canonical_path_str,
                "display_name": display_name,
                "file_count": 0,
                "passage_count": 0,
                "sync_status": "SYNCING",
                "added_at": now_iso,
                "last_sync_completed_at": None,
                "last_error": None,
            },
            "initial_job_id": initial_job_id,
        }

    @staticmethod
    def list_directories() -> list[dict]:
        """
        Returns all registered directories with current document and passage counts.
        """
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 
                    d.directory_id,
                    d.canonical_path,
                    d.display_name,
                    COUNT(DISTINCT doc.document_id) AS file_count,
                    COUNT(DISTINCT p.chunk_id) AS passage_count,
                    d.sync_status,
                    d.last_sync_completed_at,
                    d.last_error
                FROM directories d
                LEFT JOIN documents doc ON d.directory_id = doc.directory_id
                LEFT JOIN passages p ON doc.document_id = p.document_id
                GROUP BY d.directory_id
                ORDER BY d.added_at DESC;
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "directory_id": row["directory_id"],
                    "canonical_path": row["canonical_path"],
                    "display_name": row["display_name"],
                    "file_count": row["file_count"],
                    "passage_count": row["passage_count"],
                    "sync_status": row["sync_status"],
                    "last_sync_completed_at": row["last_sync_completed_at"],
                    "last_error": row["last_error"],
                }
                for row in rows
            ]
    @staticmethod
    def list_documents(directory_id: str) -> list[dict]:
        """
        Returns all tracked documents in a registered directory, including
        filename, relative/canonical path, extension, status, and passage count.
        """
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 
                    d.document_id,
                    d.directory_id,
                    d.canonical_path,
                    d.filename,
                    d.extension,
                    d.file_type,
                    d.size_bytes,
                    d.modified_time,
                    d.extraction_status,
                    d.last_indexed_at,
                    COUNT(p.chunk_id) AS passage_count
                FROM documents d
                LEFT JOIN passages p ON d.document_id = p.document_id
                WHERE d.directory_id = ?
                GROUP BY d.document_id
                ORDER BY d.filename ASC;
                """,
                (directory_id,),
            )
            rows = cursor.fetchall()
            return [
                {
                    "document_id": row["document_id"],
                    "directory_id": row["directory_id"],
                    "canonical_path": row["canonical_path"],
                    "filename": row["filename"],
                    "extension": row["extension"],
                    "file_type": row["file_type"],
                    "size_bytes": row["size_bytes"],
                    "modified_time": row["modified_time"],
                    "extraction_status": row["extraction_status"],
                    "last_indexed_at": row["last_indexed_at"],
                    "passage_count": row["passage_count"],
                }
                for row in rows
            ]

    @staticmethod
    def delete_directory(directory_id: str) -> bool:
        """
        Unlinks a directory from FindIT: deletes database records
        (cascading to documents and passages) and prunes search indices (FAISS & BM25)
        while source files on disk remain 100% untouched.
        """
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT directory_id FROM directories WHERE directory_id = ?;", (directory_id,))
            if not cursor.fetchone():
                raise DirectoryNotFoundError(f"Directory ID '{directory_id}' not found.")

        from app.sync.worker import get_sync_worker
        get_sync_worker().wait_for_directory(directory_id)
        from app.services.pruning_service import PruningService
        PruningService.prune_directory(directory_id)
        return True

    @classmethod
    def sync_directory(cls, directory_id: str) -> dict:
        """
        Triggers an incremental scan/sync of a single registered directory.
        Executes full scanning, pruning, extraction, chunking, and dual indexing.
        """
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT canonical_path, display_name FROM directories WHERE directory_id = ?;", (directory_id,))
            row = cursor.fetchone()
            if not row:
                raise DirectoryNotFoundError(f"Directory ID '{directory_id}' not found.")

            target_path = Path(row["canonical_path"]).resolve()
            if not target_path.exists():
                cursor.execute(
                    "UPDATE directories SET sync_status = 'ERROR', last_error = 'Directory path missing on disk' WHERE directory_id = ?;",
                    (directory_id,)
                )
                raise ValueError(f"Registered directory missing on disk: '{target_path}'")

        from app.sync.worker import get_sync_worker
        worker = get_sync_worker()
        job_id = worker.start_sync(directory_id, background=False)
        job_info = worker.get_job_status(job_id)

        return {
            "job_id": job_id,
            "directory_id": directory_id,
            "status": "COMPLETED",
            "files_discovered": job_info["files_discovered"] if job_info else 0,
        }

    @staticmethod
    def pick_directory_native() -> str | None:
        """
        Launches the local desktop OS directory picker dialog using Python tkinter.
        Returns the chosen path, or None if dismissed.
        """
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            selected_dir = filedialog.askdirectory(title="Select Folder to Index with FindIT")
            root.destroy()
            if selected_dir:
                return str(Path(selected_dir).resolve()).replace("\\", "/")
            return None
        except Exception as e:
            logger.warning(f"Native folder picker failed or unavailable: {e}")
            return None
