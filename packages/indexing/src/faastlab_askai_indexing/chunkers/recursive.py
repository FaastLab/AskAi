"""Recursive token-aware chunker.

Wraps LangChain's `RecursiveCharacterTextSplitter` with tiktoken-based
token counting so chunk sizes match `Settings.chunk_size_tokens`.
Preserves the strongest available `page_number` / `section_path` from
the source blocks each chunk overlaps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from faastlab_askai_core.config import Settings, get_settings

from faastlab_askai_indexing.chunkers.base import Chunk
from faastlab_askai_indexing.parsers.base import ParsedBlock, ParsedDocument

if TYPE_CHECKING:
    from collections.abc import Iterable


class RecursiveChunker:
    """Token-aware recursive splitter for arbitrary text."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        chunk_size_tokens: int | None = None,
        chunk_overlap_tokens: int | None = None,
        encoding_name: str = "cl100k_base",  # GPT-4 / OpenAI v3 embeddings
    ) -> None:
        self._settings = settings or get_settings()
        self._chunk_size = chunk_size_tokens or self._settings.chunk_size_tokens
        self._chunk_overlap = chunk_overlap_tokens or self._settings.chunk_overlap_tokens
        self._encoding = tiktoken.get_encoding(encoding_name)

        # tiktoken length function so the splitter measures in tokens, not chars.
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
            length_function=lambda s: len(self._encoding.encode(s)),
            separators=["\n\n", "\n", ". ", " ", ""],
            keep_separator=True,
        )

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        full_text = doc.text
        if not full_text.strip():
            return []

        # split_text gives us the text pieces; we then rebuild offsets and
        # look up which source block each piece came from for provenance.
        pieces = self._splitter.split_text(full_text)
        if not pieces:
            return []

        chunks: list[Chunk] = []
        cursor = 0
        for piece in pieces:
            # Find the next occurrence of `piece` starting from `cursor` so
            # we record stable char offsets even when the splitter inserted
            # overlap. Falls back to cursor if not found (rare).
            located = full_text.find(piece, cursor)
            start = located if located != -1 else cursor
            end = start + len(piece)

            page, section = _provenance_for(doc.blocks, start, end)
            chunks.append(
                Chunk(
                    text=piece.strip(),
                    section_path=section,
                    page_number=page,
                    char_start=start,
                    char_end=end,
                    token_count=len(self._encoding.encode(piece)),
                    metadata={"chunker": "recursive"},
                )
            )
            cursor = max(end - self._chunk_overlap, start + 1)

        return [c for c in chunks if c.text]


def _provenance_for(
    blocks: "Iterable[ParsedBlock]",
    start: int,
    end: int,
) -> tuple[int | None, str | None]:
    """Best-fit page + section for the given char range.

    We pick the block with the largest character overlap with `[start, end)`.
    """
    best_overlap = 0
    best_page: int | None = None
    best_section: str | None = None
    for block in blocks:
        bs = block.char_start or 0
        be = block.char_end or 0
        overlap = max(0, min(end, be) - max(start, bs))
        if overlap > best_overlap:
            best_overlap = overlap
            best_page = block.page_number
            best_section = block.section_path
    return best_page, best_section
