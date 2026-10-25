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
    FontAmbiguity,
    FontIdentity,
    FontResolutionError,
    lookup_identity,
    page_fonts,
    usable_cmap_mapping,
)

# Unmapped-CID fallthrough signatures from texttrace.
_CONTROL = {c for c in range(0x20)}
_ASCII_ARTIFACTS = set("><@^3B;,:=\"`")
_SIMPLE_SUBTYPES = frozenset({"Type1", "TrueType", "Type3", "MMType1"})
_SIMPLE_ENCODINGS = frozenset({
    "/WinAnsiEncoding", "/MacRomanEncoding", "/StandardEncoding",
    "/MacExpertEncoding",
})


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


def _same_base(left: str, right: str) -> bool:
    return left == right or left.split("+")[-1] == right.split("+")[-1]


def _font_lookup(page, *, allow_ambiguous: bool = False):
    wanted = {span["font"] for span in page.get_texttrace()}
    if getattr(page, "parent", None) is None:
        def unresolved(base: str) -> FontIdentity:
            return FontIdentity(base, base, None, "unresolved")
        return unresolved, {}
    ambiguous: dict[str, list[int]] = {}
    fonts = page_fonts(
        page,
        wanted=wanted,
        skip_ambiguous=allow_ambiguous,
        ambiguous=ambiguous if allow_ambiguous else None,
    )
    resolved = {}

    def identity(base: str) -> FontIdentity | FontResolutionError:
        if base not in resolved:
            xrefs = next(
                (value for name, value in ambiguous.items()
                 if _same_base(name, base)),
                None,
            )
            if xrefs is not None:
                resolved[base] = FontAmbiguity(base, xrefs)
            else:
                try:
                    resolved[base] = lookup_identity(fonts, base)
                except FontResolutionError as exc:
                    if not allow_ambiguous:
                        raise
                    resolved[base] = exc
        return resolved[base]

    return identity, ambiguous


def _glyph_record(identity: FontIdentity, cid, char, origin, bbox,
                  mapped=False, simple_font=False, direction=None):
    return {
        "cid": cid,
        "c": char,
        "font": identity.base_font,
        "base_font": identity.base_font,
        "font_id": identity.font_id,
        "font_xref": identity.font_xref,
        "font_id_scheme": identity.font_id_scheme,
        "mapped": bool(mapped),
        "simple_font": bool(simple_font),
        "origin": origin,
        "bbox": bbox,
        "dir": direction,
    }


def glyphs(page, dedup=True, *, allow_ambiguous=False,
           issues=None) -> list[dict]:
    """Per-glyph records with a stable ``font_id`` plus legacy font metadata.

    ``dedup`` merges glyphs the text layer draws twice at ~the same spot
    (same font_id and CID within X_TOL pt). With ``allow_ambiguous``, spans
    from duplicate BaseFont resources are skipped and reported in ``issues``
    instead of aborting the whole page.

    Falls back to span-level bbox division when per-glyph chars are absent.
    """
    identity, _ = _font_lookup(page, allow_ambiguous=allow_ambiguous)
    parent = getattr(page, "parent", None)
    cmap_cache = {}
    simple_cache = {}

    def simple(font_xref):
        if parent is None or font_xref is None:
            return False
        if font_xref not in simple_cache:
            try:
                _, subtype = parent.xref_get_key(font_xref, "Subtype")
                kind, encoding = parent.xref_get_key(font_xref, "Encoding")
            except Exception:
                subtype = encoding = None
                kind = None
            simple_cache[font_xref] = (
                str(subtype).lstrip("/") in _SIMPLE_SUBTYPES
                and kind == "name"
                and encoding in _SIMPLE_ENCODINGS
            )
        return simple_cache[font_xref]

    def mapped(font_xref, cid, char):
        if parent is None or font_xref is None:
            return False
        if font_xref not in cmap_cache:
            cmap_cache[font_xref] = usable_cmap_mapping(parent, font_xref)
        mapping = cmap_cache[font_xref]
        if not mapping or cid not in mapping:
            return False
        return char == "".join(chr(cp) for cp in mapping[cid])

    out = []
    reported = set()
    for span in page.get_texttrace():
        font = span["font"]
        info = identity(font)
        if isinstance(info, FontResolutionError):
            key = (type(info).__name__, font)
            if issues is not None and key not in reported:
                reported.add(key)
                issues.append({
                    "kind": type(info).__name__,
                    "message": str(info),
                })
            continue
        chars = span.get("chars", [])
        if chars:
            for (u, glyph, origin, bbox) in chars:
                out.append(_glyph_record(
                    info, glyph, chr(u) if u else "", origin, bbox,
                    mapped=mapped(info.font_xref, glyph, chr(u) if u else ""),
                    simple_font=simple(info.font_xref),
                    direction=span.get("dir")))
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
                    (char_x0, sb[1], char_x1, sb[3]),
                    direction=span.get("dir")))
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


