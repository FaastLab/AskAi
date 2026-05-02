"""S3 / MinIO connector — list objects under a prefix and yield bytes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from faastlab_askai_indexing.adapters.storage_minio import MinIOStorage
from faastlab_askai_indexing.connectors.base import SourceDocument
from faastlab_askai_indexing.parsers.router import detect_content_type

if TYPE_CHECKING:
    from faastlab_askai_core.config import Settings


class S3Connector:
    """Iterate over objects in an S3-compatible bucket under a prefix."""

    def __init__(
        self,
        prefix: str = "",
        *,
        settings: "Settings | None" = None,
        storage: MinIOStorage | None = None,
        bucket: str | None = None,
    ) -> None:
        self._storage = storage or MinIOStorage(settings)
        self._bucket = bucket or self._storage._bucket  # noqa: SLF001
        self._prefix = prefix

    async def iter_documents(self) -> AsyncIterator[SourceDocument]:
        async with self._storage._client() as s3:  # noqa: SLF001 — internal helper
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=self._prefix):
                for obj in page.get("Contents", []) or []:
                    key = obj.get("Key")
                    if not key or key.endswith("/"):
                        continue
                    response = await s3.get_object(Bucket=self._bucket, Key=key)
                    async with response["Body"] as stream:
                        data = await stream.read()
                    yield SourceDocument(
                        source_uri=f"s3://{self._bucket}/{key}",
                        data=data,
                        filename=key.rsplit("/", 1)[-1],
                        content_type=detect_content_type(key),
                        metadata={"size_bytes": obj.get("Size")},
                    )
