"""Storage adapter — object storage (MinIO, S3, Azure Blob)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageAdapter(Protocol):
    """Object-storage backend.

    All operations are tenant-scoped by the caller via the `key` (which
    should embed the tenant slug, e.g. `tenants/{slug}/docs/{doc_id}`).
    """

    async def get(self, key: str) -> bytes:
        """Return the bytes for `key`. Raises if the object does not exist."""
        ...

    async def put(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> None:
        """Write `data` at `key`, replacing any existing object."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the object at `key`. No-op if it does not exist."""
        ...

    async def exists(self, key: str) -> bool:
        """Return True if an object exists at `key`."""
        ...

    async def presigned_url(self, key: str, *, expires_in: int = 3600) -> str:
        """Return a time-limited URL the caller can use to fetch the object."""
        ...
