import tempfile
import time
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.db.database import get_db, init_db

client = TestClient(app)


def wait_for_job(job_id: str, timeout: float = 20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        if response.status_code < 400 and response.json()["status"] in {"COMPLETED", "FAILED"}:
            return response.json()
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish")


def test_register_and_list_directory():
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        # Create sample files
        (dir_path / "notes.txt").write_text("Test notes", encoding="utf-8")
        (dir_path / "guide.md").write_text("# Guide", encoding="utf-8")
        (dir_path / "script.py").write_text("print('hello')", encoding="utf-8")
        (dir_path / "ignored.tmp").write_text("temp", encoding="utf-8")  # Unsupported extension

        # Register directory
        response = client.post("/api/directories", json={"canonical_path": str(dir_path)})
        assert response.status_code == 201
        data = response.json()
        assert "directory" in data
        assert "initial_job_id" in data
        directory = data["directory"]
        assert directory["file_count"] == 0
        dir_id = directory["directory_id"]
        job = wait_for_job(data["initial_job_id"])
        assert job["status"] == "COMPLETED"

        # List directories
        list_resp = client.get("/api/directories")
        assert list_resp.status_code == 200
        dirs = list_resp.json()["directories"]
        matched = [d for d in dirs if d["directory_id"] == dir_id]
        assert len(matched) == 1
        assert matched[0]["file_count"] == 3

        # List documents in directory
        docs_resp = client.get(f"/api/directories/{dir_id}/documents")
        assert docs_resp.status_code == 200
        docs_data = docs_resp.json()
        assert docs_data["directory_id"] == dir_id
        assert len(docs_data["documents"]) == 3
        filenames = {d["filename"] for d in docs_data["documents"]}
        assert "notes.txt" in filenames
        assert "guide.md" in filenames
        assert "script.py" in filenames

        # Clean up
        del_resp = client.delete(f"/api/directories/{dir_id}")
        assert del_resp.status_code == 200


def test_invalid_directory():
    # Non-existent path
    response = client.post("/api/directories", json={"canonical_path": "Z:/NonExistentPath/123456"})
    assert response.status_code == 400


def test_overlapping_directories():
    with tempfile.TemporaryDirectory() as temp_dir:
        parent_path = Path(temp_dir)
        child_path = parent_path / "subfolder"
        child_path.mkdir(parents=True, exist_ok=True)
        (child_path / "test.txt").write_text("hello", encoding="utf-8")

        # Register parent
        resp1 = client.post("/api/directories", json={"canonical_path": str(parent_path)})
        assert resp1.status_code == 201
        dir_id = resp1.json()["directory"]["directory_id"]

        try:
            wait_for_job(resp1.json()["initial_job_id"])
            # Attempt to register child (should conflict)
            resp2 = client.post("/api/directories", json={"canonical_path": str(child_path)})
            assert resp2.status_code == 409

            # Attempt to register parent again (exact conflict)
            resp3 = client.post("/api/directories", json={"canonical_path": str(parent_path)})
            assert resp3.status_code == 409
        finally:
            client.delete(f"/api/directories/{dir_id}")


def test_delete_directory_leaves_files_intact():
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        test_file = dir_path / "document.txt"
        test_file.write_text("Physical document content", encoding="utf-8")

        # Register
        resp = client.post("/api/directories", json={"canonical_path": str(dir_path)})
        assert resp.status_code == 201
        dir_id = resp.json()["directory"]["directory_id"]
        wait_for_job(resp.json()["initial_job_id"])

        # Delete directory registration
        del_resp = client.delete(f"/api/directories/{dir_id}")
        assert del_resp.status_code == 200

        # Verify disk file is 100% intact
        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == "Physical document content"

        # Verify database record is gone
        list_resp = client.get("/api/directories")
        dir_ids = [d["directory_id"] for d in list_resp.json()["directories"]]
        assert dir_id not in dir_ids


def test_directory_sync():
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        (dir_path / "file1.txt").write_text("First file", encoding="utf-8")

        # Register
        resp = client.post("/api/directories", json={"canonical_path": str(dir_path)})
        assert resp.status_code == 201
        dir_id = resp.json()["directory"]["directory_id"]
        wait_for_job(resp.json()["initial_job_id"])
        assert resp.json()["directory"]["file_count"] == 0

        try:
            # Add second file
            (dir_path / "file2.md").write_text("# Second file", encoding="utf-8")

            # Trigger sync
            sync_resp = client.post(f"/api/sync/{dir_id}")
            assert sync_resp.status_code == 202
            assert wait_for_job(sync_resp.json()["job_id"])["files_discovered"] == 2

            # Check directory list
            list_resp = client.get("/api/directories")
            matched = [d for d in list_resp.json()["directories"] if d["directory_id"] == dir_id][0]
            assert matched["file_count"] == 2
        finally:
            client.delete(f"/api/directories/{dir_id}")


def test_root_drive_rejection():
    # Attempt to register root system drive
    response = client.post("/api/directories", json={"canonical_path": "C:\\"})
    assert response.status_code == 400
    assert "prohibited" in response.json()["detail"]["error"]["message"].lower()


def test_delete_and_sync_nonexistent_directory():
    del_resp = client.delete("/api/directories/dir_nonexistent123")
    assert del_resp.status_code == 404
    assert del_resp.json()["detail"]["error"]["code"] == "DIRECTORY_NOT_FOUND"

    sync_resp = client.post("/api/sync/dir_nonexistent123")
    assert sync_resp.status_code == 404
    assert sync_resp.json()["detail"]["error"]["code"] == "DIRECTORY_NOT_FOUND"


def test_sync_all_directories():
    with tempfile.TemporaryDirectory() as temp_dir1, tempfile.TemporaryDirectory() as temp_dir2:
        (Path(temp_dir1) / "doc1.txt").write_text("Doc 1", encoding="utf-8")
        (Path(temp_dir2) / "doc2.md").write_text("# Doc 2", encoding="utf-8")

        r1 = client.post("/api/directories", json={"canonical_path": temp_dir1})
        r2 = client.post("/api/directories", json={"canonical_path": temp_dir2})
        assert r1.status_code == 201
        assert r2.status_code == 201
        id1 = r1.json()["directory"]["directory_id"]
        id2 = r2.json()["directory"]["directory_id"]

        try:
            sync_all_resp = client.post("/api/sync")
            assert sync_all_resp.status_code == 202
            data = sync_all_resp.json()
            assert data["status"] == "QUEUED"
            assert len(data["jobs"]) >= 2
        finally:
            client.delete(f"/api/directories/{id1}")
            client.delete(f"/api/directories/{id2}")


def test_pick_directory_endpoint():
    from unittest.mock import patch
    with patch("app.services.directory_service.DirectoryService.pick_directory_native", return_value="C:/Mock/Path"):
        resp = client.post("/api/directories/pick")
        assert resp.status_code == 200
        assert resp.json()["selected"] is True
        assert resp.json()["path"] == "C:/Mock/Path"

    with patch("app.services.directory_service.DirectoryService.pick_directory_native", return_value=None):
        resp = client.post("/api/directories/pick")
        assert resp.status_code == 200
        assert resp.json()["selected"] is False
        assert resp.json()["path"] is None


