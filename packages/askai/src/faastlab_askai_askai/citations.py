"""Map [N]-style inline citations back to source chunks.

The model emits citations as `[1]`, `[2]`, etc., where N corresponds to
the position of the chunk in the prompt's numbered context block. We
parse the answer for those markers, deduplicate, and emit a list of
`Citation` objects pointing at the original `RetrievedChunk`s.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from faastlab_askai_core.schemas.search import Citation
from faastlab_askai_search.retrievers.base import RetrievedChunk

_CITATION_RE = re.compile(r"\[(\d+)\]")


def extract_citations(
    answer: str,
    chunks: Sequence[RetrievedChunk],
    *,
    snippet_chars: int = 220,
) -> list[Citation]:
    """Return one Citation per UNIQUE referenced chunk, in first-mention order."""
    seen: set[int] = set()
    citations: list[Citation] = []
    for match in _CITATION_RE.finditer(answer):
        idx = int(match.group(1))
        if idx in seen or not (1 <= idx <= len(chunks)):
            continue
        seen.add(idx)
        chunk = chunks[idx - 1]
        snippet = chunk.content.strip().replace("\n", " ")
        if len(snippet) > snippet_chars:
            snippet = snippet[:snippet_chars].rsplit(" ", 1)[0] + "…"
        citations.append(
            Citation(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_title=chunk.document_title,
                page_number=chunk.page_number,
                section_path=chunk.section_path,
                snippet=snippet,
            )
        )
    return citations
