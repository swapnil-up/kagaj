"""Read-only font diagnostics for legacy and hybrid PDFs.

``probe`` reports, per font subset, how much of the observed text the ToUnicode
CMap covers, which character classes appear, and which CIDs are unknown. It does
not write mappings or change decode behaviour.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .classify import char_class
from .decode import glyphs as extract_glyphs, is_unknown
from .embedded import EmbeddedFontCache
from .fingerprint import font_signature, subset_signature
from .fonts import FontResolutionError, cmap_mapping


def _new_font(font_id, base_font, font_xref, scheme):
    return {
        "font_id": font_id,
        "base_font": base_font,
        "font_xref": font_xref,
        "font_id_scheme": scheme,
        "observed": 0,
        "known": 0,
        "unknown": 0,
        "classes": Counter(),
        "unknown_cids": defaultdict(lambda: {"count": 0, "pages": set()}),
    }


def _fingerprints(font, embedded):
    xref = font.get("font_xref")
    if not xref:
        return None, None
    try:
        cache = embedded.get(xref)
        if cache is None:
            return None, None
        return subset_signature(cache.font), font_signature(
            cache.font, font.get("base_font") or "")
    except Exception:
        return None, None


def _candidates(reference, embedded, xref, cid):
    if reference is None or embedded is None or not xref:
        return []
    shape = embedded.shape(xref, cid)
    return [
        {"value": match.value, "glyph": match.glyph,
         "score": round(match.score, 3), "detail": match.detail}
        for match in reference.suggest(shape)
    ]


def probe_document(doc, *, max_pages=None, reference_font=None,
                   registry=None) -> dict:
    """Scan a PDF once and return per-font diagnostics."""
    if reference_font:
        from .reference import ReferenceIndex
        reference = ReferenceIndex.from_path(reference_font)
    else:
        reference = None
    embedded = EmbeddedFontCache(doc)

    fonts: dict[str, dict] = {}
    issues = []
    pages = range(len(doc)) if max_pages is None else range(
        min(max_pages, len(doc)))
    scanned = 0
    for pn in pages:
        page = doc[pn]
        try:
            page_glyphs = extract_glyphs(page, dedup=True)
        except FontResolutionError as exc:
            issues.append({"page": pn + 1, "kind": type(exc).__name__,
                           "message": str(exc)})
            continue
        scanned += 1
        for glyph in page_glyphs:
            font_id = (glyph.get("font_id") or glyph.get("font")
                       or "default")
            record = fonts.get(font_id)
            if record is None:
                record = fonts[font_id] = _new_font(
                    font_id,
                    glyph.get("base_font") or font_id,
                    glyph.get("font_xref"),
                    glyph.get("font_id_scheme") or "unresolved",
                )
            char = glyph.get("c") or ""
            record["observed"] += 1
            record["classes"][char_class(char)] += 1
            if is_unknown(char):
                record["unknown"] += 1
                cid = glyph.get("cid")
                entry = record["unknown_cids"][cid]
                entry["count"] += 1
                entry["pages"].add(pn + 1)
            else:
                record["known"] += 1

    out = []
    for font_id in sorted(fonts):
        record = fonts[font_id]
        total = record["observed"]
        unknown = record["unknown"]
        mapping = None
        if record.get("font_xref"):
            mapping = cmap_mapping(doc, record["font_xref"])
        subset_sig = family_sig = None
        if unknown:
            subset_sig, family_sig = _fingerprints(record, embedded)
        unknown_cids = []
        candidates = {}
        for cid in sorted(record["unknown_cids"]):
            entry = record["unknown_cids"][cid]
            unknown_cids.append({
                "cid": cid,
                "count": entry["count"],
                "pages": sorted(entry["pages"]),
            })
            if reference is not None:
                found = _candidates(reference, embedded,
                                    record.get("font_xref"), cid)
                if found:
                    candidates[str(cid)] = found
        if registry is not None and record.get("font_xref"):
            from . import registry as registry_mod
            from .fingerprint import glyph_fingerprint

            embedded_font = embedded.get(record["font_xref"])
            if embedded_font is not None:
                try:
                    family = font_signature(
                        embedded_font.font, record["base_font"] or "")
                    for row in unknown_cids:
                        cid = row["cid"]
                        if cid < 0 or cid >= len(embedded_font.order):
                            continue
                        fingerprint = glyph_fingerprint(
                            embedded_font.glyph_set, embedded_font.order[cid],
                            embedded_font.hmtx, embedded_font.upm)
                        entry = registry_mod.lookup(
                            registry, family.family_hash,
                            fingerprint.outline_hash)
                        if entry:
                            row["registry"] = {
                                "value": entry.get("value") or "",
                                "status": entry.get("status") or "",
                                "support": entry.get("support") or 0,
                                "values": entry.get("values") or [],
                            }
                except Exception:
                    pass
        out.append({
            "font_id": font_id,
            "base_font": record["base_font"],
            "font_xref": record["font_xref"],
            "font_id_scheme": record["font_id_scheme"],
            "observed": total,
            "known": total - unknown,
            "unknown": unknown,
            "coverage": round((total - unknown) / total, 4) if total else 0.0,
            "classes": dict(sorted(record["classes"].items())),
            "cmap_entries": len(mapping) if mapping is not None else 0,
            "glyph_count": (family_sig.glyph_count if family_sig else None),
            "subset_signature": subset_sig,
            "font_signature": (family_sig.as_dict() if family_sig else None),
            "unknown_cids": unknown_cids,
            "candidates": candidates,
        })

    return {
        "pdf": getattr(doc, "name", "") or "",
        "pages_scanned": scanned,
        "issues": issues,
        "fonts": out,
    }


def format_probe(result: dict) -> str:
    """Render a human-readable probe summary."""
    lines = [
        f"PDF: {result.get('pdf') or '(unknown)'}",
        f"Pages scanned: {result.get('pages_scanned', 0)} \u00b7 "
        f"fonts: {len(result.get('fonts', []))}",
    ]
    if result.get("issues"):
        pages = ", ".join(f"p{issue['page']}" for issue in result["issues"])
        lines.append(f"Skipped pages: {pages}")
        lines.append(f"  {result['issues'][0]['message']}")
    for font in result.get("fonts", []):
        lines.append("")
        lines.append(
            f"[{font['font_id']}] {font['base_font']} \u00b7 "
            f"xref {font['font_xref']} \u00b7 {font['font_id_scheme']}")
        lines.append(
            f"  glyphs: observed={font['observed']} known={font['known']} "
            f"unknown={font['unknown']} coverage={font['coverage']:.1%}")
        lines.append(f"  cmap entries: {font['cmap_entries']}")
        classes = ", ".join(f"{name}={count}"
                            for name, count in font["classes"].items())
        lines.append(f"  classes: {classes or '-'}")
        signature = font.get("font_signature")
        if signature:
            lines.append(
                f"  font: {signature.get('family') or '?'} "
                f"{signature.get('style') or ''} \u00b7 "
                f"glyphs={signature.get('glyph_count')} "
                f"\u00b7 family={signature.get('family_hash', '')[:12]} "
                f"\u00b7 subset={font['subset_signature'][:12]}")
        if font["unknown_cids"]:
            shown = ", ".join(
                f"{row['cid']}\u00d7{row['count']}"
                for row in font["unknown_cids"][:12])
            if len(font["unknown_cids"]) > 12:
                shown += ", \u2026"
            lines.append(f"  unknown CIDs: {shown}")
        for cid, matches in font.get("candidates", {}).items():
            values = ", ".join(
                f"{match['value']} ({match['glyph']}, "
                f"{match['score']:.1f})" for match in matches)
            lines.append(f"    cid {cid}: {values}")
        for row in font.get("unknown_cids", []):
            entry = row.get("registry")
            if entry:
                lines.append(
                    f"    cid {row['cid']}: registry "
                    f"{entry.get('value') or '(conflict)'} "
                    f"({entry.get('status')}, "
                    f"{entry.get('support')} doc)")
    return "\n".join(lines)
