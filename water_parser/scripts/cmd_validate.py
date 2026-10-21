"""``water_parser validate`` — flag suspicious zones in per-branch extracts.

Reads tracked ``datasets/water/<Branch>__<month>.json`` files, runs the invariant checks
in :mod:`water_parser.validate` over every zone, prints a summary, and lists the
flagged zones so a human can inspect the source row.
"""

from __future__ import annotations

import json

from .. import paths, validate


def run(args) -> int:
    if not paths.WATER_DIR.exists():
        print("[validate] datasets/water/ not found")
        return 1

    total = 0
    grand: dict[str, int] = {}
    any_flagged = False
    print(f"{'branch':<14} {'month':<12} {'zones':>6} {'flagged':>8}")
    for path in sorted(paths.WATER_DIR.glob("*.json")):
        if path.name in ("manifest.json", "schedule.json", "column_regions.json"):
            continue
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        src = doc.get("source", {})
        branch = src.get("branch") or path.stem.split("__")[0]
        if args.branch and args.branch.lower() not in branch.lower():
            continue
        zones = [z for r in doc.get("reservoirs", []) for z in r.get("zones", [])]
        for z in zones:
            cols = set(z.get("source_columns") or []) or None
            z["review_flags"] = validate.flag_zone(z, cols)
        summary = validate.summarize(zones)
        total += summary["total"]
        for k, v in summary["by_flag"].items():
            grand[k] = grand.get(k, 0) + v
        if summary["flagged"]:
            any_flagged = True
        print(f"{branch:<14} {src.get('month_key', path.stem):<12} "
              f"{summary['total']:>6} {summary['flagged']:>8}")
        if args.verbose:
            for z in validate.flagged_zones(zones):
                loc = z.get("dma") or z.get("label") or "?"
                msgs = ",".join(z["review_flags"])
                print(f"    - {loc}: {msgs} "
                      f"days={z.get('days')} {z.get('time_from')}->{z.get('time_to')}")

    print(f"\ntotal zones: {total}")
    if grand:
        print("flags: " + ", ".join(f"{k}={v}" for k, v in sorted(grand.items())))
        return 1 if any_flagged else 0
    print("no flags")
    return 0
