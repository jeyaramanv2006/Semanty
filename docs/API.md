# REST API Contract Specification — FindIT

> **Document Status**: `APPROVED` | **Version**: 1.0  
> **Host**: `http://127.0.0.1:8000` (Strict Loopback Binding)  
> **Content-Type**: `application/json`  

---

## 1. General API Conventions

### 1.1 Network & Security Binding
- The API listens exclusively on `127.0.0.1` (IPv4 loopback) or `[::1]` (IPv6 loopback).
- Cross-Origin Resource Sharing (CORS) is restricted to the local Vite development server (`http://localhost:5173`) and local desktop clients.
- State-changing operations require standard origin validation to prevent cross-site request abuse from external browser tabs.

### 1.2 Error Response Format
All 4xx and 5xx responses return a consistent error envelope:
```json
{
  "error": {
    "code": "DIRECTORY_NOT_FOUND",
    "message": "The specified directory ID does not exist in registered roots.",
    "details": {
      "directory_id": "dir_9f83a2"
    }
  }
}
```

---

## 2. Directory Management Endpoints

Directory registration and synchronization are asynchronous. `POST /api/directories` records the approved root and queues an initial indexing job; clients must use the job endpoints for progress rather than waiting for extraction or embedding in the request.

### 2.1 List Registered Directories
- **Endpoint**: `GET /api/directories`
- **Description**: Returns all user-approved directories registered with FindIT.
- **Response**: `200 OK`
```json
{
  "directories": [
    {
      "directory_id": "dir_a1b2c3",
      "canonical_path": "C:/Users/User/Documents/Projects",
      "display_name": "Projects",
      "file_count": 42,
      "passage_count": 318,
      "sync_status": "IDLE",
      "last_sync_completed_at": "2026-10-10T14:32:00Z",
      "last_error": null
    }
  ]
}
```

### 2.2 Register a Directory
- **Endpoint**: `POST /api/directories`
- **Description**: Registers a newly selected local directory root and automatically queues an initial indexing job.
- **Request Body**:
```json
{
  "canonical_path": "C:/Users/User/Documents/Specifications"
}
```
- **Response**: `201 Created`
```json
{
  "directory": {
    "directory_id": "dir_e4f5a6",
    "canonical_path": "C:/Users/User/Documents/Specifications",
    "display_name": "Specifications",
    "file_count": 0,
    "sync_status": "SYNCING",
    "added_at": "2026-10-11T00:15:00Z"
  },
  "initial_job_id": "job_987654"
}
```
- **Errors**:
  - `400 Bad Request`: Path does not exist or is not a directory.
  - `409 Conflict`: Path is already registered or is an overlapping child/parent of an existing registered directory.

### 2.3 Remove a Directory (Index-Only)
- **Endpoint**: `DELETE /api/directories/{directory_id}`
- **Description**: Purges the directory registration and its associated documents, passages, vectors, and BM25 postings from FindIT. **Original files on disk are completely untouched.**
- **Response**: `200 OK`
```json
{
  "success": true,
  "directory_id": "dir_e4f5a6",
  "message": "Directory registration and search indices removed. Original files remain untouched."
}
```

### 2.4 List Tracked Documents in a Directory
- **Endpoint**: `GET /api/directories/{directory_id}/documents`
- **Description**: Returns all tracked files within a registered folder, including filename, size, extraction status, and passage counts.
- **Response**: `200 OK`
```json
{
  "directory_id": "dir_e4f5a6",
  "documents": [
    {
      "document_id": "doc_123456",
      "directory_id": "dir_e4f5a6",
      "canonical_path": "C:/Users/name/Documents/lecture.pdf",
      "filename": "lecture.pdf",
      "extension": ".pdf",
      "file_type": "pdf",
      "size_bytes": 1048576,
      "modified_time": 1728000000,
      "extraction_status": "OK",
      "last_indexed_at": "2026-10-11T12:00:00Z",
      "passage_count": 42
    }
  ]
}
```

### 2.5 Trigger Directory Sync
- **Endpoint**: `POST /api/sync/{directory_id}`
- **Description**: Starts an incremental synchronization job for a single registered directory.
- **Response**: `202 Accepted`
```json
{
  "job_id": "job_112233",
  "directory_id": "dir_a1b2c3",
  "status": "QUEUED"
}
```

### 2.6 Trigger Sync All
- **Endpoint**: `POST /api/sync`
- **Description**: Enqueues incremental synchronization jobs across all registered directories.
- **Response**: `202 Accepted`
```json
{
  "jobs": [
    {
      "job_id": "job_112234",
      "directory_id": "dir_a1b2c3",
      "status": "QUEUED"
    }
  ]
}
```

