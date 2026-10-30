"""PDF crop rendering for review items.

Adapters pass text-space bboxes (the coordinate space used by
``page.get_texttrace`` and the census). Rendering maps them into display space,
clips them to the visible page, and returns data-URI PNGs. PyMuPDF and numpy are
imported lazily so importing this module stays cheap.
"""

from __future__ import annotations

import base64
import logging
import math

from .model import ReviewCrop

_LOG = logging.getLogger(__name__)

WORD_DPI = 300
WORD_MARGIN = 8.0
_GLYPH_TARGET_PX = 260.0
_GLYPH_DPI_MIN = 300
_GLYPH_DPI_MAX = 600
_MAX_PIXELS = 16_000_000


def _rect(value):
    if value is None:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        return None
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return (x0, y0, x1, y1)


def _nonempty(rect):
    return bool(rect) and rect[2] > rect[0] and rect[3] > rect[1]


def _page_rect(page):
    rect = _rect(getattr(page, "rect", None))
    return rect if _nonempty(rect) else None


def _pad(rect, pad):
    return (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)


def _intersect(a, b):
    if a is None or b is None:
        return None
    out = (max(a[0], b[0]), max(a[1], b[1]),
           min(a[2], b[2]), min(a[3], b[3]))
    return out if _nonempty(out) else None


def _rotation(page):
    try:
        return int(getattr(page, "rotation", 0) or 0) % 360
    except (TypeError, ValueError):
        return 0


def _rotate_point(x, y, width, height, rotation):
    if rotation == 90:
        return height - y, x
    if rotation == 180:
        return width - x, height - y
    if rotation == 270:
        return y, width - x
    return x, y


def _unrotate_point(x, y, width, height, rotation):
    if rotation == 90:
        return y, height - x
    if rotation == 180:
        return width - x, height - y
    if rotation == 270:
        return width - y, x
    return x, y


def _map_rect(rect, width, height, rotation, inverse=False):
    mapper = _unrotate_point if inverse else _rotate_point
    points = [
        mapper(rect[0], rect[1], width, height, rotation),
        mapper(rect[0], rect[3], width, height, rotation),
        mapper(rect[2], rect[1], width, height, rotation),
        mapper(rect[2], rect[3], width, height, rotation),
    ]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _page_size(page, page_rect):
    width = page_rect[2] - page_rect[0]
    height = page_rect[3] - page_rect[1]
    if _rotation(page) in (90, 270):
        return height, width
    return width, height


def _display_bbox(page, bbox):
    rect = _rect(bbox)
    page_rect = _page_rect(page)
    if rect is None or page_rect is None:
        return None
    rotation = _rotation(page)
    if rotation == 0:
        return rect
    width, height = _page_size(page, page_rect)
    return _map_rect(rect, width, height, rotation)


def _text_bbox(page, bbox):
    rect = _rect(bbox)
    page_rect = _page_rect(page)
    if rect is None or page_rect is None:
        return None
    rotation = _rotation(page)
    if rotation == 0:
        return rect
    width, height = _page_size(page, page_rect)
    return _map_rect(rect, width, height, rotation, inverse=True)


def _expand_glyph_bbox(rect):
    width = max(rect[2] - rect[0], 1.0)
    height = max(rect[3] - rect[1], 1.0)
    pad_x = max(width * 0.20, 2.5)
    pad_y = max(height * 0.12, 2.0)
    return (rect[0] - pad_x, rect[1] - pad_y,
            rect[2] + pad_x, rect[3] + pad_y)


def _ink_bbox(page, glyph_bbox, margin=15.0):
    try:
        import numpy as np

        from .. import pdf as core_pdf
    except ImportError:
        return glyph_bbox

    search_rect = _display_bbox(page, _pad(glyph_bbox, margin))
    page_rect = _page_rect(page)
    clip = _intersect(search_rect, page_rect)
    if clip is None:
        return glyph_bbox

    try:
        pix = core_pdf.render_pixmap(page, dpi=150, clip=clip)
        if not pix.width or not pix.height or pix.n <= 0:
            return glyph_bbox
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n)
        gray = arr[:, :, :3].mean(axis=2) if pix.n >= 3 else arr[:, :, 0]
        dark_y, dark_x = np.where(gray < 220)
    except Exception:
        return glyph_bbox

    if len(dark_x) == 0:
        return glyph_bbox

    scale = 72.0 / 150.0
    display_ink = (
        clip[0] + dark_x.min() * scale,
        clip[1] + dark_y.min() * scale,
        clip[0] + dark_x.max() * scale,
        clip[1] + dark_y.max() * scale,
    )
    return _text_bbox(page, display_ink) or glyph_bbox


def sanitize_glyph_bbox(page, raw_bbox, font_size=12.0):
    """Fix degenerate glyph boxes from the text layer.

    Zero-width matras and line-spanning boxes are common in CID-keyed fonts.
    """
    rect = _rect(raw_bbox)
    if rect is None:
        return None

    x0, y0, x1, y1 = rect
    width = x1 - x0
    height = y1 - y0

    if width < 2.0:
        center_x = (x0 + x1) / 2.0
        center_y = (y0 + y1) / 2.0
        half_w = max(font_size * 0.4, 4.0)
        half_h = max(font_size * 0.5, 5.0)
        x0, x1 = center_x - half_w, center_x + half_w
        y0, y1 = center_y - half_h, center_y + half_h
    elif height > font_size * 2.5 and width < font_size:
        center_y = (y0 + y1) / 2.0
        y0 = center_y - font_size * 0.6
        y1 = center_y + font_size * 0.6

    rect = _rect((x0, y0, x1, y1))
    if rect is None:
        return None
    if rect[2] - rect[0] < 1.0 or rect[3] - rect[1] < 1.0:
        return _ink_bbox(page, rect)
    return rect


