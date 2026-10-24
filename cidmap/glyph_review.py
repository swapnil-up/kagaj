"""HTML review sheet: render the original PDF around each unknown CID.

The census proves which CIDs are unknown; the reviewer still needs to SEE the
printed glyph to type the correct Devanagari. This adapter scans each page once,
renders up to N word/glyph crops per unknown CID from the source PDF, and hands
the items to :mod:`kagaj_core.review`, which owns the HTML shell, keyboard flow,
per-session persistence, filters, and neutral export.

The exported ``cid_corrections.json`` uses the neutral review shape and is
font-scoped, so it can be committed with ``cidmap commit``. The older
``{cid, correct}`` word-based files still go through ``redbook derive``.

Usage:
    python -m cidmap.cli review <pdf> -o out.html
    python -m cidmap.cli review <pdf> --reference-font Kalimati.ttf \
        -o out.html
"""

import argparse
import logging
import sys
from pathlib import Path

from .reference_fonts import reference_font_arg
from .fonts import source_hash
from .glyph_collection import collect_review_data
from kagaj_core.review import (
    ReviewCandidate,
    ReviewCrop,
    ReviewItem,
    render_review,
)
from kagaj_core.review.crops import render_review_crop

_LOG = logging.getLogger(__name__)


def _sample_crops(doc, sample, index, total):
    caption = f"p{sample['page']} \u00b7 occurrence {index}/{total}"
    try:
        crop = render_review_crop(
            doc,
            word=(sample["page"], sample["bbox"]),
            glyph=(sample["page"], sample["glyph_bbox"]),
        )
    except Exception as exc:
        _LOG.warning("crops failed for page %s: %s", sample.get("page"), exc)
        return None
    if not crop.glyph and not crop.word:
        return None
    return ReviewCrop(glyph=crop.glyph, word=crop.word,
                      overlay=crop.overlay, caption=caption)


def _reference_candidates(reference, embedded, record, cid):
    if reference is None or embedded is None:
        return ()
    matches = reference.suggest(embedded.shape(record["font_xref"], cid))
    return tuple(
        ReviewCandidate(value=match.value, label=f"ref {match.value}",
                        detail=match.detail)
        for match in matches
    )


def _registry_candidates(registry, embedded, record, cid):
    if registry is None or embedded is None:
        return ()
    from .registry import resolve_glyph

    try:
        bundle = resolve_glyph(
            registry, embedded, record.get("font_xref"), cid,
            record.get("base_font") or "")
    except Exception:
        return ()
    if not bundle:
        return ()
    entry = bundle["entry"]
    if not entry.get("value") or entry.get("status") == "conflict":
        return ()
    return (ReviewCandidate(
        value=entry["value"],
        label=f"registry {entry['value']}",
        detail=(f"registry · {entry.get('status')} · "
                f"{entry.get('support', 0)} doc"),
    ),)


def _shape_run_candidates(doc, reference_font):
    from .infer import infer_runs

    best = {}
    for inference in infer_runs(
            doc, reference_font=reference_font, max_candidates=3):
        for candidate in inference.candidates:
            for assignment in candidate.assignments:
                key = (inference.font_id, assignment.cid)
                current = best.get(key)
                if current is not None and current[0] <= candidate.score:
                    continue
                best[key] = (candidate.score, ReviewCandidate(
                    value=assignment.value,
                    label=f"run {candidate.word}",
                    detail=(f"shape-run \u00b7 {inference.observed} "
                            f"\u00b7 score {candidate.score:.1f}"),
                ))
    return {key: [value[1]] for key, value in best.items()}


