"""Content hashing for idempotent ingestion."""

from __future__ import annotations

import hashlib


def content_hash(data: bytes) -> str:
    """SHA-256 hex digest of the document bytes.

    Used to detect when a re-ingestion is a no-op (same content) or an
    update (changed content). The migration stores this in
    `documents.content_hash`.
    """
    return hashlib.sha256(data).hexdigest()
