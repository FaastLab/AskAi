"""Markdown-header-aware chunker.

For documents that already carry strong section structure (Markdown,
HTML, DOCX with proper heading styles), splitting on heading boundaries
gives much better retrieval than naive char/token splitting — chunks
align with sections so retrieved snippets read coherently.

Algorithm:
1. Walk parsed blocks; group consecutive non-heading blocks under the
   most recent heading.
2. If a section exceeds the token budget, sub-split with the recursive
   chunker.
"""

from __future__ import annotations

from faastlab_askai_core.config import Settings, get_settings

from faastlab_askai_indexing.chunkers.base import Chunk
from faastlab_askai_indexing.chunkers.recursive import RecursiveChunker
from faastlab_askai_indexing.parsers.base import ParsedBlock, ParsedDocument


class MarkdownHeaderChunker:
    """Group blocks under their nearest heading, sub-split if oversize."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        recursive: RecursiveChunker | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._recursive = recursive or RecursiveChunker(self._settings)
        self._chunk_size = self._settings.chunk_size_tokens

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        if not doc.blocks:
            return []

        groups: list[list[ParsedBlock]] = [[]]
        for block in doc.blocks:
            if block.block_type == "heading" and groups[-1]:
                groups.append([block])
            else:
                groups[-1].append(block)

        chunks: list[Chunk] = []
        for group in groups:
            if not group:
                continue
            # Identify section_path from the first heading in the group, if any.
            heading = next((b for b in group if b.block_type == "heading"), None)
            section_path = heading.section_path if heading else group[0].section_path
            page_number = group[0].page_number

            text = "\n\n".join(b.text for b in group if b.text.strip())
            if not text.strip():
                continue

            token_count = len(self._recursive._encoding.encode(text))  # noqa: SLF001
            if token_count <= self._chunk_size:
                start = group[0].char_start
                end = group[-1].char_end
                chunks.append(
                    Chunk(
                        text=text.strip(),
                        section_path=section_path,
                        page_number=page_number,
                        char_start=start,
                        char_end=end,
                        token_count=token_count,
                        metadata={"chunker": "markdown_header"},
                    )
                )
            else:
                # Section is too big — recursive-split, propagating section.
                synthetic_doc = ParsedDocument(
                    title=doc.title,
                    blocks=group,
                    metadata=doc.metadata,
                )
                for sub in self._recursive.chunk(synthetic_doc):
                    sub.section_path = section_path or sub.section_path
                    sub.page_number = page_number or sub.page_number
                    sub.metadata["chunker"] = "markdown_header+recursive"
                    chunks.append(sub)

        return chunks
