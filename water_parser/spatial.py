"""Assemble OCR lines into records using marked column geometry.

Two strategies:

* **anchor** (preferred): every line in the region's anchor column starts a new
  record (one delivery window per anchor cell). Every other line is attached to
  the *nearest* anchor by y, so a wrapped time/area cell stays with its own row
  even when the table's horizontal rules under-segment. Merged columns
  (label/DMA/days) are centred over their row group and attached afterwards by
  midpoint partition (see ``_assign_merged``).
* **gap** (fallback): when no anchor column is marked, lines are grouped into
  rows whenever y advances by more than ``row_scan.row_gap``.

No semantics beyond geometry live here — numeric/date parsing happens in
:mod:`water_parser.fields`.
"""

from __future__ import annotations

from . import columns as colmod


def region_lines(lines: list[dict], region: dict) -> list[dict]:
    page = region.get("page")
    y_skip = (region.get("row_scan") or {}).get("header_skip_y", 0)
    sel = []
    for ln in lines:
        if page is not None and ln.get("page") != page:
            continue
        if y_skip and ln["y"] < y_skip:
            continue
        sel.append(ln)
    sel.sort(key=lambda r: (r["y"], r["x"]))
    return sel


def extract_records(lines: list[dict], region: dict) -> list[dict]:
    """Return ``{column: [line, ...], 'y', 'page'}`` records for one region."""
    sel = region_lines(lines, region)
    anchor = region.get("anchor")
    if anchor:
        return _group_by_anchor(sel, region, anchor)
    return _group_by_gap(sel, region)


def _blank(region: dict) -> dict:
    rec = {name: [] for name in region.get("columns", {})}
    rec["_y"] = None
    rec["_page"] = region.get("page")
    return rec


def _attach(rec: dict, col: str, ln: dict) -> None:
    if col not in rec:
        rec[col] = []
    rec[col].append(ln["text"])
    if rec["_y"] is None:
        rec["_y"] = ln["y"]


def _finalize(rec: dict) -> dict:
    out = {k: list(v) for k, v in rec.items() if not k.startswith("_")}
    out["y"] = rec["_y"]
    out["page"] = rec["_page"]
    return out


def _group_by_anchor(lines: list[dict], region: dict, anchor: str) -> list[dict]:
    merged = set(region.get("forward_fill") or [])
    anchors: list[list] = []          # [y, [texts]]
    deferred: list[tuple[int, str, str]] = []
    others: list[tuple[int, str, str]] = []
    for ln in lines:
        col = colmod.classify_x(region, ln["x"] + ln["w"] / 2)
        if col is None:
            continue
        if col == anchor:
            if ln["text"].strip():
                anchors.append([ln["y"], [ln["text"]]])
        elif col in merged:
            deferred.append((ln["y"], col, ln["text"]))
        else:
            others.append((ln["y"], col, ln["text"]))

    if not anchors:
        return []

    records: list[dict] = []
    starts: list[int] = []
    for y, texts in anchors:
        rec = _blank(region)
        rec["_y"] = y
        rec[anchor] = list(texts)
        records.append(rec)
        starts.append(y)

    for y, col, text in others:
        idx = _nearest(starts, y)
        records[idx].setdefault(col, []).append(text)

    _assign_merged(records, starts, deferred)
    return [_finalize(r) for r in records]


def _nearest(starts: list[int], y: int) -> int:
    idx = 0
    best = None
    for i, s in enumerate(starts):
        d = abs(s - y)
        if best is None or d < best:
            best, idx = d, i
    return idx


def _assign_merged(records: list[dict], starts: list[int],
                   deferred: list[tuple[int, str, str]]) -> None:
    """Attach merged-cell values by nearest value, not by band.

    A merged cell (DMA / label / days) is vertically centred over its row group,
    so its y can fall anywhere in the group. For each merged column we partition
    the zones at the midpoints between consecutive cell values; every zone maps
    to the value whose partition contains its start y.
    """
    by_col: dict[str, list[tuple[int, str]]] = {}
    for y, col, text in deferred:
        by_col.setdefault(col, []).append((y, text))

    for col, items in by_col.items():
        items.sort()
        ys = [y for y, _ in items]
        for j, start in enumerate(starts):
            idx = 0
            for k in range(1, len(ys)):
                if start >= (ys[k - 1] + ys[k]) / 2:
                    idx = k
                else:
                    break
            records[j].setdefault(col, []).append(items[idx][1])


def _group_by_gap(lines: list[dict], region: dict) -> list[dict]:
    row_gap = (region.get("row_scan") or {}).get("row_gap", 40)
    records: list[dict] = []
    current: dict | None = None
    last_y: float | None = None
    for ln in lines:
        col = colmod.classify_x(region, ln["x"] + ln["w"] / 2)
        if col is None:
            continue
        if current is None or (last_y is not None and ln["y"] - last_y > row_gap):
            if current is not None:
                records.append(_finalize(current))
            current = _blank(region)
        _attach(current, col, ln)
        last_y = ln["y"]
    if current is not None:
        records.append(_finalize(current))
    return records
