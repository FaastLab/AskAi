"""XLSX parser + row chunker tests."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pytest
from openpyxl import Workbook

from faastlab_askai_indexing.chunkers import RowChunker, get_chunker
from faastlab_askai_indexing.parsers import ParserError, XlsxParser, detect_content_type, get_parser


def _workbook_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Standards"
    ws.append([])  # leading blank row — header detection should skip it
    ws.append(["Code", "Title", "Issued", "", "Owner"])
    ws.append(["STD-001", "Track drainage", datetime(2019, 3, 1), "x", "Civils"])
    ws.append([None, None, None, None, None])  # blank row, skipped
    ws.append(["STD-002", "Signal cabling", 12.0, None, None])

    hidden = wb.create_sheet("Secret")
    hidden.append(["A"])
    hidden.append(["should not appear"])
    hidden.sheet_state = "hidden"

    notes = wb.create_sheet("Notes")
    notes.append(["Topic", "Note"])
    notes.append(["Scope", "Applies to all routes"])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_one_block_per_data_row_with_headers() -> None:
    doc = XlsxParser().parse(_workbook_bytes(), filename="All_Standards.xlsx")

    assert doc.title == "All_Standards"
    assert doc.metadata["parser"] == "openpyxl"
    assert doc.metadata["sheets"] == ["Standards", "Notes"]  # hidden skipped
    assert doc.metadata["row_count"] == 3
    assert [b.block_type for b in doc.blocks] == ["table_row"] * 3

    first = doc.blocks[0]
    assert first.text.splitlines()[0] == "Sheet: Standards | Row 3"
    assert "Code: STD-001" in first.text
    assert "Issued: 2019-03-01" in first.text  # midnight datetime → date
    assert "Column D: x" in first.text  # blank header → column letter
    assert first.section_path == "Standards"
    assert first.metadata["row"] == 3


def test_empty_cells_and_integer_floats() -> None:
    doc = XlsxParser().parse(_workbook_bytes())
    second = doc.blocks[1]
    assert "Issued: 12" in second.text  # 12.0 → "12"
    assert "Owner" not in second.text  # empty cell omitted


def test_char_offsets_match_document_text() -> None:
    doc = XlsxParser().parse(_workbook_bytes())
    for b in doc.blocks:
        assert doc.text[b.char_start : b.char_end] == b.text


def test_hidden_sheets_opt_in() -> None:
    doc = XlsxParser(include_hidden_sheets=True).parse(_workbook_bytes())
    assert "Secret" in doc.metadata["sheets"]


def test_invalid_bytes_raise_parser_error() -> None:
    with pytest.raises(ParserError):
        XlsxParser().parse(b"not a workbook")


def test_router_wiring() -> None:
    assert detect_content_type("x.xlsx").endswith("spreadsheetml.sheet")
    assert isinstance(get_parser(detect_content_type("x.xlsx")), XlsxParser)
    doc = XlsxParser().parse(_workbook_bytes())
    assert isinstance(get_chunker(doc), RowChunker)


def test_row_chunker_one_chunk_per_row() -> None:
    doc = XlsxParser().parse(_workbook_bytes())
    chunks = RowChunker(token_counter=lambda s: len(s.split())).chunk(doc)
    assert len(chunks) == len(doc.blocks)
    assert chunks[0].metadata["sheet"] == "Standards"
    assert chunks[0].metadata["row"] == 3
    assert "fields" not in chunks[0].metadata


def test_row_chunker_splits_wide_rows_and_repeats_header() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Wide"
    ws.append([f"H{i}" for i in range(20)])
    ws.append([f"value number {i}" for i in range(20)])
    buf = BytesIO()
    wb.save(buf)
    doc = XlsxParser().parse(buf.getvalue())

    chunks = RowChunker(max_tokens=20, token_counter=lambda s: len(s.split())).chunk(doc)
    assert len(chunks) > 1
    for i, c in enumerate(chunks, start=1):
        assert c.text.startswith("Sheet: Wide | Row 2")
        assert c.metadata["row_part"] == i
    joined = "\n".join(chunks_text for c in chunks for chunks_text in c.text.splitlines()[1:])
    for i in range(20):
        assert f"H{i}: value number {i}" in joined
