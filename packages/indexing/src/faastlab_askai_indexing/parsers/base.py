"""Parser Protocol and shared dataclasses.

A parser turns raw bytes into a sequence of `ParsedBlock`s — each block
is a paragraph, heading, list item, or table row with its source
metadata (page number, char offsets, section path) preserved for
paragraph-level citations later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

# Re-export the canonical exception so callers don't reach into core.
from faastlab_askai_core.exceptions import ParserError

BlockType = Literal[
    "title",
    "heading",
    "paragraph",
    "list_item",
    "table_row",
    "caption",
    "footer",
    "code",
]


@dataclass(slots=True)
class ParsedBlock:
    """One semantic block extracted from a document."""

    text: str
    block_type: BlockType = "paragraph"
    page_number: int | None = None  # 1-indexed; PDFs only
    section_path: str | None = None  # e.g. "1 / 1.2 / 1.2.3"
    char_start: int | None = None  # offset in the parsed plain-text stream
    char_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDocument:
    """A document after parsing — title + ordered blocks + metadata."""

    title: str | None
    blocks: list[ParsedBlock]
    page_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Flat plain-text stream (used for keyword search and chunking)."""
        return "\n\n".join(b.text for b in self.blocks if b.text.strip())


@runtime_checkable
class Parser(Protocol):
    """Bytes → ParsedDocument."""

    @property
    def supported_content_types(self) -> tuple[str, ...]:
        """Tuple of MIME types this parser handles."""
        ...

    def parse(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        """Parse `data` into a `ParsedDocument`. Synchronous because the
        underlying libraries (PyMuPDF, Unstructured) are CPU-bound."""
        ...


__all__ = ["BlockType", "ParsedBlock", "ParsedDocument", "Parser", "ParserError"]
