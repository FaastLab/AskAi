"""Parser router — pick the right parser by content-type or filename."""

from __future__ import annotations

import mimetypes

from faastlab_askai_core.exceptions import ParserError

from faastlab_askai_indexing.parsers.base import Parser
from faastlab_askai_indexing.parsers.docx import DocxParser
from faastlab_askai_indexing.parsers.html import HtmlParser
from faastlab_askai_indexing.parsers.markdown import MarkdownParser
from faastlab_askai_indexing.parsers.pdf import PdfParser

_REGISTRY: dict[str, type[Parser]] = {
    "application/pdf": PdfParser,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxParser,
    "text/html": HtmlParser,
    "application/xhtml+xml": HtmlParser,
    "text/markdown": MarkdownParser,
    "text/x-markdown": MarkdownParser,
}

_EXTENSION_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


def detect_content_type(filename: str | None, *, default: str = "application/pdf") -> str:
    """Best-effort MIME type from a filename's extension.

    Falls back to `mimetypes.guess_type` then to `default`. Used by the
    pipeline when callers haven't supplied an explicit content type.
    """
    if not filename:
        return default
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _EXTENSION_TO_MIME:
        return _EXTENSION_TO_MIME[ext]
    guess, _ = mimetypes.guess_type(filename)
    return guess or default


def get_parser(content_type: str) -> Parser:
    """Return a parser instance for `content_type`. Raises if unsupported."""
    cls = _REGISTRY.get(content_type)
    if cls is None:
        raise ParserError(
            f"No parser registered for content type {content_type!r}. "
            f"Supported: {sorted(_REGISTRY)}"
        )
    return cls()
