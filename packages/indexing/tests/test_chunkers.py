"""Chunker tests."""

from __future__ import annotations

from pathlib import Path

from faastlab_askai_indexing.chunkers.markdown import MarkdownHeaderChunker
from faastlab_askai_indexing.chunkers.recursive import RecursiveChunker
from faastlab_askai_indexing.chunkers.router import get_chunker
from faastlab_askai_indexing.parsers import MarkdownParser

FIXTURES = Path(__file__).parent / "fixtures"


def _parse_sample() -> "MarkdownParser":
    data = (FIXTURES / "sample.md").read_bytes()
    return MarkdownParser().parse(data, filename="sample.md")


def test_recursive_chunker_emits_chunks() -> None:
    doc = _parse_sample()
    chunks = RecursiveChunker(chunk_size_tokens=50, chunk_overlap_tokens=10).chunk(doc)
    assert chunks, "expected at least one chunk"
    for c in chunks:
        assert c.text.strip()
        assert c.token_count is not None and c.token_count > 0


def test_recursive_chunker_respects_token_budget() -> None:
    doc = _parse_sample()
    budget = 40
    chunks = RecursiveChunker(chunk_size_tokens=budget, chunk_overlap_tokens=5).chunk(doc)
    # Allow some slack for the splitter's separator preservation.
    for c in chunks:
        assert (c.token_count or 0) <= budget * 1.5


def test_markdown_header_chunker_groups_by_section() -> None:
    doc = _parse_sample()
    chunks = MarkdownHeaderChunker(
        recursive=RecursiveChunker(chunk_size_tokens=400, chunk_overlap_tokens=50),
    ).chunk(doc)
    # Each section should produce at least one chunk with a section_path.
    section_paths = {c.section_path for c in chunks if c.section_path}
    assert section_paths
    assert any("Tier 1" in p for p in section_paths)


def test_router_picks_header_chunker_for_markdown() -> None:
    doc = _parse_sample()
    chunker = get_chunker(doc)
    assert isinstance(chunker, MarkdownHeaderChunker)
