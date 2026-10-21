"""``water_parser build`` — merge per-branch extractions into one schedule file.

Scans tracked ``datasets/water/*.json`` (excluding the manifest), keeps the most recent
month per branch (Nepali month order via :func:`paths.month_sort_key`), and
writes ``datasets/water/schedule.json`` — the single artifact the website consumes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .. import paths

# Split a run of place names into individual search tokens. Comma-like
# separators only, so multi-word names ("Baneshwor Height") stay intact.
_TOKEN_SPLIT = re.compile(r"[,;/|।\n]+")


def _search_terms(zone: dict) -> list[str]:
    seen: dict[str, None] = {}
    for key in ("areas_np", "areas_en"):
        for phrase in zone.get(key) or []:
            for tok in _TOKEN_SPLIT.split(phrase or ""):
                tok = tok.strip(" .")
                if len(tok) >= 2 and tok not in seen:
                    seen[tok] = None
    return list(seen)


def run(args) -> int:
    if not paths.WATER_DIR.exists():
        print("[build] datasets/water/ not found — run `process` first")
        return 1

    # latest structured file per branch
    best: dict[str, dict] = {}
    for path in sorted(paths.WATER_DIR.glob("*.json")):
        if path.name in ("manifest.json", "schedule.json"):
            continue
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"[build] skipping unreadable {path.name}")
            continue
        src = doc.get("source", {})
        branch = src.get("branch")
        month_key = src.get("month_key")
        if not branch or not month_key:
            continue
        prev = best.get(branch)
        if prev is None or paths.month_sort_key(month_key) > paths.month_sort_key(
            prev["month_key"]
        ):
            best[branch] = {"month_key": month_key, "doc": doc, "file": path.name}

    if not best:
        print("[build] no branch extracts found")
        return 1

    branches = []
    for branch in sorted(best):
        entry = best[branch]
        doc = entry["doc"]
        src = doc.get("source", {})
        reservoirs = doc.get("reservoirs", [])
        for reservoir in reservoirs:
            for zone in reservoir.get("zones", []):
                zone.pop("source_columns", None)
                zone.setdefault("search_terms", _search_terms(zone))
        branches.append({
            "branch": branch,
            "branch_np": doc.get("branch_np"),
            "branch_en": doc.get("branch_en") or branch,
            "month_bs": doc.get("month_bs"),
            "month_key": entry["month_key"],
            "source_file": src.get("file"),
            "source_url": src.get("url"),
            "reservoirs": reservoirs,
        })

    paths.SCHEDULE.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": paths.KUKL_SCHEDULE_URL,
        "branches": branches,
    }, ensure_ascii=False, indent=2) + "\n")

    total = sum(len(r.get("zones", [])) for b in branches for r in b["reservoirs"])
    print(f"[build] {len(branches)} branches, {total} zones → {paths.SCHEDULE.name}")
    for b in branches:
        z = sum(len(r.get("zones", [])) for r in b["reservoirs"])
        print(f"         {b['branch']:<14} {b['month_key']:<12} {z} zones")
    return 0
