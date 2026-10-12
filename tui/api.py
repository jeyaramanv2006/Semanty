"""Small async REST client used by the Textual interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class APIError(RuntimeError):
    """An actionable error returned by the local FindIT API."""


@dataclass(frozen=True)
class APIClient:
    base_url: str = "http://127.0.0.1:8000/api"

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise APIError(f"Backend unavailable: {exc}") from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
                error = payload.get("error", payload.get("detail", payload))
                message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            except ValueError:
                message = response.text or f"HTTP {response.status_code}"
            raise APIError(message)
        return response.json()

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def search(self, query: str, limit: int = 10, offset: int = 0) -> dict[str, Any]:
        return await self._request(
            "POST", "/search", json={"query": query, "limit": limit, "offset": offset}
        )

    async def passage(self, chunk_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/passages/{chunk_id}")

    async def directories(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/directories")).get("directories", [])

    async def pick_directory(self) -> str | None:
        return (await self._request("POST", "/directories/pick")).get("path")

    async def register_directory(self, path: str) -> dict[str, Any]:
        return await self._request("POST", "/directories", json={"canonical_path": path})

    async def remove_directory(self, directory_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/directories/{directory_id}")

    async def sync_directory(self, directory_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/sync/{directory_id}")

    async def sync_all(self) -> dict[str, Any]:
        return await self._request("POST", "/sync")

    async def job(self, job_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/jobs/{job_id}")

    async def open_folder(self, document_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/documents/{document_id}/open-folder")

    async def open_document(self, document_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/documents/{document_id}/open")
