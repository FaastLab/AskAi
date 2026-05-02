"""Chunker Protocol and `Chunk` dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from faastlab_askai_indexing.parsers.base import ParsedDocument


@dataclass(slots=True)
class Chunk:
    """A retrieval-sized slice of a document.

    `char_start` / `char_end` reference the parsed plain-text stream
    (`ParsedDocument.text`). `page_number` and `section_path` carry
    paragraph-level provenance forward into the database for citation.
    """

    text: str
    section_path: str | None = None
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    token_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Chunker(Protocol):
    """ParsedDocument → list[Chunk]."""

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        """Split `doc` into chunks, preserving block-level provenance."""
        ...
