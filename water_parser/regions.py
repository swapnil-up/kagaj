"""Propose PDF column regions from the rendered table's rule lines.

The chosen workflow is human-verified boundaries (mark-boxes). This module makes
that cheap: it detects the table's vertical rules within the table body and maps
them to each page's known column order, writing a draft
``water_parser/column_regions.json`` plus a divider overlay for eyeballing. If the draft
is right, no dragging is needed; if a boundary is off, re-mark that page with
``agent-tools/mark-boxes`` and fold it in.

Layouts are per branch with per-page overrides, because KUKL varies the columns
between pages (with/without DMA, separate vs combined time, presence of a
remarks column) and re-margins some tables.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

_BW = "Baneshwor"
_BK = "Bhaktpur"

LAYOUTS = {
    _BW: {
        "default": {
            "columns": ["label", "dma", "days", "time_from", "time_to", "areas", "contacts"],
            "anchor": "time_from",
            "forward_fill": ["label", "dma", "days"],
        },
        "pages": {
            # p6 (मिनभवन) has no DMA column.
            6: {
                "columns": ["label", "days", "time_from", "time_to", "areas", "contacts"],
                "anchor": "time_from",
                "forward_fill": ["label", "days"],
            },
        },
    },
    _BK: {
        "default": {
            "columns": ["label", "days", "areas", "time", "contacts"],
            "anchor": "time",
            "forward_fill": ["label", "days"],
        },
        "pages": {
            # p1 carries a trailing remarks column; p2/p4 have no data rows.
            1: {
                "columns": ["label", "days", "areas", "time", "contacts", "notes"],
                "anchor": "time",
                "forward_fill": ["label", "days"],
            },
            2: {"skip": True},
            4: {"skip": True},
        },
    },
}


def _gray_array(png_path: Path) -> np.ndarray:
    return np.array(Image.open(png_path).convert("L"))


def _rules(projection: np.ndarray, threshold: float, gap: int = 3) -> list[int]:
    hits = [i for i, v in enumerate(projection) if v > threshold]
    groups: list[list[int]] = []
    for i in hits:
        if groups and i - groups[-1][-1] <= gap:
            groups[-1].append(i)
        else:
            groups.append([i])
    return [int(np.mean(g)) for g in groups]


def detect_horizontal_rules(img: np.ndarray, frac: float = 0.5) -> list[int]:
    return _rules((img < 128).sum(axis=1), img.shape[1] * frac)


def detect_vertical_rules(img: np.ndarray, y0: int | None = None,
                          y1: int | None = None, frac: float = 0.5) -> list[int]:
    band = img[y0:y1] if y0 is not None else img
    return _rules((band < 128).sum(axis=0), band.shape[0] * frac)


def _layout_for(branch: str, page: int) -> dict:
    spec = LAYOUTS[branch]
    return spec.get("pages", {}).get(page, spec["default"])


def propose_regions(branch: str, png_paths: list[Path], dpi: float = 300.0,
                    log=None) -> dict:
    regions: dict = {}
    for page, png in enumerate(sorted(png_paths), 1):
        layout = _layout_for(branch, page)
        if layout.get("skip"):
            if log:
                log(f"[regions] {branch} p{page}: skipped (no data rows)")
            continue
        names = layout["columns"]
        img = _gray_array(png)
        hrules = detect_horizontal_rules(img)
        if len(hrules) < 3:
            if log:
                log(f"[regions] {branch} p{page}: no table detected — skipped")
            continue
        vrules = detect_vertical_rules(img, y0=hrules[1], y1=hrules[-1])
        if len(vrules) - 1 != len(names):
            if log:
                log(f"[regions] {branch} p{page}: detected {len(vrules) - 1} "
                    f"columns, expected {len(names)} — skipped (mark manually)")
            continue
        columns = {
            name: {"px": [left, 0, right, img.shape[0]]}
            for name, left, right in zip(names, vrules, vrules[1:])
        }
        bands = [[hrules[i], hrules[i + 1]] for i in range(2, len(hrules) - 1)]
        key = f"{branch}_p{page}"
        regions[key] = {
            "branch": branch,
            "page": page,
            "dpi": dpi,
            "reservoir_np": None,
            "reservoir_en": None,
            "columns": columns,
            "row_scan": {"y_start": 0, "row_gap": 120, "header_skip_y": hrules[2]},
            "row_bands": bands,
            "anchor": layout["anchor"],
            "forward_fill": layout["forward_fill"],
        }
        if log:
            log(f"[regions] {key}: {names} header_skip={hrules[2]} bands={len(bands)}")
    return regions


def draw_overlay(png_path: Path, region: dict, out_path: Path) -> None:
    """Save a copy of the page with column boundaries drawn for review."""
    img = Image.open(png_path).convert("RGB")
    arr = np.array(img)
    top = region["row_scan"]["header_skip_y"]
    for name, spec in region["columns"].items():
        left, _, right, _ = spec["px"]
        arr[top:top + 8, max(left - 3, 0):right + 3] = [255, 0, 0]
        arr[top:img.height, max(left - 1, 0):left + 1] = [0, 128, 255]
    Image.fromarray(arr).save(out_path)
