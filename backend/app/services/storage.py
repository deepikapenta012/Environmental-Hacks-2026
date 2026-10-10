"""Secure file-storage abstraction for evidence documents.

The local backend stores files under a configurable root directory with
server-generated filenames. A future cloud implementation can satisfy the
same protocol without changing callers.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.config import get_settings


class StorageBackend(Protocol):
    """Minimal protocol a storage implementation must satisfy."""

    def save(self, claim_id: str, suffix: str, content: bytes) -> str:
        """Persist *content* and return a stable storage key."""
        ...

    def load(self, storage_key: str) -> bytes:
        """Return the raw bytes for *storage_key*, or raise ``FileNotFoundError``."""
        ...

    def exists(self, storage_key: str) -> bool:
        """Return whether *storage_key* resolves to an existing file."""
        ...

    def delete(self, storage_key: str) -> None:
        """Remove an uncommitted object after its metadata transaction fails."""
        ...

    def resolve_path(self, storage_key: str) -> Path:
        """Return an absolute filesystem path that can be served.

        Raises ``FileNotFoundError`` if the key does not map to a real file.
        """
        ...


class LocalStorageBackend:
    """Store evidence files on the local filesystem.

    Files are organised as ``<root>/<claim_id>/<uuid><suffix>`` and are
    never named after user input.  Read operations validate that the
    resolved path stays inside the configured root to prevent traversal.
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            root = Path(get_settings().evidence_storage_root).resolve()
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    # ── write ────────────────────────────────────────────────────────────

    def save(self, claim_id: str, suffix: str, content: bytes) -> str:
        safe_claim_id = _sanitise_segment(claim_id)
        safe_suffix = _sanitise_suffix(suffix)
        stored_name = f"{uuid.uuid4().hex}{safe_suffix}"
        key = f"{safe_claim_id}/{stored_name}"
        destination = (self._root / key).resolve()
        if not destination.is_relative_to(self._root):
            raise PermissionError("Storage key escapes root")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stored_file:
            stored_file.write(content)
        return key

    # ── read ─────────────────────────────────────────────────────────────

    def load(self, storage_key: str) -> bytes:
        path = self.resolve_path(storage_key)
        return path.read_bytes()

    def exists(self, storage_key: str) -> bool:
        try:
            self.resolve_path(storage_key)
            return True
        except FileNotFoundError:
            return False

    def delete(self, storage_key: str) -> None:
        try:
            self.resolve_path(storage_key).unlink()
        except FileNotFoundError:
            return

    def resolve_path(self, storage_key: str) -> Path:
        safe_key = PurePosixPath(storage_key)
        # Reject any relative escape sequences
        for part in safe_key.parts:
            if part in {".", ".."} or "/" in part or "\\" in part:
                raise FileNotFoundError("Invalid storage key")
        path = (self._root / str(safe_key)).resolve()
        if not path.is_relative_to(self._root):
            raise FileNotFoundError("Storage key escapes root")
        if not path.is_file():
            raise FileNotFoundError(f"Evidence file not found: {storage_key}")
        return path


# ── helpers ──────────────────────────────────────────────────────────────


def _sanitise_segment(value: str) -> str:
    """Keep only safe filename characters."""
    return "".join(c for c in value if c.isalnum() or c in "-_")


def _sanitise_suffix(suffix: str) -> str:
    """Ensure the suffix starts with a dot and has no path separators."""
    suffix = suffix.strip()
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return "".join(c for c in suffix if c.isalnum() or c == ".")


# ── singleton ────────────────────────────────────────────────────────────

_backend: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    global _backend
    if _backend is None:
        _backend = LocalStorageBackend()
    return _backend


def set_storage_backend(backend: StorageBackend) -> None:
    """Replace the active backend — useful for tests."""
    global _backend
    _backend = backend
