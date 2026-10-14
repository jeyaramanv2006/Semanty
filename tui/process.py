"""Lifecycle ownership for a backend process started by the TUI."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import httpx

from .api import APIClient, APIError


class BackendProcess:
    def __init__(self, client: APIClient | None = None, project_root: Path | None = None) -> None:
        self.client = client or APIClient()
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def owns_process(self) -> bool:
        return self.process is not None

    async def ensure_ready(self, timeout: float = 20.0) -> dict:
        try:
            return await self.client.health()
        except APIError:
            pass

        backend_dir = self.project_root / "backend"
        python_path = backend_dir / ".venv" / "Scripts" / "python.exe"
        python = str(python_path if python_path.exists() else Path(sys.executable))
        env = os.environ.copy()
        env.setdefault("FINDIT_RELOAD", "0")
        self.process = subprocess.Popen(
            [python, "run.py"],
            cwd=backend_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = asyncio.get_running_loop().time() + timeout
        last_error = "Backend did not become ready"
        while asyncio.get_running_loop().time() < deadline:
            try:
                return await self.client.health()
            except (APIError, httpx.HTTPError) as exc:
                last_error = str(exc)
                await asyncio.sleep(0.25)
        self.stop()
        raise APIError(last_error)

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
