"""Connector Protocol and `SourceDocument` dataclass."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class SourceDocument:
    """Raw bytes plus the metadata needed to identify and parse them."""

    source_uri: str  # canonical URI: file:///, s3://, https://, ...
    data: bytes
    filename: str | None = None
    content_type: str | None = None
    # Human-readable document title. When set, the pipeline uses this in
    # preference to `filename` for `documents.title`. Used by the watcher
    # to keep regulator RSS titles ("Consultation paper CP1/26") instead
    # of the URL-derived placeholder filename.
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Connector(Protocol):
    """Iterator of `SourceDocument`s from some upstream system."""

    async def iter_documents(self) -> AsyncIterator[SourceDocument]:
        """Yield documents to ingest. Implementations may be lazy."""
        ...
