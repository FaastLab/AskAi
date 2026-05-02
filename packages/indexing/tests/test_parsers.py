"""Parser tests using static fixtures (no PDF — that requires a real file)."""

from __future__ import annotations

from pathlib import Path

import pytest

from faastlab_askai_indexing.parsers import (
    HtmlParser,
    MarkdownParser,
    detect_content_type,
    get_parser,
)
from faastlab_askai_indexing.parsers.base import ParserError

FIXTURES = Path(__file__).parent / "fixtures"


def test_detect_content_type_known_extensions() -> None:
    assert detect_content_type("foo.pdf") == "application/pdf"
    assert detect_content_type("foo.md") == "text/markdown"
    assert detect_content_type("foo.html") == "text/html"
    assert detect_content_type("foo.docx").endswith("wordprocessingml.document")


def test_detect_content_type_default_when_unknown() -> None:
    assert detect_content_type(None) == "application/pdf"
    assert detect_content_type("foo.unknownext") == "application/pdf"


def test_get_parser_for_unsupported_type_raises() -> None:
    with pytest.raises(ParserError):
        get_parser("application/x-nonsense")


def test_markdown_parser_preserves_section_path() -> None:
    data = (FIXTURES / "sample.md").read_bytes()
    parser = MarkdownParser()
    doc = parser.parse(data, filename="sample.md")

    assert doc.title == "Sample Regulation"
    headings = [b for b in doc.blocks if b.block_type == "heading"]
    assert any(h.text == "Capital Requirements" or "Capital" in h.text for h in headings)

    # Tier 1 paragraph should sit under "Sample Regulation / 1. … / 1.1 Tier 1"
    tier1_paragraphs = [
        b for b in doc.blocks
        if "Common Equity Tier 1" in b.text and b.block_type == "paragraph"
    ]
    assert tier1_paragraphs
    assert "Tier 1" in (tier1_paragraphs[0].section_path or "")


def test_html_parser_drops_chrome_and_keeps_main() -> None:
    data = (FIXTURES / "sample.html").read_bytes()
    parser = HtmlParser()
    doc = parser.parse(data, filename="sample.html")

    flat = doc.text
    assert "Consumer Duty" in flat
    assert "Cross-cutting" in flat
    assert "Footer text" not in flat  # <footer> dropped
    assert "Skip to content" not in flat  # <nav> dropped


def test_markdown_parser_blocks_have_offsets() -> None:
    data = (FIXTURES / "sample.md").read_bytes()
    doc = MarkdownParser().parse(data, filename="sample.md")
    for b in doc.blocks:
        assert b.char_start is not None
        assert b.char_end is not None
        assert b.char_end >= b.char_start
