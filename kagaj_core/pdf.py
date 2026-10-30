"""PyMuPDF helpers shared by extractors.

PyMuPDF is imported lazily so importing :mod:`kagaj_core` never requires the
``redbook`` extra. Coordinates follow PyMuPDF's unrotated text space unless a
function says otherwise; rendered pixmaps/arrays are in display space.
"""

from __future__ import annotations

from typing import Any, Iterator

DEFAULT_DPI = 300


def open_pdf(path, **kwargs):
    """Open a PDF with PyMuPDF, accepting a path or an already-open document."""
    if hasattr(path, "page_count") and hasattr(path, "load_page"):
        return path
    fitz = _fitz()
    return fitz.open(str(path), **kwargs)


def iter_pages(doc, max_pages: int | None = None) -> Iterator[Any]:
    """Yield pages, optionally capped at *max_pages*."""
    limit = doc.page_count if max_pages is None else min(max_pages, doc.page_count)
    for number in range(limit):
        yield doc.load_page(number)


def normalize_bbox(bbox) -> tuple[float, float, float, float]:
    """Return *bbox* as an axis-aligned ``(x0, y0, x1, y1)`` tuple."""
    rect = _fitz().Rect(bbox).normalize()
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def text_space_bbox(page, bbox) -> tuple[float, float, float, float]:
    """Map a display-space box into unrotated text space.

    PyMuPDF returns page coordinates in display space. Rotated pages need the
    derotation matrix before a box can be compared with ``get_texttrace``
    output or stored against a CID.
    """
    if not int(getattr(page, "rotation", 0) or 0):
        return tuple(float(v) for v in bbox)
    fitz = _fitz()
    rect = fitz.Rect(bbox) * page.derotation_matrix
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def render_pixmap(page, dpi: int = DEFAULT_DPI, *, clip=None, rgb: bool = False):
    """Render one page (or *clip*) to a PyMuPDF pixmap at *dpi*."""
    fitz = _fitz()
    zoom = dpi / 72.0
    options = {"matrix": fitz.Matrix(zoom, zoom)}
    if clip is not None:
        options["clip"] = fitz.Rect(clip)
    if rgb:
        options["colorspace"] = fitz.csRGB
    return page.get_pixmap(**options)


def render_page(page, dpi: int = DEFAULT_DPI):
    """Render one page to an RGB ``numpy`` array in display space."""
    import numpy as np

    fitz = _fitz()
    pix = render_pixmap(page, dpi=dpi)
    if pix.colorspace is None or pix.colorspace.name not in (
            "RGB", fitz.csRGB.name):
        pix = fitz.Pixmap(fitz.csRGB, pix)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    if pix.n > 3:
        arr = arr[:, :, :3]
    return arr


def suppress_display_errors() -> None:
    """Silence MuPDF's stderr chatter for malformed PDFs."""
    try:
        _fitz().TOOLS.mupdf_display_errors(False)
    except Exception:  # pragma: no cover - version-dependent
        pass


def get_texttrace(page):
    """Return PyMuPDF's glyph-level text trace (one entry per drawn glyph)."""
    return page.get_texttrace()


def text_words(page) -> list[tuple]:
    """Return PyMuPDF ``get_text('words')`` tuples for the page."""
    return list(page.get_text("words"))


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover - legacy installs expose `fitz`
        import fitz
    return fitz