The supported sync routes are the asynchronous `/api/sync` and `/api/sync/{directory_id}` endpoints. Synchronous directory sync routes are not part of the public contract.

---

## 3. Asynchronous Job Monitoring

### 3.1 Get Index Job Status
- **Endpoint**: `GET /api/jobs/{job_id}`
- **Description**: Returns live progress, stage, and file counts for an active or completed indexing/sync job.
- **Response**: `200 OK`
```json
{
  "job_id": "job_112233",
  "directory_id": "dir_a1b2c3",
  "job_type": "SYNC_DIRECTORY",
  "status": "RUNNING",
  "stage": "EMBEDDING",
  "files_discovered": 45,
  "files_processed": 32,
  "files_failed": 1,
  "passages_created": 210,
  "started_at": "2026-10-11T00:20:10Z",
  "updated_at": "2026-10-11T00:20:25Z",
  "completed_at": null,
  "warnings": [
    {
      "file": "Corrupt_Diagram.pdf",
      "reason": "Scanned document without embedded text layer."
    }
  ]
}
```

---

## 4. Search & Passage Retrieval Endpoints

### 4.1 Hybrid Search
- **Endpoint**: `POST /api/search`
- **Description**: Executes hybrid retrieval (FAISS semantic + BM25 lexical) combined via Reciprocal Rank Fusion ($k=60$).
- **User-facing ranking policy**: The standard client contract always returns the backend's unified hybrid RRF ordering. Semantic and lexical ranks may be retained as developer diagnostics only; clients must not re-sort the returned list.
- **Request Body**:
```json
{
  "query": "vector indexing and authentication architecture",
  "limit": 10,
  "offset": 0,
  "include_diagnostics": false
}
```
- **Response**: `200 OK`
```json
{
  "query": "vector indexing and authentication architecture",
  "total_available": 18,
  "results": [
    {
      "chunk_id": "chunk_7b8a9c_04",
      "document_id": "doc_7b8a9c",
      "filename": "FindIT_Architecture_Spec.docx",
      "canonical_path": "C:/Users/User/Documents/Projects/FindIT_Architecture_Spec.docx",
      "display_path": "~/Documents/Projects",
      "file_type": "docx",
      "location_label": "Section: Storage Architecture & Indexing",
      "passage_preview": "The system utilizes FAISS for vector indexing and enforces SQLite persistence for metadata. Authentication architecture relies on local-first loopback binding...",
      "hybrid_rank": 1,
      "rrf_score": 0.03278
    }
  ],
  "next_offset": 10
}
```

### 4.2 Fetch Full Passage
- **Endpoint**: `GET /api/passages/{chunk_id}`
- **Description**: Retrieves complete, unvarnished passage text and precise location metadata for the Passage Inspector modal.
- **Response**: `200 OK`
```json
{
  "chunk_id": "chunk_7b8a9c_04",
  "document_id": "doc_7b8a9c",
  "filename": "FindIT_Architecture_Spec.docx",
  "display_path": "~/Documents/Projects",
  "file_type": "docx",
  "location_label": "Section: Storage Architecture & Indexing",
  "text": "The system utilizes FAISS for vector indexing and enforces SQLite persistence for metadata. Authentication architecture relies on local-first loopback binding rather than complex multi-user credential schemes...",
  "page_number": null,
  "slide_number": null,
  "start_line": null,
  "end_line": null,
  "section_heading": "Storage Architecture & Indexing"
}
```

---

## 5. Local OS Filesystem Integration

### 5.1 Open Containing Folder
- **Endpoint**: `POST /api/documents/{document_id}/open-folder`
- **Description**: Validates that the requested document belongs to an approved registered root and commands the native operating system file manager to open its directory (and select/highlight the file if supported).
- **Response**: `200 OK`
```json
{
  "success": true,
  "message": "Opened containing folder in native explorer.",
  "path": "C:/Users/User/Documents/Projects/FindIT_Architecture_Spec.docx"
}
```
- **Errors**:
  - `404 Not Found`: Document ID does not exist in SQLite database.
  - `403 Forbidden`: File path fails directory-boundary security checks.

### 5.2 Open Document
- **Endpoint**: `POST /api/documents/{document_id}/open`
- **Description**: Commands the OS to launch the document in its default associated application (e.g., Adobe Acrobat, VS Code, Word).
- **Response**: `200 OK`
```json
{
  "success": true,
  "message": "Launched file in default application."
}
```

---

## 6. System Health

### 6.1 Health & Environment
- **Endpoint**: `GET /api/health`
- **Response**: `200 OK`
```json
{
  "status": "OK",
  "version": "0.1.0",
  "model_loaded": true,
  "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
  "registered_directories": 2,
  "total_passages_indexed": 1420
}
```
