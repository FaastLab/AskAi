"""Pick a chunker by document type / parser metadata."""

from __future__ import annotations

from faastlab_askai_indexing.chunkers.base import Chunker
from faastlab_askai_indexing.chunkers.markdown import MarkdownHeaderChunker
from faastlab_askai_indexing.chunkers.recursive import RecursiveChunker
from faastlab_askai_indexing.parsers.base import ParsedDocument

# Parsers that already produce strong heading structure → header chunker.
_HEADING_AWARE_PARSERS = {"markdown", "python-docx", "beautifulsoup4"}


def get_chunker(doc: ParsedDocument) -> Chunker:
    """Return the appropriate chunker for a parsed document.

    PDFs get the recursive chunker (heading inference is unreliable);
    everything else with strong heading metadata gets header-aware.
    """
    parser = (doc.metadata or {}).get("parser", "")
    if parser in _HEADING_AWARE_PARSERS:
        return MarkdownHeaderChunker()
    return RecursiveChunker()
