"""Sync + async clients."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from httpx_sse import EventSource, aconnect_sse, connect_sse
from pydantic import TypeAdapter

from faastlab_askai_sdk.models import (
    AskResult,
    DocumentRecord,
    SearchHit,
    SearchResult,
)

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=5.0, read=120.0)


def _auth_headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


# =============================================================================
# Sync client
# =============================================================================


class AskAiClient:
    """Synchronous AskAi client.

    Powered by an internal `httpx.Client`; close via `client.close()` or
    use it as a context manager (`with AskAiClient(...) as c: …`).
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers=_auth_headers(api_key),
            timeout=timeout,
        )

    def __enter__(self) -> "AskAiClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # ---- Reads ---------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        k: int = 8,
        filters: dict[str, Any] | None = None,
        rerank: bool = True,
    ) -> SearchResult:
        body = {"query": query, "k": k, "filters": filters or {}, "rerank": rerank}
        r = self._http.post("/v1/search", json=body)
        r.raise_for_status()
        return SearchResult.model_validate(r.json())

    def list_documents(
        self, *, only_active: bool = True, limit: int = 50, offset: int = 0
    ) -> list[DocumentRecord]:
        r = self._http.get(
            "/v1/documents",
            params={"only_active": only_active, "limit": limit, "offset": offset},
        )
        r.raise_for_status()
        return TypeAdapter(list[DocumentRecord]).validate_python(r.json())

    def get_document(self, document_id: UUID | str) -> DocumentRecord:
        r = self._http.get(f"/v1/documents/{document_id}")
        r.raise_for_status()
        return DocumentRecord.model_validate(r.json())

    # ---- Ask -----------------------------------------------------------

    def ask(
        self,
        question: str,
        *,
        session_id: UUID | str | None = None,
        include_superseded: bool = False,
    ) -> AskResult:
        body = {
            "query": question,
            "session_id": str(session_id) if session_id else None,
            "filters": {"include_superseded": include_superseded},
            "stream": False,
        }
        r = self._http.post("/v1/ask", json=body)
        r.raise_for_status()
        return AskResult.model_validate(r.json())

    def stream_ask(
        self,
        question: str,
        *,
        session_id: UUID | str | None = None,
        include_superseded: bool = False,
    ) -> Iterator[dict[str, Any]]:
        body = {
            "query": question,
            "session_id": str(session_id) if session_id else None,
            "filters": {"include_superseded": include_superseded},
            "stream": True,
        }
        with connect_sse(
            self._http, "POST", "/v1/ask", json=body
        ) as event_source:  # type: EventSource
            for event in event_source.iter_sse():
                yield json.loads(event.data)

    # ---- Ingest --------------------------------------------------------

    def upload(self, path: str | Path, *, title: str | None = None) -> dict[str, Any]:
        p = Path(path)
        with p.open("rb") as fh:
            files = {"file": (p.name, fh)}
            data = {"title": title} if title else None
            r = self._http.post("/v1/ingest/upload", files=files, data=data)
        r.raise_for_status()
        return r.json()


# =============================================================================
# Async client
# =============================================================================


class AsyncAskAiClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers=_auth_headers(api_key),
            timeout=timeout,
        )

    async def __aenter__(self) -> "AsyncAskAiClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def search(
        self,
        query: str,
        *,
        k: int = 8,
        filters: dict[str, Any] | None = None,
        rerank: bool = True,
    ) -> SearchResult:
        body = {"query": query, "k": k, "filters": filters or {}, "rerank": rerank}
        r = await self._http.post("/v1/search", json=body)
        r.raise_for_status()
        return SearchResult.model_validate(r.json())

    async def ask(
        self,
        question: str,
        *,
        session_id: UUID | str | None = None,
        include_superseded: bool = False,
    ) -> AskResult:
        body = {
            "query": question,
            "session_id": str(session_id) if session_id else None,
            "filters": {"include_superseded": include_superseded},
            "stream": False,
        }
        r = await self._http.post("/v1/ask", json=body)
        r.raise_for_status()
        return AskResult.model_validate(r.json())

    async def stream_ask(
        self,
        question: str,
        *,
        session_id: UUID | str | None = None,
        include_superseded: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        body = {
            "query": question,
            "session_id": str(session_id) if session_id else None,
            "filters": {"include_superseded": include_superseded},
            "stream": True,
        }
        async with aconnect_sse(
            self._http, "POST", "/v1/ask", json=body
        ) as event_source:
            async for event in event_source.aiter_sse():
                yield json.loads(event.data)

    async def list_documents(
        self, *, only_active: bool = True, limit: int = 50, offset: int = 0
    ) -> list[DocumentRecord]:
        r = await self._http.get(
            "/v1/documents",
            params={"only_active": only_active, "limit": limit, "offset": offset},
        )
        r.raise_for_status()
        return TypeAdapter(list[DocumentRecord]).validate_python(r.json())

    async def get_document(self, document_id: UUID | str) -> DocumentRecord:
        r = await self._http.get(f"/v1/documents/{document_id}")
        r.raise_for_status()
        return DocumentRecord.model_validate(r.json())

    async def upload(
        self, path: str | Path, *, title: str | None = None
    ) -> dict[str, Any]:
        p = Path(path)
        with p.open("rb") as fh:
            files = {"file": (p.name, fh)}
            data = {"title": title} if title else None
            r = await self._http.post("/v1/ingest/upload", files=files, data=data)
        r.raise_for_status()
        return r.json()
