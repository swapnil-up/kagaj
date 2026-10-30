"""Render PDF pages to PNGs for mark-boxes and coordinate-aware OCR.

Produces one PNG per page at a fixed dpi. The pixel space is the same one
mark-boxes records (``px``) and PaddleOCR's ``rec_boxes`` use, so column
regions marked on these images line up with OCR coordinates directly.
"""

from __future__ import annotations

from pathlib import Path

from kagaj_core import pdf as core_pdf

DEFAULT_DPI = 300


def render_pdf(pdf_path: str | Path, out_dir: str | Path,
               dpi: int = DEFAULT_DPI, log=None) -> list[Path]:
    """Render each page of ``pdf_path`` to ``<out_dir>/<stem>_pageN.png``."""
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = core_pdf.open_pdf(pdf_path)
    paths: list[Path] = []
    for i, page in enumerate(core_pdf.iter_pages(doc)):
        pix = core_pdf.render_pixmap(page, dpi=dpi)
        out = out_dir / f"{pdf_path.stem}_page{i + 1}.png"
        pix.save(out)
        paths.append(out)
        if log:
            log(f"[render] page {i + 1}/{doc.page_count} → {out.name}")
    doc.close()
    return paths
