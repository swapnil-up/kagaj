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
from .embedded import EmbeddedFontCache
from .legacy_identify import (
    LegacyIdentity,
    LegacyReferenceIndex,
    identify_font,
)
from .mappings import get_value


def decode_page(page, store, dedup=True, legacy=True,
                issues=None, embedded=None, references=None,
                identities=None) -> str:
    """Decode one page to Devanagari text (reading order, newline per line).

    Legacy 8-bit spans are decoded deterministically before per-glyph store
    lookup.  Unsupported legacy families are left unchanged so their raw bytes
    remain visible instead of being silently reinterpreted.

    Spans whose BaseFont maps to several resources are skipped and reported in
    ``issues`` rather than aborting the page.
    """
    if identities is None:
        identities = {}
    if embedded is None and getattr(page, "parent", None) is not None:
        embedded = EmbeddedFontCache(page.parent)
    page_glyphs = glyphs(page, dedup=dedup, allow_ambiguous=True,
                         issues=issues)
    out = []
    for line in layout_lines(cluster_lines(page_glyphs)):
        out.append(_decode_line(
            line, store, legacy, identities, embedded, references))
    return "\n".join(out)


def _legacy_identity(glyph: dict, identities: dict, embedded,
                     references) -> LegacyIdentity:
    key = (glyph.get("font_xref"),
           glyph.get("base_font") or glyph.get("font") or "")
    found = identities.get(key)
    if found is not None:
        return found
    font = None
    xref = glyph.get("font_xref")
    if embedded is not None and xref:
        cached = embedded.get(xref)
        if cached is not None:
            font = cached.font
    found = identify_font(
        key[1], font, simple=glyph.get("simple_font"),
        references=references)
    identities[key] = found
    return found


def _decode_line(line, store, legacy=True, identities=None,
                 embedded=None, references=None) -> str:
    if not legacy:
        return "".join(_resolve(glyph, store) for glyph in line)
    if identities is None:
        identities = {}
    out = []
    index = 0
    while index < len(line):
        glyph = line[index]
        identity = _legacy_identity(
            glyph, identities, embedded, references)
        family = identity.family
        if family and identity.supported:
            end = index + 1
            while end < len(line):
                other = _legacy_identity(
                    line[end], identities, embedded, references)
                if not (other.family == family and other.supported):
                    break
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
    embedded = EmbeddedFontCache(doc) if legacy and doc is not None else None
    references = LegacyReferenceIndex.from_local() if legacy else None
    identities = {}
    out = []
    for pn in pages:
        page = doc[pn]
        page_issues = []
        text = decode_page(
            page, store, dedup=dedup, legacy=legacy,
            issues=page_issues, embedded=embedded, references=references,
            identities=identities)
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
