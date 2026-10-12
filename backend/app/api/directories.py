from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.services.directory_service import (
    DirectoryService,
    DirectoryConflictError,
    DirectoryNotFoundError,
)

router = APIRouter(prefix="/directories", tags=["Directories"])


class RegisterDirectoryRequest(BaseModel):
    canonical_path: str


@router.get("")
def list_directories():
    """
    Returns all registered user-approved directory roots with document and passage counts.
    """
    dirs = DirectoryService.list_directories()
    return {"directories": dirs}


@router.post("", status_code=status.HTTP_201_CREATED)
def register_directory(req: RegisterDirectoryRequest):
    """
    Registers a new local directory, performs validation, and executes an initial file scan.
    """
    try:
        result = DirectoryService.register_directory(req.canonical_path)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_DIRECTORY_PATH",
                    "message": str(e),
                }
            },
        )
    except DirectoryConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "DIRECTORY_CONFLICT",
                    "message": str(e),
                }
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "REGISTRATION_FAILED",
                    "message": f"Failed to register directory: {e}",
                }
            },
        )


@router.delete("/{directory_id}")
def delete_directory(directory_id: str):
    """
    Unlinks a directory from FindIT: deletes internal index and database records.
    Source files on disk remain completely untouched.
    """
    try:
        DirectoryService.delete_directory(directory_id)
        return {
            "success": True,
            "directory_id": directory_id,
            "message": "Directory registration and search indices removed. Original files remain untouched.",
        }
    except DirectoryNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "DIRECTORY_NOT_FOUND",
                    "message": str(e),
                    "details": {"directory_id": directory_id},
                }
            },
        )


@router.get("/{directory_id}/documents")
def list_directory_documents(directory_id: str):
    """
    Returns the list of all tracked documents inside a registered directory,
    including filename, status, and passage counts.
    """
    docs = DirectoryService.list_documents(directory_id)
    return {"directory_id": directory_id, "documents": docs}


@router.post("/pick")
def pick_native_directory():
    """
    Launches the host OS native folder picker dialog and returns the selected path.
    """
    chosen_path = DirectoryService.pick_directory_native()
    return {
        "path": chosen_path,
        "selected": chosen_path is not None,
    }
