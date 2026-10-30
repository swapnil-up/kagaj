"""Flatten a schedule source file into reading-order text for the LLM.

Two front-ends, one output shape:

* ``xlsx_to_text``  — openpyxl; every sheet becomes ``### sheet: <name>`` followed
  by one line per row (cells joined with `` | ``). Values are stringified, newlines
  collapsed to spaces, so the LLM sees a stable, greppable table.
* ``pdf_to_text``   — PaddleOCR (Devanagari PP-OCRv5) over 300-dpi page renders,
  words re-sorted into reading order and joined per page. The text layer is
  intentionally ignored: KUKL PDFs are either legacy-font (garbled extraction)
  or scans (empty), and OCR handles both uniformly.

Both return ``{"kind", "text", "pages"|"sheets"}`` plus source metadata.
"""

from __future__ import annotations

import re
from pathlib import Path

_TAG_RE = re.compile(r"\s+")


def _clean(value) -> str:
    if value is None:
        return ""
    return _TAG_RE.sub(" ", str(value)).strip()


def xlsx_to_text(path: str | Path) -> dict:
    """Flatten an .xlsx/.xls workbook to text, one block per sheet."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    blocks: list[str] = []
    sheet_names: list[str] = []
    for ws in wb.worksheets:
        sheet_names.append(ws.title)
        blocks.append(f"### sheet: {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = [_clean(c) for c in row]
            if not any(cells):
                continue
            # trim trailing empty cells so rows stay compact
            while cells and cells[-1] == "":
                cells.pop()
            blocks.append(" | ".join(cells))
    wb.close()
    return {"kind": "xlsx", "text": "\n".join(blocks), "sheets": sheet_names}


def pdf_to_text(path: str | Path, log=None) -> dict:
    """OCR every page of a PDF into reading-order Devanagari text."""
    from kagaj_core import ocr as core_ocr
    from kagaj_core import pdf as core_pdf

    def emit(msg: str) -> None:
        if log:
            log(msg)

    doc = core_pdf.open_pdf(path)
    engine = core_ocr.create_engine()
    pages: list[str] = []
    for pn, page in enumerate(core_pdf.iter_pages(doc), 1):
        words = core_ocr.ocr_page(engine, page)
        words.sort(key=lambda w: (round(w.bbox[1], 1), w.bbox[0]))
        text = "\n".join(w.text for w in words if w.text.strip())
        pages.append(text)
        emit(f"[ocr]  page {pn}/{doc.page_count}: {len(words)} words")
    doc.close()
    text = "\n".join(f"### page: {i + 1}\n{p}" for i, p in enumerate(pages))
    return {"kind": "pdf", "text": text, "pages": len(pages)}


def document_text(path: str | Path, log=None) -> dict:
    """Dispatch on file type and return flattened text + metadata."""
    suffix = Path(path).suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return xlsx_to_text(path)
    if suffix == ".pdf":
        return pdf_to_text(path, log=log)
    raise ValueError(f"unsupported source type: {suffix}")
