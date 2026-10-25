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

from . import legacy as legacy_fonts
from .decode import cluster_lines, glyphs, is_unknown_glyph, layout_lines
from .mappings import get_value


def decode_page(page, store, dedup=True, legacy=True,
                issues=None) -> str:
    """Decode one page to Devanagari text (reading order, newline per line).

    Legacy 8-bit spans are decoded deterministically before per-glyph store
    lookup.  Unsupported legacy families are left unchanged so their raw bytes
    remain visible instead of being silently reinterpreted.

    Spans whose BaseFont maps to several resources are skipped and reported in
    ``issues`` rather than aborting the page.
    """
    page_glyphs = glyphs(page, dedup=dedup, allow_ambiguous=True,
                         issues=issues)
    out = []
    for line in layout_lines(cluster_lines(page_glyphs)):
        out.append(_decode_line(line, store, legacy))
    return "\n".join(out)


def _legacy_family(glyph: dict) -> str | None:
    return legacy_fonts.family(
        glyph.get("base_font") or glyph.get("font") or "")


def _decode_line(line, store, legacy=True) -> str:
    if not legacy:
        return "".join(_resolve(glyph, store) for glyph in line)
    out = []
    index = 0
    while index < len(line):
        glyph = line[index]
        family = _legacy_family(glyph)
        if family and legacy_fonts.supported(family):
            end = index + 1
            while end < len(line) and _legacy_family(line[end]) == family:
                end += 1
            run = line[index:end]
            if legacy_fonts.table_family(family):
                decoded = legacy_fonts.decode_cids(
                    [item["cid"] for item in run], family)
                fallback = "".join(_resolve(item, store) for item in run)
            else:
                text = "".join(item.get("c") or "" for item in run)
                decoded = legacy_fonts.decode(text, family)
                fallback = text
            out.append(decoded if decoded is not None else fallback)
            index = end
            continue
        out.append(_resolve(glyph, store))
        index += 1
    return "".join(out)


def _resolve(g: dict, store: dict) -> str:
    c = g["c"]
    if c and not is_unknown_glyph(g):
        return c
    font = g["font_id"] or ""
    v = get_value(store, font, g["cid"])
    if v:
        return v
    return f"\u27e6cid:{g['cid']}\u27e7"


def decode_doc(doc, store, max_pages=None, dedup=True, log=None,
               legacy=True, issues=None) -> list[str]:
    """Decode a document; return one Devanagari string per page."""
    pages = range(len(doc)) if max_pages is None else range(
        min(max_pages, len(doc)))
    out = []
    for pn in pages:
        page = doc[pn]
        page_issues = []
        text = decode_page(page, store, dedup=dedup, legacy=legacy,
                           issues=page_issues)
        for issue in page_issues:
            issue["page"] = pn + 1
        if issues is not None:
            issues.extend(page_issues)
        out.append(text)
        if log:
            n_unk = text.count("\u27e6cid:")
            log(f"  p{pn + 1}: {len(text)} chars, {n_unk} unmapped"
                + (f", {len(page_issues)} font issue(s)"
                   if page_issues else ""))
    return out


def coverage(text: str) -> tuple[int, int]:
    """(mapped, unmapped) glyph counts from a decoded page string."""
    import re
    mapped = re.sub(r"\u27e6cid:\d+\u27e7", "", text)
    return len(mapped.replace("\n", "")), len(re.findall(
        r"\u27e6cid:\d+\u27e7", text))
