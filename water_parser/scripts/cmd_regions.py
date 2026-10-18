"""``water_parser regions`` — auto-propose column regions from rendered tables.

For every branch that has a known layout and rendered page PNGs, detect the
table rules, map them to the branch's column order, merge the draft into
``water/column_regions.json``, and write divider overlays under
``output/water/rendered/<branch>/overlay/`` for human review.
"""

from __future__ import annotations

import json

from .. import columns as colmod
from .. import paths, regions as regions_mod

OVERLAY_SUBDIR = "overlay"


def run(args) -> int:
    existing = colmod.load_regions(paths.COLUMN_REGIONS)
    branches = [args.branch] if args.branch else list(regions_mod.LAYOUTS)

    wrote = 0
    for branch in branches:
        if branch not in regions_mod.LAYOUTS:
            print(f"[regions] no layout known for {branch!r} — skipping")
            continue
        pngs = sorted((paths.RENDER_DIR / branch).glob("*_page*.png"))
        pngs = [p for p in pngs if p.parent.name == branch
                and OVERLAY_SUBDIR not in p.parts]
        if not pngs:
            print(f"[regions] {branch}: no rendered pages (run `render`)")
            continue
        proposed = regions_mod.propose_regions(branch, pngs, log=print)
        overlay_dir = paths.RENDER_DIR / branch / OVERLAY_SUBDIR
        overlay_dir.mkdir(parents=True, exist_ok=True)
        for page, png in enumerate(pngs, 1):
            key = f"{branch}_p{page}"
            if key in proposed:
                regions_mod.draw_overlay(png, proposed[key], overlay_dir / png.name)
        existing.update(proposed)
        wrote += len(proposed)
        print(f"[regions] {branch}: {len(proposed)} regions → overlays in {overlay_dir}")

    if wrote:
        colmod.save_regions(existing, paths.COLUMN_REGIONS)
        print(f"[regions] wrote {wrote} regions → {paths.COLUMN_REGIONS.relative_to(paths.REPO_ROOT)}")
        print("[regions] review overlays, then run `process --month <key> --force`")
    return 0
