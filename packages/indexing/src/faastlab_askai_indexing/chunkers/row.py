"""Row chunker — one chunk per spreadsheet row.

Pairs with `XlsxParser`: each `table_row` block already carries its
sheet name, row number and column headers, so the right chunk boundary
is the row itself. Size-based splitting would only cut rows in half.

A row longer than the token budget (very wide sheets, long free-text
cells) is split on field boundaries, and every piece repeats the
`Sheet: ... | Row N` line so it stays self-describing.
"""

from __future__ import annotations

from collections.abc import Callable

from faastlab_askai_indexing.chunkers.base import Chunk
from faastlab_askai_indexing.parsers.base import ParsedDocument


def _default_token_counter(encoding_name: str) -> Callable[[str], int]:
    """tiktoken when its encoding is available, else a ~4 chars/token estimate.

    tiktoken downloads its BPE file on first use; air-gapped installs
    shouldn't fail to index spreadsheets because of that.
    """
    try:
        import tiktoken

        enc = tiktoken.get_encoding(encoding_name)
        return lambda s: len(enc.encode(s))
    except Exception:  # noqa: BLE001
        return lambda s: max(1, len(s) // 4)


class RowChunker:
    """ParsedDocument (table rows) → one Chunk per row."""

    def __init__(
        self,
        *,
        max_tokens: int = 512,
        encoding_name: str = "cl100k_base",
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.max_tokens = max_tokens
        self._count = token_counter or _default_token_counter(encoding_name)

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        for block in doc.blocks:
            text = block.text.strip()
            if not text:
                continue
            meta = {k: v for k, v in (block.metadata or {}).items() if k != "fields"}
            meta["block_type"] = block.block_type

            tokens = self._count(text)
            if tokens <= self.max_tokens:
                chunks.append(
                    Chunk(
                        text=text,
                        section_path=block.section_path,
                        page_number=block.page_number,
                        char_start=block.char_start,
                        char_end=block.char_end,
                        token_count=tokens,
                        metadata=meta,
                    )
                )
                continue

            # Oversized row: split on field lines, repeat the header line.
            header, *fields = text.split("\n")
            piece: list[str] = []
            part = 1

            def flush() -> None:
                nonlocal piece, part
                if not piece:
                    return
                body = "\n".join([header, *piece])
                chunks.append(
                    Chunk(
                        text=body,
                        section_path=block.section_path,
                        page_number=block.page_number,
                        char_start=block.char_start,
                        char_end=block.char_end,
                        token_count=self._count(body),
                        metadata={**meta, "row_part": part},
                    )
                )
                piece = []
                part += 1

            for line in fields:
                candidate = "\n".join([header, *piece, line])
                if piece and self._count(candidate) > self.max_tokens:
                    flush()
                piece.append(line)
            flush()
        return chunks


__all__ = ["RowChunker"]
