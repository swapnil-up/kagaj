"""HTML decision sheet: review conflict records, crop evidence, export decisions.

Each card is one :class:`cidmap.conflicts.Conflict`: current store/derive value,
verdict, census context, a glyph crop, and the printed-word crop with the glyph
region highlighted. OCR candidates are separate buttons, never concatenated.

The shell, persistence, keyboard flow, and filters come from
:mod:`kagaj_core.review`. Decisions export in the neutral review shape
(``{key, value, undecodable, inconsistent, note, data}``); ``cidmap commit``
accepts only font-scoped neutral records.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from kagaj_core.review import (
    ReviewCandidate,
    ReviewCrop,
    ReviewItem,
    render_review,
)
from kagaj_core.review.crops import render_review_crop

from .conflicts import Conflict, build_conflicts
from .decode import census
from .mappings import load as load_store

_LOG = logging.getLogger(__name__)


def _word_candidate(conflict: Conflict) -> dict:
    """Pick the best ranked OCR candidate that has a crop box."""
    candidates = conflict.ocr_candidates or []
    for candidate in candidates:
        if (candidate.get("bbox")
                and conflict.page in (candidate.get("pages") or [])):
            return candidate
    for candidate in candidates:
        if candidate.get("bbox"):
            return candidate
    return candidates[0] if candidates else {}


def _crops(doc, conflict: Conflict) -> ReviewCrop | None:
    glyph = None
    if conflict.glyph_bbox and conflict.page:
        glyph = (conflict.page, conflict.glyph_bbox)

    candidate = _word_candidate(conflict)
    word_bbox = (candidate.get("bbox") or conflict.word_bbox
                 or conflict.glyph_bbox)
    candidate_pages = [p for p in (candidate.get("pages") or []) if p]
    word_page = (candidate.get("bbox_page") or
                 (candidate_pages[0] if candidate_pages else None) or
                 conflict.page)
    word = (word_page, word_bbox) if word_bbox and word_page else None

    if glyph is None and word is None:
        return None
    try:
        crop = render_review_crop(doc, word=word, glyph=glyph)
    except Exception as exc:
        _LOG.warning("crops failed for %s CID %s: %s",
                     conflict.font or "(no font)", conflict.cid, exc)
        return None
    return crop if crop.glyph or crop.word else None


def _candidate_detail(candidate: dict) -> str:
    pages = candidate.get("pages") or []
    detail = f"{candidate['count']} occurrence(s)"
    if pages:
        detail += f" on p{pages[0]}\u2013p{pages[-1]}"
    return detail


def _review_item(conflict: Conflict, crop: ReviewCrop | None) -> ReviewItem:
    font = conflict.font or ""
    candidates = tuple(
        ReviewCandidate(value=candidate.get("word", ""),
                        count=int(candidate.get("count") or 0),
                        detail=_candidate_detail(candidate))
        for candidate in conflict.ocr_candidates or []
    )
    crops = (crop,) if crop else ()
    return ReviewItem(
        key=f"{font}\u2571{conflict.cid}",
        label=f"CID {conflict.cid}",
        group=font or "(no font)",
        context=conflict.context,
        current=conflict.store_value or conflict.derive_value,
        candidates=candidates,
        crops=crops,
        data={"font": font, "font_id": font, "cid": conflict.cid},
        tags={"verdict": conflict.verdict},
    )


def build_conflicts_html(conflicts: list[Conflict],
                         crops: dict | None = None,
                         *, session: str = "cidmap",
                         notice: str | None = None) -> str:
    """Render conflict records to the workbench HTML (no PDF/OCR needed)."""
    crops = crops or {}
    items = [_review_item(c, crops.get((c.font, c.cid)))
             for c in conflicts]
    return render_review(
        items,
        session=session,
        title="CID mapping review",
        export_name="decisions.json",
        group_label="font",
        search_placeholder="CID search",
        tag_filters=("verdict",),
        notice=notice,
    )


def build_review_html(doc, store, ocr_data, only_font=None, max_samples=2,
                      max_pages=None, *, conflicts=None,
                      census_result=None, session=None,
                      issues: list | None = None) -> str:
    if issues is None:
        issues = []
    if conflicts is None:
        if census_result is None and doc is not None:
            census_result = census(doc, max_pages=max_pages, issues=issues)
        conflicts = build_conflicts(
            doc, store, ocr_data, census_result=census_result)
    if only_font:
        conflicts = [c for c in conflicts if c.font == only_font]
    crops = {}
    if doc is not None:
        for conflict in conflicts:
            crops[(conflict.font, conflict.cid)] = _crops(doc, conflict)
    if session is None:
        name = ""
        if doc is not None:
            name = getattr(doc, "name", "") or getattr(doc, "path", "")
        session = f"cidmap:{name}" if name else "cidmap"
    notice = ""
    if issues:
        pages = ", ".join(f"p{issue['page']}" for issue in issues[:12])
        notice = (f"{len(issues)} page(s) need manual font resolution and were "
                  f"skipped: {pages}. {issues[0]['message']}")
    return build_conflicts_html(conflicts, crops, session=session,
                                notice=notice)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pdf")
    p.add_argument("--store", default="cidmap/data/cid_mappings.json")
    p.add_argument("--ocr", default=None, help="optional cross_check JSON")
    p.add_argument("--font", default=None)
    p.add_argument("-o", "--output", default="output/cidmap_review.html")
    a = p.parse_args(argv)

    from kagaj_core import pdf as core_pdf
    doc = core_pdf.open_pdf(a.pdf)
    store = load_store(a.store)
    ocr = json.loads(Path(a.ocr).read_text()) if a.ocr else {}
    htmlout = build_review_html(
        doc, store, ocr, only_font=a.font,
        session=f"cidmap:{Path(a.pdf).resolve()}:{Path(a.store).resolve()}")
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(htmlout, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
