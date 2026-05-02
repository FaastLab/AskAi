"""HTML parser — BeautifulSoup with main-content extraction."""

from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag

from faastlab_askai_indexing.parsers.base import (
    ParsedBlock,
    ParsedDocument,
    ParserError,
)

_HTML_MIME_TYPES = ("text/html", "application/xhtml+xml")
_BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_DROP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript"}


class HtmlParser:
    """HTML → ParsedDocument."""

    @property
    def supported_content_types(self) -> tuple[str, ...]:
        return _HTML_MIME_TYPES

    def parse(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        try:
            soup = BeautifulSoup(data, "lxml")
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"BeautifulSoup failed to parse HTML: {exc}") from exc

        for tag in soup(_DROP_TAGS):
            tag.decompose()

        title: str | None = None
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # Prefer <main> or <article> if present; fall back to <body>.
        root: Tag | None = soup.find("main") or soup.find("article") or soup.body
        if root is None:
            root = soup

        blocks: list[ParsedBlock] = []
        char_offset = 0
        section_path: list[str] = []

        for tag in root.find_all(_BLOCK_TAGS):
            text_value = _stringify(tag).strip()
            if not text_value:
                continue
            block_type: str = "paragraph"
            if tag.name in _HEADING_TAGS:
                block_type = "heading"
                level = int(tag.name[1])
                section_path = section_path[: max(level - 1, 0)]
                section_path.append(text_value)
                if not title:
                    title = text_value
            elif tag.name == "li":
                block_type = "list_item"
            elif tag.name == "pre":
                block_type = "code"

            start = char_offset
            end = char_offset + len(text_value)
            blocks.append(
                ParsedBlock(
                    text=text_value,
                    block_type=block_type,  # type: ignore[arg-type]
                    section_path=" / ".join(section_path) if section_path else None,
                    char_start=start,
                    char_end=end,
                )
            )
            char_offset = end + 2

        if (not title) and filename:
            title = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]

        return ParsedDocument(
            title=title,
            blocks=blocks,
            metadata={"parser": "beautifulsoup4"},
        )


def _stringify(tag: Tag) -> str:
    """Tag → flat string with single spaces."""
    parts = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            parts.append(_stringify(child))
    return " ".join("".join(parts).split())
