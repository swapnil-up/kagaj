"""Extract and cache embedded subset fonts from an open PDF document."""

from __future__ import annotations

import io
import logging
from contextlib import contextmanager

from fontTools.ttLib import TTFont

from .shape import GlyphShape, glyph_shape

_LOG = logging.getLogger(__name__)
_HEAD_LOG = logging.getLogger("fontTools.ttLib.tables._h_e_a_d")


@contextmanager
def quiet_fonttools():
    previous = _HEAD_LOG.level
    _HEAD_LOG.setLevel(logging.ERROR)
    try:
        yield
    finally:
        _HEAD_LOG.setLevel(previous)


class EmbeddedFont:
    def __init__(self, font: TTFont):
        self.font = font
        self.glyph_set = font.getGlyphSet()
        self.order = font.getGlyphOrder()
        self.hmtx = font["hmtx"]
        self.upm = font["head"].unitsPerEm

    def shape(self, cid: int) -> GlyphShape | None:
        if cid < 0 or cid >= len(self.order):
            return None
        return glyph_shape(self.glyph_set, self.order[cid], self.hmtx, self.upm)


class EmbeddedFontCache:
    """Extract and cache subset fonts from one open PDF document."""

    def __init__(self, doc):
        self.doc = doc
        self._fonts: dict[int, EmbeddedFont | None] = {}

    def get(self, xref) -> EmbeddedFont | None:
        if not xref:
            return None
        if xref not in self._fonts:
            try:
                info = self.doc.extract_font(int(xref))
                data = info[3]
                with quiet_fonttools():
                    font = TTFont(io.BytesIO(data), fontNumber=0, lazy=False)
                    self._fonts[xref] = EmbeddedFont(font)
            except Exception:
                _LOG.debug("font extraction failed for xref %s", xref,
                           exc_info=True)
                self._fonts[xref] = None
        return self._fonts[xref]

    def shape(self, xref, cid: int) -> GlyphShape | None:
        embedded = self.get(xref)
        return embedded.shape(cid) if embedded else None
