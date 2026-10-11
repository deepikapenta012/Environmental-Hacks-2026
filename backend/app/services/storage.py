"""Secure file-storage abstraction for evidence documents.

The local backend stores files under a configurable root directory with
server-generated filenames. Deployments can select the S3 implementation
without changing evidence API callers.
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


class S3StorageBackend:
    """Evidence object storage using the AWS SDK's default credential chain."""

    def __init__(self, bucket: str, *, region: str, prefix: str = "", kms_key_id: str = "", client=None):
        if not bucket.strip():
            raise ValueError("EVIDENCE_S3_BUCKET is required when S3 storage is enabled")
        self._bucket = bucket.strip()
        self._prefix = _sanitise_prefix(prefix)
        self._kms_key_id = kms_key_id.strip()
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("Install backend requirements to use AWS S3 evidence storage") from exc
            client = boto3.client("s3", region_name=region)
        self._client = client

    def save(self, claim_id: str, suffix: str, content: bytes) -> str:
        safe_claim_id = _sanitise_segment(claim_id)
        safe_suffix = _sanitise_suffix(suffix)
        key_parts = [part for part in (self._prefix, safe_claim_id, f"{uuid.uuid4().hex}{safe_suffix}") if part]
        key = "/".join(key_parts)
        extension = safe_suffix.lower()
        content_type = {
            ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
        }.get(extension, "application/octet-stream")
        request = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": content,
            "ContentType": content_type,
            "ServerSideEncryption": "aws:kms" if self._kms_key_id else "AES256",
        }
        if self._kms_key_id:
            request["SSEKMSKeyId"] = self._kms_key_id
        self._client.put_object(**request)
        return key

    def load(self, storage_key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=_validate_object_key(storage_key))
        except Exception as exc:
            if _is_missing_s3_object(exc):
                raise FileNotFoundError("Evidence object not found") from exc
            raise
        body = response["Body"]
        try:
            return body.read()
        finally:
            close = getattr(body, "close", None)
            if close:
                close()

    def exists(self, storage_key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=_validate_object_key(storage_key))
            return True
        except Exception as exc:
            if _is_missing_s3_object(exc):
                return False
            raise

    def delete(self, storage_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=_validate_object_key(storage_key))


def _sanitise_prefix(prefix: str) -> str:
    prefix = prefix.strip().strip("/")
    if not prefix:
        return ""
    parts = prefix.split("/")
    if any(part in {"", ".", ".."} or "\\" in part for part in parts):
        raise ValueError("EVIDENCE_S3_PREFIX must be a safe relative object prefix")
    return "/".join(parts)


def _validate_object_key(key: str) -> str:
    parts = key.split("/")
    if not key or key.startswith("/") or any(part in {"", ".", ".."} or "\\" in part for part in parts):
        raise FileNotFoundError("Invalid evidence object key")
    return key


def _is_missing_s3_object(error: Exception) -> bool:
    response = getattr(error, "response", {})
    code = str((response.get("Error") or {}).get("Code", ""))
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


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
        settings = get_settings()
        backend = settings.evidence_storage_backend.strip().lower()
        if backend == "local":
            _backend = LocalStorageBackend()
        elif backend == "s3":
            _backend = S3StorageBackend(
                settings.evidence_s3_bucket,
                region=settings.aws_region,
                prefix=settings.evidence_s3_prefix,
                kms_key_id=settings.evidence_s3_kms_key_id,
            )
        else:
            raise ValueError("EVIDENCE_STORAGE_BACKEND must be 'local' or 's3'")
    return _backend


def set_storage_backend(backend: StorageBackend) -> None:
    """Replace the active backend — useful for tests."""
    global _backend
    _backend = backend


def reset_storage_backend() -> None:
    """Clear the selected backend so configuration can be reloaded."""
    global _backend
    _backend = None
