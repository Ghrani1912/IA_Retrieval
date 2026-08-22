"""Filesystem-based object cache for raw IA source files.

Replaces MinIO (archived April 2026, no further security patches).
Files are stored as: {OBJECT_CACHE_DIR}/{ia_identifier}/{filename}

To migrate to S3/R2/Backblaze later: replace read() and write() with
boto3/aioboto3 calls — the interface is identical.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def _item_dir(ia_identifier: str) -> Path:
    """Return the cache directory for a given identifier, creating it if needed."""
    path = Path(settings.object_cache_dir) / ia_identifier
    path.mkdir(parents=True, exist_ok=True)
    return path


def exists(ia_identifier: str, filename: str = "raw.txt") -> bool:
    """Return True if the cached file exists for this identifier."""
    return (_item_dir(ia_identifier) / filename).exists()


def read(ia_identifier: str, filename: str = "raw.txt") -> str | None:
    """Read cached content for an identifier.

    Returns:
        File contents as a string, or None if not cached.
    """
    path = _item_dir(ia_identifier) / filename
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Object cache read failed for %s/%s: %s", ia_identifier, filename, exc)
        return None


def write(ia_identifier: str, content: str, filename: str = "raw.txt") -> bool:
    """Write content to the cache for an identifier.

    Returns:
        True on success, False if the write failed (caller continues with in-memory content).
    """
    path = _item_dir(ia_identifier) / filename
    try:
        path.write_text(content, encoding="utf-8")
        logger.debug("Object cache written: %s/%s (%d bytes)", ia_identifier, filename, len(content))
        return True
    except OSError as exc:
        logger.warning(
            "Object cache write failed for %s/%s: %s — continuing with in-memory content",
            ia_identifier,
            filename,
            exc,
        )
        return False


def cache_dir() -> Path:
    """Return the root cache directory path."""
    return Path(settings.object_cache_dir)
