"""XLSX parser — one block per spreadsheet row, headers attached.

Why a dedicated parser: generic extractors flatten a workbook into one
long text stream. Two things then go wrong:

1. Managed indexers cap the text they extract per document (Azure AI
   Search stops at a few million characters depending on tier), so rows
   past the cap are silently never indexed.
2. Even when everything fits, size-based chunking cuts rows in half and
   separates values from their column headers, so a chunk reads
   "42 | 2019 | Yes" with no idea what those numbers mean.

This parser emits one `table_row` block per data row, rendered as
`Header: value` lines prefixed with the sheet name and row number, so
every row is a self-describing unit that `RowChunker` can index 1:1 and
citations can point at the exact sheet and row.
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Any

from faastlab_askai_indexing.parsers.base import (
    ParsedBlock,
    ParsedDocument,
    ParserError,
)

_XLSX_MIME_TYPES = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
)


def _cell_text(value: Any) -> str:
    """Render a cell value as clean text ('' for empty)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        # Drop a midnight time component — most "dates" in sheets are dates.
        if value.hour == value.minute == value.second == 0:
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


class XlsxParser:
    """XLSX → ParsedDocument with one `table_row` block per data row.

    The first non-empty row of each sheet is treated as the header row.
    Blank header cells fall back to the column letter (`Column C`).
    Fully empty rows are skipped. Hidden sheets are skipped by default.
    """

    def __init__(self, *, include_hidden_sheets: bool = False, max_rows_per_sheet: int | None = None) -> None:
        self._include_hidden = include_hidden_sheets
        self._max_rows = max_rows_per_sheet

    @property
    def supported_content_types(self) -> tuple[str, ...]:
        return _XLSX_MIME_TYPES

    def parse(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        try:
            from openpyxl import load_workbook
            from openpyxl.utils import get_column_letter
        except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
            raise ParserError("openpyxl is required to parse XLSX files") from exc

        try:
            # read_only streams rows (low memory on big workbooks);
            # data_only returns cached formula results instead of formulas.
            wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"openpyxl failed to open XLSX: {exc}") from exc

        blocks: list[ParsedBlock] = []
        char_offset = 0
        sheet_names: list[str] = []
        total_rows = 0

        try:
            for ws in wb.worksheets:
                if not self._include_hidden and getattr(ws, "sheet_state", "visible") != "visible":
                    continue
                sheet_names.append(ws.title)
                headers: list[str] | None = None
                emitted = 0

                for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                    cells = [_cell_text(v) for v in row]
                    if not any(cells):
                        continue
                    if headers is None:
                        headers = [
                            c or f"Column {get_column_letter(i + 1)}" for i, c in enumerate(cells)
                        ]
                        continue

                    pairs: list[tuple[str, str]] = []
                    for i, value in enumerate(cells):
                        if not value:
                            continue
                        header = headers[i] if i < len(headers) else f"Column {get_column_letter(i + 1)}"
                        pairs.append((header, value))
                    if not pairs:
                        continue

                    lines = [f"Sheet: {ws.title} | Row {row_idx}"]
                    lines.extend(f"{h}: {v}" for h, v in pairs)
                    text = "\n".join(lines)

                    blocks.append(
                        ParsedBlock(
                            text=text,
                            block_type="table_row",
                            section_path=ws.title,
                            char_start=char_offset,
                            char_end=char_offset + len(text),
                            metadata={
                                "sheet": ws.title,
                                "row": row_idx,
                                "fields": dict(pairs),
                            },
                        )
                    )
                    # +2 for the "\n\n" join in ParsedDocument.text
                    char_offset += len(text) + 2
                    emitted += 1
                    total_rows += 1
                    if self._max_rows is not None and emitted >= self._max_rows:
                        break
        finally:
            wb.close()

        title = None
        if filename:
            title = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]

        return ParsedDocument(
            title=title,
            blocks=blocks,
            page_count=None,
            metadata={
                "parser": "openpyxl",
                "sheets": sheet_names,
                "row_count": total_rows,
            },
        )


__all__ = ["XlsxParser"]
