"""MinIO / S3-compatible storage adapter.

Uses aioboto3 so the same adapter works against MinIO (default OSS dev),
AWS S3, Cloudflare R2, Backblaze B2, etc. Azure Blob has its own SDK
and gets a separate adapter when needed.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, cast

import aioboto3
from botocore.exceptions import ClientError

from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.exceptions import AskAiError

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client


class StorageObjectNotFoundError(AskAiError):
    """Raised when `get` or `delete` is called for a missing key."""


class MinIOStorage:
    """S3-compatible object storage.

    Bucket is created lazily on first write so a fresh `docker compose up`
    doesn't require a separate bootstrap step (the `minio-init` service
    in `docker-compose.yml` also creates it as a belt-and-braces).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session: aioboto3.Session | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session = session or aioboto3.Session()
        self._bucket = self._settings.minio_bucket
        self._endpoint = self._settings.minio_endpoint
        self._region = self._settings.minio_region
        self._access_key = self._settings.minio_root_user
        self._secret_key = self._settings.minio_root_password
        self._bucket_ensured = False

    # ---- Internal ----------------------------------------------------------

    @asynccontextmanager
    async def _client(self) -> AsyncIterator["S3Client"]:
        async with self._session.client(
            "s3",
            endpoint_url=self._endpoint,
            region_name=self._region,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        ) as client:
            yield cast("S3Client", client)

    async def _ensure_bucket(self) -> None:
        if self._bucket_ensured:
            return
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"404", "NoSuchBucket", "NotFound"}:
                    await s3.create_bucket(Bucket=self._bucket)
                else:
                    raise
        self._bucket_ensured = True

    # ---- StorageAdapter protocol ------------------------------------------

    async def get(self, key: str) -> bytes:
        async with self._client() as s3:
            try:
                response = await s3.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"NoSuchKey", "404"}:
                    raise StorageObjectNotFoundError(key) from exc
                raise
            async with response["Body"] as stream:
                return await stream.read()

    async def put(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> None:
        await self._ensure_bucket()
        params: dict[str, object] = {"Bucket": self._bucket, "Key": key, "Body": data}
        if content_type:
            params["ContentType"] = content_type
        async with self._client() as s3:
            await s3.put_object(**params)  # type: ignore[arg-type]

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"404", "NoSuchKey", "NotFound"}:
                    return False
                raise

    async def presigned_url(self, key: str, *, expires_in: int = 3600) -> str:
        async with self._client() as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return cast(str, url)
