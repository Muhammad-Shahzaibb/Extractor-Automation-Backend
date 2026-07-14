"""In-memory cache for a parsed run until Excel is downloaded (no disk storage)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, status


@dataclass
class CachedRun:
    run_id: str
    user_id: str
    records: list[dict[str, Any]]
    columns: list[str]
    errors: list[tuple[str, str]]
    files_total: int
    files_ok: int
    files_failed: int
    created_at: float = field(default_factory=time.time)


class RunCache:
    """Holds parsed results briefly so the user can pick columns and download Excel."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._runs: dict[str, CachedRun] = {}
        self._lock = threading.Lock()

    def _purge_locked(self) -> None:
        now = time.time()
        expired = [k for k, v in self._runs.items() if now - v.created_at > self._ttl]
        for k in expired:
            del self._runs[k]

    def put(self, run: CachedRun) -> CachedRun:
        with self._lock:
            self._purge_locked()
            self._runs[run.run_id] = run
        return run

    def get(self, run_id: str, user_id: str) -> CachedRun:
        with self._lock:
            self._purge_locked()
            run = self._runs.get(run_id)
        if run is None or run.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Run not found or expired — upload and parse again",
            )
        return run

    def pop(self, run_id: str, user_id: str) -> CachedRun:
        run = self.get(run_id, user_id)
        with self._lock:
            self._runs.pop(run_id, None)
        return run

    def new_id(self) -> str:
        return str(uuid.uuid4())


run_cache = RunCache()