def _limit_dpi(rect, dpi, max_pixels):
    width = max(rect[2] - rect[0], 1e-6)
    height = max(rect[3] - rect[1], 1e-6)
    scale = max(int(dpi), 1) / 72.0
    if width * height * scale * scale <= max_pixels:
        return max(int(dpi), 1)
    max_scale = math.sqrt(max_pixels / (width * height))
    return max(1, min(int(dpi), int(max_scale * 72)))


def _render_region(page, rect, dpi, *, max_pixels=_MAX_PIXELS):
    from .. import pdf as core_pdf

    dpi = _limit_dpi(rect, dpi, max_pixels)
    pix = core_pdf.render_pixmap(page, dpi=dpi, clip=rect, rgb=True)
    if not pix.width or not pix.height:
        raise ValueError("empty crop")
    encoded = base64.b64encode(pix.tobytes("png")).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _glyph_render_rect(page, glyph_bbox):
    expanded = _expand_glyph_bbox(glyph_bbox)
    width = max(expanded[2] - expanded[0], 1.0)
    height = max(expanded[3] - expanded[1], 1.0)
    pad_h = max(height * 0.08, 1.0)
    pad_w = max(width * 0.12, pad_h)
    text_clip = (expanded[0] - pad_w, expanded[1] - pad_h,
                 expanded[2] + pad_w, expanded[3] + pad_h)

    clip = _intersect(_display_bbox(page, text_clip), _page_rect(page))
    if clip is None:
        return None, None
    long_side = max(clip[2] - clip[0], clip[3] - clip[1], 1e-6)
    target = int(round((_GLYPH_TARGET_PX / long_side) * 72))
    dpi = max(_GLYPH_DPI_MIN, min(target, _GLYPH_DPI_MAX))
    return clip, dpi


def _word_render_rect(page, word_bbox, margin):
    display = _display_bbox(page, word_bbox)
    if display is None:
        return None, None
    clip = _intersect(_pad(display, margin), _page_rect(page))
    return clip, display


def _overlay(crop_rect, glyph_rect):
    inner = _intersect(crop_rect, glyph_rect)
    if inner is None:
        return None
    width = max(crop_rect[2] - crop_rect[0], 1e-6)
    height = max(crop_rect[3] - crop_rect[1], 1e-6)
    return {
        "left": f"{(inner[0] - crop_rect[0]) / width * 100:.2f}%",
        "top": f"{(inner[1] - crop_rect[1]) / height * 100:.2f}%",
        "width": f"{(inner[2] - inner[0]) / width * 100:.2f}%",
        "height": f"{(inner[3] - inner[1]) / height * 100:.2f}%",
    }


def _page(doc, page_no):
    try:
        index = int(page_no)
    except (TypeError, ValueError):
        return None
    if index < 1:
        return None
    try:
        return doc[index - 1]
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def _same_page(a, b):
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return a == b


def render_review_crop(doc, *, word=None, glyph=None, word_dpi=WORD_DPI,
                       word_margin=WORD_MARGIN, sanitize_glyph=True,
                       max_pixels=_MAX_PIXELS) -> ReviewCrop:
    """Render a word crop with its glyph region, plus the glyph close-up.

    ``word`` and ``glyph`` are ``(page_no, bbox)`` pairs in text space. They may
    point at different pages; the overlay is only drawn when both share a page.
    """
    glyph_src = word_src = overlay = None
    glyph_page_no = None
    glyph_text = None

    if glyph is not None:
        glyph_page_no, glyph_bbox = glyph
        page = _page(doc, glyph_page_no)
        if page is not None and glyph_bbox is not None:
            try:
                glyph_text = (sanitize_glyph_bbox(page, glyph_bbox)
                              if sanitize_glyph else _rect(glyph_bbox))
                if glyph_text is not None:
                    clip, dpi = _glyph_render_rect(page, glyph_text)
                    if clip is not None:
                        glyph_src = _render_region(
                            page, clip, dpi, max_pixels=max_pixels)
            except Exception as exc:
                _LOG.warning("glyph crop failed on page %s: %s",
                             glyph_page_no, exc)

    if word is not None:
        word_page_no, word_bbox = word
        page = _page(doc, word_page_no)
        if page is not None and word_bbox is not None:
            try:
                clip, display = _word_render_rect(
                    page, word_bbox, word_margin)
                if clip is not None:
                    word_src = _render_region(
                        page, clip, word_dpi, max_pixels=max_pixels)
                    if (glyph_text is not None
                            and _same_page(word_page_no, glyph_page_no)):
                        overlay = _overlay(
                            clip, _display_bbox(page, glyph_text))
            except Exception as exc:
                _LOG.warning("word crop failed on page %s: %s",
                             word_page_no, exc)

    return ReviewCrop(glyph=glyph_src, word=word_src, overlay=overlay)
