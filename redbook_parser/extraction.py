"""Page text / glyph extraction via PyMuPDF (imported lazily).

Glyph extraction and line clustering are delegated to ``cidmap.decode`` — the
single source of truth for texttrace-based glyph extraction. This module
re-exports them for backward compatibility and adds ``extract_page_text``
(redbook-specific flat text extraction).

SPIKE RESULT (validated on Type0/Identity-H notice PDFs, PyMuPDF 1.28):

- ``page.get_texttrace()`` returns span dicts with the **BaseFont name** (not
  the subset resource name) and a ``chars`` tuple of per-glyph
  ``(unicode, glyph_id, origin, bbox)``. ``cidmap.fonts`` resolves the actual
  font resource and gives each glyph a stable ``font_id``.
- For unmapped CIDs the ``unicode`` is ``U+FFFD`` and ``glyph_id`` IS the CID.
  ``rawdict``/``get_text`` instead render ``chr(cid)`` fallbacks (control
  chars / ASCII artifacts) — the source of the old EXACT_FIXES table.
- bbox correlation between rawdict and texttrace FAILS (different bbox
  semantics: texttrace bbox is the glyph box, rawdict char bbox is a line
  box). Do not attempt it; texttrace alone is sufficient.
- Same CID maps to different glyphs in different font subsets, so decoding
  must be scoped by ``font_id`` + ``glyph_id`` (see ``cidmap.fonts``).
"""


def extract_page_text(doc, pno: int) -> str:
    """Extract flattened text from a single page (current v3 baseline)."""
    page = doc[pno]
    return page.get_text("text")


from cidmap.decode import glyphs as extract_glyphs, cluster_lines  # noqa: E402
