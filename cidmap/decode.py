"""Text-layer decode: per-glyph census of unmapped CIDs, scoped by font_id.

PyMuPDF decodes ~95% of redbook glyphs via each font subset's ToUnicode CMap.
Unmapped CIDs fall through to Identity-H -> control chars / \\ufffd / ASCII
artifacts. This module finds those glyphs and records, per (font_id, cid):

  - occurrence count,
  - pages,
  - the logical-order window around each occurrence (context), and
  - a representative position (bbox) for OCR cross-check / crop rendering.

Font identity comes from :mod:`cidmap.fonts`: a ToUnicode CMap hash when
available, otherwise a PDF-local source hash plus font xref. Texttrace only
reports the BaseFont name (``Kalimati``), which is shared by every subset and is
therefore unusable as a scoping key on its own.
"""

from __future__ import annotations

from collections import defaultdict

from .fonts import (
    FontIdentity,
    FontResolutionError,
    lookup_identity,
    page_fonts,
)

# Unmapped-CID fallthrough signatures from texttrace.
_CONTROL = {c for c in range(0x20)}
_ASCII_ARTIFACTS = set("><@^3B;,:=\"`")


def is_unknown(char: str) -> bool:
    """True when PyMuPDF's decoded char is the Identity-H fallthrough artifact."""
    if not char:
        return True
    code = ord(char)
    if code == 0xFFFD:  # U+FFFD replacement char = CID absent from ToUnicode
        return True
    if code in _CONTROL or code == 0x7F:
        return True
    if char in _ASCII_ARTIFACTS:
        return True
    return False


def _font_lookup(page):
    wanted = {span["font"] for span in page.get_texttrace()}
    if getattr(page, "parent", None) is None:
        def unresolved(base: str) -> FontIdentity:
            return FontIdentity(base, base, None, "unresolved")
        return unresolved
    fonts = page_fonts(page, wanted=wanted)
    resolved = {}

    def identity(base: str) -> FontIdentity:
        if base not in resolved:
            resolved[base] = lookup_identity(fonts, base)
        return resolved[base]

    return identity


def _glyph_record(identity: FontIdentity, cid, char, origin, bbox):
    return {
        "cid": cid,
        "c": char,
        "font": identity.base_font,
        "base_font": identity.base_font,
        "font_id": identity.font_id,
        "font_xref": identity.font_xref,
        "font_id_scheme": identity.font_id_scheme,
        "origin": origin,
        "bbox": bbox,
    }


def glyphs(page, dedup=True) -> list[dict]:
    """Per-glyph records with a stable ``font_id`` plus legacy font metadata.

    ``dedup`` merges glyphs the text layer draws twice at ~the same spot
    (same font_id and CID within X_TOL pt).

    Falls back to span-level bbox division when per-glyph chars are absent.
    """
    identity = _font_lookup(page)
    out = []
    for span in page.get_texttrace():
        font = span["font"]
        info = identity(font)
        chars = span.get("chars", [])
        if chars:
            for (u, glyph, origin, bbox) in chars:
                out.append(_glyph_record(
                    info, glyph, chr(u) if u else "", origin, bbox))
        else:
            sb = span["bbox"]
            text = span.get("text", "")
            n_chars = max(len(text), 1)
            span_w = (sb[2] - sb[0]) / n_chars
            for idx, ch in enumerate(text):
                origin = (sb[0] + idx * span_w, sb[1])
                char_x0 = sb[0] + idx * span_w
                char_x1 = char_x0 + span_w
                out.append(_glyph_record(
                    info, 0, ch, origin,
                    (char_x0, sb[1], char_x1, sb[3])))
    if not dedup:
        return out
    seen = set()
    deduped = []
    for g in out:
        key = (g["font_id"], g["cid"], round(g["origin"][1]),
               round(g["origin"][0]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(g)
    return deduped


def cluster_lines(glyphs, y_gap=3.0) -> list[list[dict]]:
    if not glyphs:
        return []
    ordered = sorted(glyphs, key=lambda g: (round(g["origin"][1], 1),
                                            g["origin"][0]))
    lines = [[ordered[0]]]
    prev_y = ordered[0]["origin"][1]
    for g in ordered[1:]:
        if abs(g["origin"][1] - prev_y) > y_gap:
            lines.append([])
        lines[-1].append(g)
        prev_y = g["origin"][1]
    return lines


def _marker(g) -> str:
    return f"⟦{g['cid']}⟧" if is_unknown(g["c"]) else g["c"]


def census(doc, max_pages=None, issues=None) -> dict:
    """Scan pages; return {font_id: {cid: record}} for unknown glyphs.

    ``issues`` optionally collects page-level font-resolution failures instead
    of aborting the whole scan.

    Record keys: count, pages (list), contexts (list of window strings),
    samples (list of {page, bbox} for OCR / render).
    """
    out: dict[str, dict[int, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0, "pages": [], "contexts": [],
                                     "samples": []}))
    pages = range(len(doc)) if max_pages is None else range(
        min(max_pages, len(doc)))
    for pn in pages:
        page = doc[pn]
        try:
            page_glyphs = glyphs(page)
        except FontResolutionError as exc:
            if issues is None:
                raise
            issues.append({"page": pn + 1, "kind": type(exc).__name__,
                           "message": str(exc)})
            continue
        for line in cluster_lines(page_glyphs):
            for i, g in enumerate(line):
                if not is_unknown(g["c"]):
                    continue
                font = g["font_id"] or ""
                rec = out[font][g["cid"]]
                rec["count"] += 1
                rec["pages"].append(pn + 1)
                lo = max(0, i - 3)
                hi = min(len(line), i + 4)
                ctx = "".join(_marker(x) for x in line[lo:hi])
                if ctx not in rec["contexts"] and len(rec["contexts"]) < 8:
                    rec["contexts"].append(ctx)
                if len(rec["samples"]) < 3:
                    rec["samples"].append({
                        "page": pn + 1, "bbox": g["bbox"],
                        "font_id": g["font_id"],
                        "base_font": g["base_font"],
                        "font_xref": g["font_xref"],
                        "font_id_scheme": g["font_id_scheme"],
                    })
    # dedup pages
    for font in out:
        for cid in out[font]:
            rec = out[font][cid]
            rec["pages"] = sorted(set(rec["pages"]))
            rec["range"] = f"p{rec['pages'][0]}–p{rec['pages'][-1]}"
    return {f: dict(m) for f, m in out.items()}


def flatten(census_result: dict) -> list[dict]:
    """Flatten to rows keyed by (font_id, cid) for review."""
    rows = []
    for font_id, cids in census_result.items():
        for cid, rec in sorted(cids.items()):
            rows.append({"key": f"{font_id}╱{cid}", "font": font_id,
                         "font_id": font_id, "cid": cid, **rec})
    return rows