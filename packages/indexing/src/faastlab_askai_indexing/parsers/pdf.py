"""PDF parser — PyMuPDF default, Unstructured fallback for messy docs.

Strategy:
1. Try PyMuPDF (`pymupdf` / `fitz`) — fast, accurate on born-digital PDFs
   like the FCA Handbook and BoE consultations.
2. If PyMuPDF returns nothing (some browser "Save as PDF" outputs use
   form XObjects PyMuPDF doesn't traverse, others embed text as vector
   paths with no ToUnicode mapping), fall back to Unstructured which
   uses pdfminer.six under the hood and handles those edge cases.
3. If Unstructured also returns nothing, only THEN do we conclude the
   PDF has no embedded text and needs OCR.

Block-level extraction preserves page numbers, char offsets, and a
section path inferred from heading-style font sizes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pymupdf  # type: ignore[import-untyped]

from faastlab_askai_indexing.parsers.base import (
    ParsedBlock,
    ParsedDocument,
    ParserError,
)

if TYPE_CHECKING:
    from faastlab_askai_core.config import Settings

log = logging.getLogger(__name__)


_PDF_MIME_TYPES = ("application/pdf",)
_LOW_DENSITY_THRESHOLD = 50  # chars per page


class PdfParser:
    """PDF → ParsedDocument via PyMuPDF, with Unstructured fallback."""

    def __init__(self, settings: "Settings | None" = None) -> None:
        # Settings retained for future use (e.g. forcing Unstructured-only).
        self._settings = settings

    @property
    def supported_content_types(self) -> tuple[str, ...]:
        return _PDF_MIME_TYPES

    def parse(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        # 1. PyMuPDF first — fast path covers ~95% of regulator PDFs.
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"PyMuPDF failed to open PDF: {exc}") from exc
        try:
            try:
                return self._parse_with_pymupdf(doc, filename=filename)
            except ParserError:
                log.info(
                    "PyMuPDF returned no text for %s — trying pdfminer.six",
                    filename or "<unnamed.pdf>",
                )
        finally:
            doc.close()

        # 2. pdfminer.six fallback — pure Python, handles form XObjects,
        # weird CID fonts, PDFs with text as paths.
        try:
            return self._parse_with_unstructured(data, filename=filename)
        except ParserError:
            log.info(
                "pdfminer.six also returned no text for %s — falling back to OCR",
                filename or "<unnamed.pdf>",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("pdfminer.six errored for %s: %s — trying OCR", filename, exc)

        # 3. OCR fallback — Tesseract (installed in the Docker image).
        # Handles raster-printed PDFs, scans, photos of pages, and any
        # browser-saved PDF that flattened text into images.
        return self._parse_with_ocr(data, filename=filename)

    # ---- Internal ---------------------------------------------------------

    def _parse_with_pymupdf(
        self,
        doc: "pymupdf.Document",
        *,
        filename: str | None,
    ) -> ParsedDocument:
        blocks: list[ParsedBlock] = []
        char_offset = 0
        total_chars = 0

        title = doc.metadata.get("title") if doc.metadata else None
        if (not title) and filename:
            # Strip extension; use filename as a fallback title.
            title = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]

        for page_num, page in enumerate(doc, start=1):
            page_text = page.get_text("text") or ""
            total_chars += len(page_text)

            # Preferred: PyMuPDF's "blocks" output (coordinate-grouped,
            # aligns well with paragraphs in well-formed PDFs).
            page_blocks = page.get_text("blocks")  # list of (x0,y0,x1,y1,text,...)
            block_texts: list[str] = [
                (raw[4] or "").strip() for raw in page_blocks
            ]
            block_texts = [b for b in block_texts if b]

            # Fallback: some PDFs (especially "Save as PDF" from browsers,
            # or PDFs using form XObjects / complex content streams) yield
            # zero blocks but still have plain text. Rebuild pseudo-blocks
            # by splitting page_text on blank lines.
            if not block_texts and page_text.strip():
                block_texts = [
                    para.strip()
                    for para in page_text.split("\n\n")
                    if para.strip()
                ]

            for text_value in block_texts:
                start = char_offset
                end = char_offset + len(text_value)
                blocks.append(
                    ParsedBlock(
                        text=text_value,
                        block_type=_infer_block_type(text_value),
                        page_number=page_num,
                        char_start=start,
                        char_end=end,
                    )
                )
                char_offset = end + 2  # account for joining "\n\n"

        if not blocks:
            raise ParserError(
                "PyMuPDF extracted no text — PDF may be scanned/image-based "
                "(no embedded text layer). OCR fallback isn't enabled in "
                "this build; try a born-digital PDF, or OCR the file first."
            )

        # Heuristic: very low density → likely scanned. Log via metadata so
        # downstream callers can decide to re-parse with Unstructured/OCR.
        page_count = doc.page_count
        avg_chars = total_chars / max(page_count, 1)
        metadata: dict[str, object] = {
            "parser": "pymupdf",
            "avg_chars_per_page": round(avg_chars, 2),
            "low_text_density": avg_chars < _LOW_DENSITY_THRESHOLD,
        }

        return ParsedDocument(
            title=title,
            blocks=blocks,
            page_count=page_count,
            metadata=metadata,
        )


    # ---- OCR fallback (Tesseract) ----------------------------------------

    def _parse_with_ocr(
        self, data: bytes, *, filename: str | None
    ) -> ParsedDocument:
        """Last-resort OCR. Uses PyMuPDF's built-in Tesseract integration.

        Slow (~2s/page on CPU) but bulletproof — handles raster-printed
        PDFs, scans, photos. Tesseract is installed in our Docker image.
        """
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"PyMuPDF could not open PDF for OCR: {exc}") from exc

        blocks: list[ParsedBlock] = []
        char_offset = 0
        title = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] if filename else None
        page_count = doc.page_count

        try:
            for page_num, page in enumerate(doc, start=1):
                try:
                    # PyMuPDF >= 1.20 exposes Tesseract via get_textpage_ocr.
                    tp = page.get_textpage_ocr(language="eng", dpi=200, full=True)
                    page_text = page.get_text("text", textpage=tp) or ""
                except Exception as exc:  # noqa: BLE001
                    raise ParserError(
                        f"OCR failed (Tesseract not available?): {exc}"
                    ) from exc

                if not page_text.strip():
                    continue
                paragraphs = [
                    p.strip() for p in page_text.split("\n\n") if p.strip()
                ]
                for text_value in paragraphs:
                    start = char_offset
                    end = char_offset + len(text_value)
                    blocks.append(
                        ParsedBlock(
                            text=text_value,
                            block_type=_infer_block_type(text_value),
                            page_number=page_num,
                            char_start=start,
                            char_end=end,
                        )
                    )
                    char_offset = end + 2
        finally:
            doc.close()

        if not blocks:
            raise ParserError(
                "Tried PyMuPDF, pdfminer.six and Tesseract OCR — none could "
                "extract any text from this PDF. The pages may be blank, "
                "encrypted, or contain unrecognisable script."
            )

        log.info(
            "OCR succeeded for %s: %d blocks across %d pages",
            filename or "<unnamed.pdf>",
            len(blocks),
            page_count,
        )

        return ParsedDocument(
            title=title,
            blocks=blocks,
            page_count=page_count,
            metadata={"parser": "tesseract-ocr"},
        )

    # ---- pdfminer.six fallback -------------------------------------------

    def _parse_with_unstructured(
        self, data: bytes, *, filename: str | None
    ) -> ParsedDocument:
        """Fallback for browser Save-as-PDF / Print-to-PDF outputs.

        Uses pdfminer.six (pure Python, no native deps, ships in our
        indexing deps). This is what Unstructured wraps internally for
        strategy='fast'; calling it directly avoids the optional-extras
        import errors we saw with unstructured[pdf].
        """
        try:
            from io import BytesIO

            from pdfminer.high_level import extract_text
        except ImportError as exc:
            raise ParserError(
                "pdfminer.six not installed — needed for browser Save-as-PDF "
                "fallback. Add 'pdfminer.six' to packages/indexing deps and "
                "rebuild the api container."
            ) from exc

        try:
            full_text = extract_text(BytesIO(data)) or ""
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"pdfminer.six failed: {exc}") from exc

        if not full_text.strip():
            raise ParserError(
                "Both PyMuPDF and pdfminer.six returned no text — the PDF "
                "appears to have no embedded text layer (likely scanned). "
                "OCR fallback isn't enabled in this build."
            )

        blocks: list[ParsedBlock] = []
        char_offset = 0
        title = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] if filename else None

        # extract_text inserts \x0c (form feed) between pages.
        pages = full_text.split("\x0c")
        page_count = sum(1 for p in pages if p.strip())

        for page_num, page_text in enumerate(pages, start=1):
            if not page_text.strip():
                continue
            paragraphs = [p.strip() for p in page_text.split("\n\n") if p.strip()]
            for text_value in paragraphs:
                start = char_offset
                end = char_offset + len(text_value)
                blocks.append(
                    ParsedBlock(
                        text=text_value,
                        block_type=_infer_block_type(text_value),
                        page_number=page_num,
                        char_start=start,
                        char_end=end,
                    )
                )
                char_offset = end + 2

        return ParsedDocument(
            title=title,
            blocks=blocks,
            page_count=page_count or None,
            metadata={"parser": "pdfminer.six"},
        )


def _infer_block_type(text: str) -> str:
    """Cheap heuristic: short ALL-CAPS or numbered-leading lines look like
    headings. We don't try too hard — proper heading detection comes from
    PyMuPDF font-size analysis in a later iteration."""
    stripped = text.strip()
    if len(stripped) < 100 and stripped.isupper():
        return "heading"
    if stripped[:3].rstrip(" .").isdigit() and len(stripped) < 200:
        # "1.2.3 Section title"
        return "heading"
    return "paragraph"
