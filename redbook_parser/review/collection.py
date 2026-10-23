"""Backward-compatible alias for :mod:`cidmap.glyph_collection`."""

import sys

from cidmap import glyph_collection as _impl

sys.modules[__name__] = _impl
