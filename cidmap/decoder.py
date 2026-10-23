"""Text-layer decoder: turn a PDF page into Devanagari using the canonical store.

This is the consumer side of ``cidmap`` — the piece a bill/verbatim pipeline
wires in to read CID-keyed fonts WITHOUT OCR. For each glyph from ``texttrace``:

  - a clean Unicode char (already ToUnicode-decoded) is kept verbatim,
  - an unknown glyph (control char / U+FFFD / ASCII artifact) is resolved via
    ``mappings.get_value(store, font, cid)`` — font-scoped first, then CID
    fallback,
  - glyphs that stay unmapped are rendered as a visible ``⟦cid:N⟧`` marker so
    coverage is auditable and the number of markers is the decode failure count.

The store is loaded once per document; ``decode_doc`` returns per-page text.
"""

from __future__ import annotations

from .decode import cluster_lines, glyphs, is_unknown
from .mappings import get_value


def decode_page(page, store, dedup=True) -> str:
    """Decode one page to Devanagari text (reading order, newline per line)."""
    out = []
    for line in cluster_lines(glyphs(page, dedup=dedup)):
        out.append("".join(_resolve(g, store) for g in line))
    return "\n".join(out)


def _resolve(g: dict, store: dict) -> str:
    c = g["c"]
    if c and not is_unknown(c):
        return c
    font = g["font_id"] or ""
    v = get_value(store, font, g["cid"])
    if v:
        return v
    return f"\u27e6cid:{g['cid']}\u27e7"


def decode_doc(doc, store, max_pages=None, dedup=True, log=None) -> list[str]:
    """Decode a document; return one Devanagari string per page."""
    pages = range(len(doc)) if max_pages is None else range(
        min(max_pages, len(doc)))
    out = []
    for pn in pages:
        page = doc[pn]
        text = decode_page(page, store, dedup=dedup)
        out.append(text)
        if log:
            n_unk = text.count("\u27e6cid:")
            log(f"  p{pn + 1}: {len(text)} chars, {n_unk} unmapped")
    return out


def coverage(text: str) -> tuple[int, int]:
    """(mapped, unmapped) glyph counts from a decoded page string."""
    import re
    mapped = re.sub(r"\u27e6cid:\d+\u27e7", "", text)
    return len(mapped.replace("\n", "")), len(re.findall(
        r"\u27e6cid:\d+\u27e7", text))