def build_review_items(doc, sample_per_cid: int = 3,
                       only: set[int] | None = None,
                       issues: list | None = None, *,
                       reference_font: str | None = None,
                       shape_runs: bool = False,
                       registry: dict | None = None,
                       legacy_map=None) -> list[ReviewItem]:
    """Collect unknown ``(font_id, cid)`` pairs as neutral review items."""
    data = collect_review_data(doc, max_samples_per_cid=sample_per_cid,
                               issues=issues, legacy_map=legacy_map)
    reference = None
    embedded = None
    if shape_runs and not reference_font:
        raise ValueError("shape_runs requires reference_font")
    if reference_font or registry is not None:
        from cidmap.embedded import EmbeddedFontCache
        embedded = EmbeddedFontCache(doc)
    if reference_font:
        from cidmap.reference import ReferenceIndex
        reference = ReferenceIndex.from_path(reference_font)
    run_candidates = (
        _shape_run_candidates(doc, reference_font) if shape_runs else {}
    )
    pdf_hash = source_hash(doc)
    source = getattr(doc, "name", "") or getattr(doc, "path", "") or ""
    items = []
    for (font_id, cid) in sorted(data, key=lambda key: (key[0], key[1])):
        if only is not None and cid not in only and font_id not in only:
            continue
        record = data[(font_id, cid)]
        crops = []
        samples = record["samples"]
        for index, sample in enumerate(samples, 1):
            crop = _sample_crops(doc, sample, index, len(samples))
            if crop is not None:
                crops.append(crop)

        pages = record["pages"]
        shown_pages = ", ".join(f"p{p}" for p in pages[:6])
        if len(pages) > 6:
            shown_pages += ", \u2026"
        summary = (f"{record['count']} occurrence(s) \u00b7 {shown_pages} "
                   f"\u00b7 {record['font_id_scheme']} \u00b7 "
                   f"xref {record['font_xref']}")
        data_out = {
            "cid": cid,
            "font": font_id,
            "font_id": font_id,
            "base_font": record["base_font"],
            "font_xref": record["font_xref"],
            "font_id_scheme": record["font_id_scheme"],
            "source_pdf": source,
            "source_sha256": pdf_hash,
        }
        if record["has_legacy_value"]:
            data_out["legacy_value"] = record["legacy_value"]
        items.append(ReviewItem(
            key=f"{font_id}\u2571{cid}",
            label=f"CID {cid}",
            group=font_id,
            context=summary,
            candidates=(
                _reference_candidates(reference, embedded, record, cid)
                + _registry_candidates(registry, embedded, record, cid)
                + tuple(run_candidates.get((font_id, cid), ()))
            ),
            crops=tuple(crops),
            data=data_out,
            input_placeholder="glyph / cluster (e.g. \u0930\u094d or \u093f)",
        ))
    return items


def build_review_html(doc, sample_per_cid: int = 3,
                      only: set[int] | None = None, *,
                      session: str | None = None,
                      reference_font: str | None = None,
                      shape_runs: bool = False,
                      registry: dict | None = None,
                      legacy_map=None) -> str:
    """Render the review sheet (no PDF libraries are needed by core)."""
    if session is None:
        name = (getattr(doc, "name", "") or getattr(doc, "path", "")
                or "unknown")
        session = f"cidmap:{name}"
    issues: list[dict] = []
    items = build_review_items(doc, sample_per_cid, only, issues=issues,
                               reference_font=reference_font,
                               shape_runs=shape_runs,
                               registry=registry,
                               legacy_map=legacy_map)
    notice = ""
    if issues:
        pages = ", ".join(f"p{issue['page']}" for issue in issues[:12])
        notice = (f"{len(issues)} page(s) need manual font resolution and were "
                  f"skipped: {pages}. {issues[0]['message']}")
    return render_review(
        items,
        session=session,
        title=f"Unknown-CID review ({len(items)})",
        export_name="cid_corrections.json",
        group_label="font",
        search_placeholder="CID or font search",
        notice=notice,
        help_text=(
            "Each card is one (font subset, CID) pair; the same CID in a "
            "different subset is a different card. The blue-bordered image is "
            "the missing CID. Judge the glyph crop, not the surrounding word: "
            "the same mark can appear in unrelated words. Type only the "
            "glyph/cluster that the CID maps to. Mark undecodable when the ink "
            "is unreadable; use inconsistent only when the same CID prints a "
            "different glyph shape in different samples. Reference-font "
            "candidates are suggestions from outline matching; confirm them "
            "against the crop."
        ),
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pdf")
    p.add_argument("-o", "--output", default="output/cid_review.html")
    p.add_argument("--crop", type=int, default=3,
                   help="render samples per (font, CID) pair")
    p.add_argument("--cids", type=lambda s: {int(x) for x in s.split(",")},
                   default=None, help="restrict to these CIDs (comma-separated)")
    p.add_argument("--reference-font", default=None, type=reference_font_arg,
                   help="original TTF/OTF used to suggest glyph values")
    p.add_argument("--shape-runs", action="store_true",
                   help="add shape-run candidates (requires --reference-font)")
    p.add_argument("--registry", default=None,
                   help="cross-document glyph registry for candidates")
    a = p.parse_args(argv)
    if a.reference_font and not Path(a.reference_font).exists():
        print(f"Error: {a.reference_font} not found", file=sys.stderr)
        return 1
    if a.shape_runs and not a.reference_font:
        print("Error: --shape-runs requires --reference-font",
              file=sys.stderr)
        return 1

    import fitz

    registry = None
    if getattr(a, "registry", None):
        from . import registry as registry_mod
        registry = registry_mod.load(a.registry)
    doc = fitz.open(a.pdf)
    htmlout = build_review_html(
        doc, a.crop, only=a.cids,
        session=f"cidmap:{Path(a.pdf).resolve()}",
        reference_font=a.reference_font, shape_runs=a.shape_runs,
        registry=registry)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(htmlout, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
