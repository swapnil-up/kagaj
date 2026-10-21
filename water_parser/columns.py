"""Load and query human-marked column regions for PDF schedule tables.

The JSON is produced by folding ``agent-tools/mark-boxes`` output into
``water_parser/column_regions.json`` (one region per branch/table/page). Each region
holds pixel-space column rectangles at a known render dpi and an anchor column
used by :mod:`water_parser.spatial` to detect new records.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_COLUMNS = ("label", "dma", "days", "time_from", "time_to", "areas", "contacts")


def load_regions(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def regions_for(regions: dict, branch: str, page: int | None = None) -> list[dict]:
    out = []
    for key, r in regions.items():
        if r.get("branch") != branch:
            continue
        if page is not None and r.get("page") != page:
            continue
        out.append({"key": key, **r})
    return sorted(out, key=lambda r: r.get("page", 0))


def classify_x(region: dict, x_center: float) -> str | None:
    """Return the column name whose x-range contains ``x_center`` (or None)."""
    for name, spec in region.get("columns", {}).items():
        left, _, right, _ = spec["px"]
        if left <= x_center <= right:
            return name
    return None


def from_markboxes(boxes: dict, column_names: tuple[str, ...] = DEFAULT_COLUMNS) -> dict:
    """Convert a mark-boxes export to a ``columns`` mapping.

    Boxes are consumed in list (marking) order; the i-th box becomes
    ``column_names[i]``. Raises if the counts differ, to catch mis-marking.
    """
    marked = boxes.get("boxes", [])
    if len(marked) != len(column_names):
        raise ValueError(
            f"expected {len(column_names)} boxes {column_names}, got {len(marked)}"
        )
    columns = {}
    for name, box in zip(column_names, marked):
        columns[name] = {"px": [int(v) for v in box["px"]]}
    return columns


def make_region(branch: str, page: int, dpi: float, columns: dict,
                reservoir_np: str | None = None, reservoir_en: str | None = None,
                anchor: str | None = "dma",
                row_scan: dict | None = None,
                forward_fill: list[str] | None = None) -> dict:
    region = {
        "branch": branch,
        "page": page,
        "dpi": dpi,
        "reservoir_np": reservoir_np,
        "reservoir_en": reservoir_en,
        "columns": columns,
        "row_scan": row_scan or {"y_start": 0, "row_gap": 40, "header_skip_y": 0},
        "anchor": anchor,
    }
    if forward_fill:
        region["forward_fill"] = list(forward_fill)
    return region


def save_regions(regions: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(regions, ensure_ascii=False, indent=2) + "\n")
