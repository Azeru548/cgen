"""Ephemeral download file store (M4).

Maps cryptographically random tokens to generated STEP/STL file pairs.

Security properties:
  - Tokens are generated with `secrets.token_urlsafe`; they are opaque
    dictionary keys, NEVER interpreted as filesystem paths.
  - `resolve()` returns only paths previously registered by `put()`.
    A request token can therefore never cause arbitrary filesystem access,
    and `../` traversal is impossible by construction.
  - Entries expire after FILE_TTL_SECONDS and the store is capped at
    MAX_ENTRIES (oldest evicted first). Render's disk is ephemeral; files
    only need to live for the generate -> download workflow. No database,
    no object storage in this milestone.

This store is intentionally single-process and in-memory: Render Free runs
one instance, and generated files die with deploys/restarts by design.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_ENTRIES = 200
FILE_TTL_SECONDS = 3600
SUPPORTED_FORMATS = ("step", "stl")


@dataclass
class StoredFiles:
    step_path: str
    stl_path: str
    stem: str
    created: float = field(default_factory=time.monotonic)


class FileStore:
    def __init__(
        self, *, max_entries: int = MAX_ENTRIES, ttl_seconds: float = FILE_TTL_SECONDS
    ) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, StoredFiles] = {}

    def put(self, *, step_path: str, stl_path: str, stem: str) -> str:
        """Register a generated file pair; return its download token."""
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._entries[token] = StoredFiles(
                step_path=step_path, stl_path=stl_path, stem=stem
            )
            self._prune_locked()
        return token

    def resolve(self, token: object, download_format: object) -> Path | None:
        """Return the registered file path for (token, format), or None.

        Returns None for unknown/expired tokens, unsupported formats, and
        files that have vanished from the ephemeral disk. `token` is only
        ever used as a dict key — never joined into a path.
        """
        if not isinstance(token, str) or not token:
            return None
        if download_format not in SUPPORTED_FORMATS:
            return None
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            if time.monotonic() - entry.created > self._ttl_seconds:
                del self._entries[token]
                return None
            raw = entry.step_path if download_format == "step" else entry.stl_path
        path = Path(raw)
        if not path.is_file():
            return None
        return path

    def filename_for(self, token: object, download_format: object) -> str | None:
        """Public download filename (sanitized stem + extension), or None."""
        if not isinstance(token, str) or not token:
            return None
        if download_format not in SUPPORTED_FORMATS:
            return None
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            return f"{entry.stem}.{download_format}"

    def _prune_locked(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, entry in self._entries.items()
            if now - entry.created > self._ttl_seconds
        ]
        for key in expired:
            del self._entries[key]
        while len(self._entries) > self._max_entries:
            oldest = next(iter(self._entries))
            del self._entries[oldest]

    def __len__(self) -> int:  # pragma: no cover - diagnostic helper
        with self._lock:
            return len(self._entries)