_ORDER_BUCKET = 2.0


def _bucket(value: float) -> int:
    return int(value / _ORDER_BUCKET)


def _segments(line, x_gap: float) -> list[list[dict]]:
    indexed = list(enumerate(line))
    ordered = [
        glyph for _, glyph in sorted(
            indexed,
            key=lambda item: (_bucket(item[1]["origin"][0]), item[0]))
    ]
    segments = [[ordered[0]]]
    previous = ordered[0]["origin"][0]
    for glyph in ordered[1:]:
        current = glyph["origin"][0]
        if current - previous > x_gap:
            segments.append([])
        segments[-1].append(glyph)
        previous = current
    return segments


def layout_lines(lines, x_gap: float = 24.0,
                 y_gap: float = 20.0) -> list[list[dict]]:
    """Split lines into multi-column blocks, then read each block by column.

    Consecutive lines sharing the same wide gap are treated as columns. Short
    lines that fit entirely inside one column (such as a caption ending after
    two lines) stay in that column. Lines without a wide gap are unchanged.
    """
    out = []
    index = 0
    while index < len(lines):
        segments = _segments(lines[index], x_gap)
        if len(segments) < 2:
            out.append(lines[index])
            index += 1
            continue
        boundaries = [
            (left[-1]["origin"][0] + right[0]["origin"][0]) / 2
            for left, right in zip(segments, segments[1:])
        ]
        block = [index]
        cursor = index + 1
        while cursor < len(lines):
            previous_y = lines[cursor - 1][0]["origin"][1]
            current_y = lines[cursor][0]["origin"][1]
            if current_y - previous_y > y_gap:
                break
            current = _segments(lines[cursor], x_gap)
            if len(current) > len(boundaries) + 1:
                break
            crosses = any(
                any(g["origin"][0] < boundary for g in segment)
                and any(g["origin"][0] >= boundary for g in segment)
                for segment in current
                for boundary in boundaries
            )
            if crosses:
                break
            block.append(cursor)
            cursor += 1
        if len(block) < 2:
            out.append(lines[index])
            index += 1
            continue
        columns = [[] for _ in range(len(boundaries) + 1)]
        for line_index in block:
            for segment in _segments(lines[line_index], x_gap):
                midpoint = (segment[0]["origin"][0]
                            + segment[-1]["origin"][0]) / 2
                column = sum(midpoint >= boundary for boundary in boundaries)
                columns[column].append(segment)
        for column in columns:
            out.extend(sorted(column, key=lambda seg: seg[0]["origin"][1]))
        index = cursor
    return out


def _vertical(glyph) -> bool:
    dx, dy = glyph.get("dir") or (1.0, 0.0)
    return abs(dy) > abs(dx)


def _cluster(glyphs, axis: int, gap: float) -> list[list[dict]]:
    indexed = list(enumerate(glyphs))
    order = {id(glyph): position for position, glyph in indexed}
    ordered = [
        glyph for _, glyph in sorted(
            indexed,
            key=lambda item: (round(item[1]["origin"][axis], 1), item[0]))
    ]
    lines = [[ordered[0]]]
    previous = ordered[0]["origin"][axis]
    for glyph in ordered[1:]:
        current = glyph["origin"][axis]
        if abs(current - previous) > gap:
            lines.append([])
        lines[-1].append(glyph)
        previous = current
    for line in lines:
        line.sort(key=lambda glyph: (_bucket(glyph["origin"][1 - axis]),
                                     order[id(glyph)]))
    return lines


def cluster_lines(glyphs, y_gap=3.0) -> list[list[dict]]:
    if not glyphs:
        return []
    horizontal = [glyph for glyph in glyphs if not _vertical(glyph)]
    vertical = [glyph for glyph in glyphs if _vertical(glyph)]
    lines = []
    if horizontal:
        lines.extend(_cluster(horizontal, 1, y_gap))
    if vertical:
        lines.extend(_cluster(vertical, 0, y_gap))
    return lines


def is_unknown_glyph(g: dict) -> bool:
    if g.get("mapped"):
        return False
    char = g.get("c") or ""
    if (g.get("simple_font") and char and char.isprintable()
            and char != "\ufffd"):
        return False
    return is_unknown(char)


def _marker(g) -> str:
    return f"⟦{g['cid']}⟧" if is_unknown_glyph(g) else g["c"]


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
                if not is_unknown_glyph(g):
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