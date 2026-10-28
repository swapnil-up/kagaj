"""``water_parser render`` — render PDF entries to page PNGs for mark-boxes.

Renders each selected PDF manifest entry at 300 dpi into
``output/water/rendered/<branch>/`` so column regions can be marked with
``agent-tools/mark-boxes`` and OCR coordinates line up with the marked pixels.
"""

from __future__ import annotations

import json
from .. import paths, render
from .cmd_process import _download, _raw_path


def run(args) -> int:
    if not paths.MANIFEST.exists():
        print("[render] no manifest — run `scrape` first")
        return 1

    manifest = json.loads(paths.MANIFEST.read_text())
    selected = []
    for e in manifest["entries"]:
        if e["kind"] != "pdf":
            continue
        if args.month and e["month_key"].lower() != args.month.lower():
            continue
        if args.branch and args.branch.lower() not in e["branch"].lower():
            continue
        selected.append(e)
    if not selected:
        print("[render] no PDFs matched")
        return 0

    for entry in selected:
        out_dir = paths.RENDER_DIR / entry["branch"]
        existing = list(out_dir.glob("*.png")) if out_dir.exists() else []
        if existing and not args.force:
            print(f"[render] {entry['branch']}: {len(existing)} pages cached")
            continue
        raw_path = _raw_path(entry)
        if not raw_path.exists():
            _download(entry["url"], raw_path)
        print(f"[render] {entry['branch']} → {out_dir.relative_to(paths.REPO_ROOT)}")
        render.render_pdf(raw_path, out_dir, log=print)
    return 0
