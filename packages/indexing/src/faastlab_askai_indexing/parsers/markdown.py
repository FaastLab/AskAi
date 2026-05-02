"""Markdown parser — splits on ATX headings and paragraphs.

Kept dependency-light (no `markdown` package call): we just walk the
text line by line. This preserves heading hierarchy in `section_path`
so the chunker can emit per-section chunks downstream.
"""

from __future__ import annotations

import re

from faastlab_askai_indexing.parsers.base import ParsedBlock, ParsedDocument

_MD_MIME_TYPES = ("text/markdown", "text/x-markdown")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+")


class MarkdownParser:
    """Markdown → ParsedDocument."""

    @property
    def supported_content_types(self) -> tuple[str, ...]:
        return _MD_MIME_TYPES

    def parse(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        text = data.decode("utf-8", errors="replace")
        blocks: list[ParsedBlock] = []
        char_offset = 0
        section_path: list[str] = []
        title: str | None = None
        buffer: list[str] = []

        def flush_paragraph() -> None:
            nonlocal char_offset
            if not buffer:
                return
            paragraph = "\n".join(buffer).strip()
            buffer.clear()
            if not paragraph:
                return
            start = char_offset
            end = char_offset + len(paragraph)
            blocks.append(
                ParsedBlock(
                    text=paragraph,
                    block_type=_classify_paragraph(paragraph),
                    section_path=" / ".join(section_path) if section_path else None,
                    char_start=start,
                    char_end=end,
                )
            )
            char_offset = end + 2

        for line in text.splitlines():
            heading_match = _HEADING_RE.match(line)
            if heading_match:
                flush_paragraph()
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                section_path = section_path[: max(level - 1, 0)]
                section_path.append(heading_text)
                if not title:
                    title = heading_text
                start = char_offset
                end = char_offset + len(heading_text)
                blocks.append(
                    ParsedBlock(
                        text=heading_text,
                        block_type="heading",
                        section_path=" / ".join(section_path),
                        char_start=start,
                        char_end=end,
                    )
                )
                char_offset = end + 2
                continue

            if line.strip() == "":
                flush_paragraph()
                continue

            buffer.append(line)

        flush_paragraph()

        if (not title) and filename:
            title = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]

        return ParsedDocument(
            title=title,
            blocks=blocks,
            metadata={"parser": "markdown"},
        )


def _classify_paragraph(text: str) -> str:
    if _LIST_RE.match(text):
        return "list_item"
    if text.startswith("```"):
        return "code"
    return "paragraph"
