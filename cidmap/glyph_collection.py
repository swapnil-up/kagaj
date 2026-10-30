"""Data collection: gather unknown-CID samples from a PDF in one pass.

Each page is extracted once and clustered once. The same line data feeds the
census (counts, pages, contexts), optional legacy hints, and the crop
samples, so review generation no longer rescans pages per glyph.
"""

import logging

from .decode import cluster_lines, glyphs as extract_glyphs
from .fonts import FontResolutionError
from kagaj_core import pdf as core_pdf
from kagaj_core.review.crops import sanitize_glyph_bbox

_LOG = logging.getLogger(__name__)

_WIN = 3  # context window (chars) on each side of the unknown glyph
_WORD_GAP = 2.0  # pt; larger gaps separate columns or words


def _ctx_str(line, i) -> str:
    """Word-window around glyph ``i`` using the census marker scheme."""
    lo = max(0, i - _WIN)
    hi = min(len(line), i + _WIN + 1)
    return "".join(
        f"⟦{g['cid']}⟧" if g["c"] == "\ufffd" else g["c"]
        for g in line[lo:hi])


def _word_bbox(line, i):
    """BBox of the contiguous visual word containing glyph ``i``.

    A page ``line`` from :func:`cluster_lines` can span several table columns
    because it is clustered only by baseline. Split on horizontal gaps so the
    crop is a word, not a slice of the whole row.
    """
    target = line[i]
    tbox = core_pdf.normalize_bbox(target["bbox"])
    tx = ((tbox[0] + tbox[2]) / 2.0 if tbox[2] - tbox[0] > 0.5
          else target["origin"][0])

    boxes = []
    for g in line:
        if g["c"].isspace():
            continue
        r = core_pdf.normalize_bbox(g["bbox"])
        if r[2] - r[0] > 0.5 and r[3] - r[1] > 0.5:
            boxes.append(r)
    if not boxes:
        return target["bbox"]
    boxes.sort(key=lambda r: (r[0], r[2]))

    clusters = []
    for rect in boxes:
        if clusters and rect[0] - clusters[-1][2] <= _WORD_GAP:
            clusters[-1][2] = max(clusters[-1][2], rect[2])
            clusters[-1][1] = min(clusters[-1][1], rect[1])
            clusters[-1][3] = max(clusters[-1][3], rect[3])
        else:
            clusters.append([rect[0], rect[1], rect[2], rect[3]])

    def contains(cluster):
        return cluster[0] - _WORD_GAP <= tx <= cluster[2] + _WORD_GAP

    chosen = next((c for c in clusters if contains(c)), None)
    if chosen is None:
        chosen = min(clusters, key=lambda c: min(abs(tx - c[0]),
                                                 abs(tx - c[2])))
    return tuple(chosen)


def _new_record(cid, font_id, base_font, font_xref, font_id_scheme,
                legacy_map=None):
    legacy_map = legacy_map or {}
    return {
        "count": 0,
        "pages": set(),
        "contexts": set(),
        "font_id": font_id,
        "base_font": base_font,
        "font_xref": font_xref,
        "font_id_scheme": font_id_scheme,
        "legacy_value": legacy_map.get(cid, ""),
        "has_legacy_value": cid in legacy_map,
        "samples": [],
    }


def collect_review_data(doc, max_samples_per_cid=1, issues=None,
                        legacy_map=None) -> dict:
    """Scan every page once and return ``{(font_id, cid): record}``.

    Each record holds ``count``, ``pages``, ``contexts``, font metadata and up
    to ``max_samples_per_cid`` distinct ``samples`` (deduplicated by page and
    font). Pages with ambiguous font resources are skipped and reported through
    ``issues`` (or logged when no list is supplied).
    """
    unknown: dict[tuple[str, int], dict] = {}
    for pn in range(len(doc)):
        page = doc[pn]
        try:
            glyphs = extract_glyphs(page, dedup=True)
        except FontResolutionError as exc:
            issue = {"page": pn + 1, "kind": type(exc).__name__,
                     "message": str(exc)}
            if issues is not None:
                issues.append(issue)
            else:
                _LOG.warning("page %s needs manual font resolution: %s",
                             pn + 1, exc)
            continue
        lines = cluster_lines(glyphs, y_gap=3.0)
        for line in lines:
            for i, g in enumerate(line):
                if g["c"] != "\ufffd":
                    continue
                cid = g["cid"]
                font_id = g.get("font_id") or g.get("font", "default")
                key = (font_id, cid)
                record = unknown.get(key)
                if record is None:
                    record = unknown[key] = _new_record(
                        cid, font_id, g.get("base_font", font_id),
                        g.get("font_xref"), g.get("font_id_scheme",
                                                "unresolved"),
                        legacy_map=legacy_map)

                record["count"] += 1
                record["pages"].add(pn + 1)
                ctx_text = _ctx_str(line, i)
                record["contexts"].add(ctx_text)

                if len(record["samples"]) >= max_samples_per_cid:
                    continue
                if any(s["page"] == pn + 1 and s.get("font_id") == font_id
                       for s in record["samples"]):
                    continue

                rect = core_pdf.normalize_bbox(g["bbox"])
                sanitized = sanitize_glyph_bbox(page, rect)
                srect = core_pdf.normalize_bbox(sanitized)
                if srect[2] - srect[0] <= 0 or srect[3] - srect[1] <= 0:
                    continue

                record["samples"].append({
                    "page": pn + 1,
                    "font_id": font_id,
                    "base_font": record["base_font"],
                    "bbox": _word_bbox(line, i),
                    "glyph_bbox": sanitized,
                    "ctx": ctx_text,
                })

    for record in unknown.values():
        record["pages"] = sorted(record["pages"])
        record["contexts"] = sorted(record["contexts"])
    return unknown


def collect_samples(doc, max_samples_per_cid=1, legacy_map=None):
    """Backward-compatible view: ``{(font_id, cid): [sample, ...]}``."""
    return {key: record["samples"]
            for key, record in collect_review_data(
                doc, max_samples_per_cid=max_samples_per_cid,
                legacy_map=legacy_map).items()}
