"""Backward-compatible redbook entry point for the shared CID review sheet.

The implementation lives in :mod:`cidmap.glyph_review`; this module only adds
the redbook-specific legacy CID hints.
"""

import argparse
import sys
from pathlib import Path

from cidmap import glyph_collection as collection
from cidmap.glyph_review import (
    _reference_candidates,
    _sample_crops,
    build_review_html as _build_review_html,
    build_review_items as _build_review_items,
)
from redbook_parser.legacy import CID_CHAR_MAP

__all__ = [
    "build_review_html",
    "build_review_items",
    "collection",
    "main",
]


def build_review_items(doc, sample_per_cid: int = 3,
                       only: set[int] | None = None,
                       issues: list | None = None, *,
                       reference_font: str | None = None,
                       shape_runs: bool = False,
                       registry: dict | None = None):
    return _build_review_items(
        doc, sample_per_cid, only, issues=issues,
        reference_font=reference_font, shape_runs=shape_runs,
        registry=registry, legacy_map=CID_CHAR_MAP)


def build_review_html(doc, sample_per_cid: int = 3,
                      only: set[int] | None = None, *,
                      session: str | None = None,
                      reference_font: str | None = None,
                      shape_runs: bool = False,
                      registry: dict | None = None):
    if session is None:
        name = (getattr(doc, "name", "") or getattr(doc, "path", "")
                or "unknown")
        session = f"redbook:{name}"
    return _build_review_html(
        doc, sample_per_cid, only, session=session,
        reference_font=reference_font, shape_runs=shape_runs,
        registry=registry, legacy_map=CID_CHAR_MAP)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pdf")
    p.add_argument("-o", "--output", default="output/cid_review.html")
    p.add_argument("--crop", type=int, default=3,
                   help="render samples per (font, CID) pair")
    p.add_argument("--cids", type=lambda s: {int(x) for x in s.split(",")},
                   default=None, help="restrict to these CIDs (comma-separated)")
    p.add_argument("--reference-font", default=None,
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

    from kagaj_core import pdf as core_pdf

    registry = None
    if getattr(a, "registry", None):
        from cidmap import registry as registry_mod
        registry = registry_mod.load(a.registry)
    doc = core_pdf.open_pdf(a.pdf)
    htmlout = build_review_html(
        doc, a.crop, only=a.cids,
        session=f"redbook:{Path(a.pdf).resolve()}",
        reference_font=a.reference_font, shape_runs=a.shape_runs,
        registry=registry)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(htmlout, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
