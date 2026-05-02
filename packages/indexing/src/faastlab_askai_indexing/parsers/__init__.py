"""Document parsers — bytes → structured text blocks."""

from faastlab_askai_indexing.parsers.base import (
    ParsedBlock,
    ParsedDocument,
    Parser,
    ParserError,
)
from faastlab_askai_indexing.parsers.docx import DocxParser
from faastlab_askai_indexing.parsers.html import HtmlParser
from faastlab_askai_indexing.parsers.markdown import MarkdownParser
from faastlab_askai_indexing.parsers.pdf import PdfParser
from faastlab_askai_indexing.parsers.router import detect_content_type, get_parser

__all__ = [
    "DocxParser",
    "HtmlParser",
    "MarkdownParser",
    "ParsedBlock",
    "ParsedDocument",
    "Parser",
    "ParserError",
    "PdfParser",
    "detect_content_type",
    "get_parser",
]
