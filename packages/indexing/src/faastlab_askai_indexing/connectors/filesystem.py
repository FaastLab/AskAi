"""Filesystem connector — walks a directory yielding `SourceDocument`s."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

from faastlab_askai_indexing.connectors.base import SourceDocument
from faastlab_askai_indexing.parsers.router import detect_content_type

_DEFAULT_EXTENSIONS = (".pdf", ".docx", ".html", ".htm", ".md", ".markdown")


class FilesystemConnector:
    """Read documents from a local directory."""

    def __init__(
        self,
        root: Path | str,
        *,
        extensions: Iterable[str] = _DEFAULT_EXTENSIONS,
        recursive: bool = True,
    ) -> None:
        self._root = Path(root).expanduser().resolve()
        self._extensions = tuple(e.lower() for e in extensions)
        self._recursive = recursive

    async def iter_documents(self) -> AsyncIterator[SourceDocument]:
        if not self._root.exists():
            raise FileNotFoundError(f"Connector root does not exist: {self._root}")

        glob_pattern = "**/*" if self._recursive else "*"
        for path in sorted(self._root.glob(glob_pattern)):
            if not path.is_file():
                continue
            if path.suffix.lower() not in self._extensions:
                continue

            data = await asyncio.to_thread(path.read_bytes)
            yield SourceDocument(
                source_uri=path.resolve().as_uri(),
                data=data,
                filename=path.name,
                content_type=detect_content_type(path.name),
                metadata={"size_bytes": path.stat().st_size},
            )
