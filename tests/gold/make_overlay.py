"""Generate an editable HTML overlay of extracted text on a page image.

Usage:
    redbook-env/bin/python tests/gold/make_overlay.py <pdf> <page> [-o out.html] [--boxes boxes.json]

Renders the page and places every decoded glyph as editable, band-anchored
cells on top of it. Cells are anchored to the user-verified column bands
(measured in the spike via mark_boxes.py -> boxes.json), NOT to per-word
bboxes:

  - each rawdict char is bucketed into a band by its x-center (logical order
    is preserved, so control chars that fix_text keys on stay intact);
  - each (line, band) cell joins its chars in logical order and runs the full
    fix_text chain once — cross-word fixes like 'रा9प'+'त' -> 'राष्ट्रपति'
    work because the \x04 control char is still inside the joined string;
  - the box is placed at the band's x-range x the line's y-band, so the text
    sits loose in its column instead of being pixel-pinned to word bboxes.

Open the HTML in a browser: yellow text over the page image; where it
disagrees, edit the cell in place. Band grid lines show which column each
cell belongs to. Click "Save JSON" to download the corrected spatial text
layer for gold seeding.

Decode is the same best-effort chain as the pipeline (ToUnicode CMap via
PyMuPDF + legacy fix_text for unmapped CIDs). Residual errors are exactly
what the human corrects in the overlay.
"""

import argparse
import base64
import html
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from redbook_parser.legacy import fix_text, sanitize_devanagari
from redbook_parser.spatial import GRID_BOUNDS

DPI = 200  # render resolution; bbox pt -> px via scale = DPI/72
SCALE = DPI / 72.0


def load_bands(boxes_path: Path | None) -> list[tuple[str, str, float, float]]:
    """Return ordered bands as (label, name, x0, x1) in PDF points.

    Prefers a boxes.json from the spike (user-verified geometry: label b1-b12),
    falls back to the detail GRID_BOUNDS in spatial.py (column names).
    """
    if boxes_path and Path(boxes_path).exists():
        data = json.loads(Path(boxes_path).read_text())
        bands = []
        for b in data.get("boxes", []):
            x0, _, x1, _ = b["pt"]
            bands.append((b["label"], b.get("name", b["label"]), x0, x1))
        if bands:
            return bands
    return [(k, k, lo, hi) for k, (lo, hi) in GRID_BOUNDS.items()]


def band_for(x: float, bands) -> str | None:
    """Nearest-band label for an x-center (points)."""
    best, best_d = None, float("inf")
    for label, _name, lo, hi in bands:
        if lo <= x <= hi:
            return label
        d = min(abs(x - lo), abs(x - hi))
        if d < best_d:
            best, best_d = label, d
    return best


def build_cells(page, bands) -> tuple[list[dict], list[str]]:
    """Bucket rawdict chars into (line, band) cells; return cell data + html.

    Each line is a dict {y0, y1, cells: [(label, x0, x1, text)]} where text is
    the fix_text-decodded join of that line's chars in its band.
    """
    html_spans: list[str] = []
    lines_out: list[dict] = []

    raw = page.get_text("rawdict")

    # rawdict splits one visual row into a separate "line" per column (large
    # gaps between bands). Merge lines whose y-centers overlap into rows.
    raw_lines: list[dict] = []
    for block in raw["blocks"]:
        if block.get("type") != 0:
            continue
        raw_lines.extend(block["lines"])
    rows: list[dict] = []
    for line in raw_lines:
        yc = (line["bbox"][1] + line["bbox"][3]) / 2.0
        for row in rows:
            if abs(yc - (row["y0"] + row["y1"]) / 2.0) < 4.0:
                row["lines"].append(line)
                row["y0"] = min(row["y0"], line["bbox"][1])
                row["y1"] = max(row["y1"], line["bbox"][3])
                break
        else:
            rows.append({"y0": line["bbox"][1], "y1": line["bbox"][3], "lines": [line]})
    rows.sort(key=lambda r: r["y0"])

    for row in rows:
        y0, y1 = row["y0"], row["y1"]
        # bucket chars by band, preserving logical (rawdict) order
        cells: dict[str, list[str]] = {}
        for line in row["lines"]:
            for span in line["spans"]:
                for ch in span["chars"]:
                    cx = (ch["bbox"][0] + ch["bbox"][2]) / 2.0
                    label = band_for(cx, bands)
                    cells.setdefault(label, []).append(ch["c"])
        line_cells = []
        for label, name, lo, hi in bands:
            if label not in cells:
                continue
            joined = sanitize_devanagari(fix_text("".join(cells[label])))
            if not joined.strip():
                continue
            left = (lo + 2) * SCALE
            width = (hi - lo - 4) * SCALE
            top = (y0 - 1) * SCALE
            height = max((y1 - y0 + 2) * SCALE, 8)
            line_cells.append({"band": label, "text": joined})
            html_spans.append(
                f'<div class="w" data-line="{len(lines_out)}" data-band="{label}" '
                f'contenteditable="true" spellcheck="false" '
                f'style="left:{left:.1f}px;top:{top:.1f}px;'
                f'width:{max(width, 8):.1f}px;height:{height:.1f}px">'
                f'{html.escape(joined)}</div>'
            )
        lines_out.append({"y0": y0, "y1": y1, "cells": line_cells})

    return lines_out, html_spans


def make_overlay(pdf_path: str, page_no: int, boxes_path: Path | None = None):
    from kagaj_core import pdf as core_pdf

    doc = core_pdf.open_pdf(pdf_path)
    page = doc[page_no - 1]
    pix = core_pdf.render_pixmap(page, dpi=DPI)
    b64 = base64.b64encode(pix.tobytes("png")).decode()
    bands = load_bands(boxes_path)

    lines_data, spans_html = build_cells(page, bands)

    # vertical grid lines for the bands (full page height)
    grid_lines = []
    for label, name, lo, hi in bands:
        x = (lo + hi) / 2.0 * SCALE
        grid_lines.append(f'<div class="gline" style="left:{lo * SCALE:.1f}px"></div>')
        grid_lines.append(
            f'<div class="glabel" style="left:{lo * SCALE + 2:.1f}px">{html.escape(label)}</div>'
        )

    layer_data = {
        "page": page_no,
        "scale": 1,
        "bands": [
            {"label": label, "name": name, "x0": lo, "x1": hi} for label, name, lo, hi in bands
        ],
        "lines": lines_data,
    }

    body = f"""<!DOCTYPE html>
<html lang="ne">
<head>
<meta charset="utf-8">
<title>Page {page_no} overlay</title>
<style>
  body {{ margin: 0; background: #222; font-family: 'Noto Sans Devanagari', 'Kalimati', serif; }}
  .toolbar {{ position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
             background: rgba(0,0,0,.85); color: #eee; padding: 8px 12px;
             display: flex; gap: 14px; align-items: center; font-size: 14px; }}
  .toolbar button {{ padding: 4px 12px; font-size: 14px; cursor: pointer; }}
  .toolbar label {{ display: flex; align-items: center; gap: 6px; }}
  .stage {{ position: relative; width: {pix.width}px; margin: 48px auto 0; }}
  .stage img {{ display: block; width: {pix.width}px; }}
  .gline {{ position: absolute; top: 0; bottom: 0; width: 1px;
           background: rgba(0,255,0,.28); pointer-events: none; }}
  .glabel {{ position: absolute; top: 0; color: rgba(0,255,0,.7);
            font-size: 11px; pointer-events: none; }}
  .w {{ position: absolute; border: 1px solid rgba(255,80,80,.5); cursor: text;
        color: #ff0; background: rgba(0,0,0,.35); text-shadow: 0 0 2px #000;
        outline: none; font-size: {7 * SCALE:.0f}px; line-height: 1.2;
        white-space: nowrap; overflow: visible; }}
  .w:hover {{ border-color: #4f4; background: rgba(0,0,0,.55); }}
  .w:focus {{ border-color: #0af; background: rgba(0,0,0,.8); color: #fff; }}
  .hidden .w {{ visibility: hidden; }}
  #status {{ color: #8f8; font-size: 13px; }}
</style>
</head>
<body>
<div class="toolbar">
  <button onclick="save()">Save JSON</button>
  <label><input type="checkbox" id="toggle" onchange="document.body.classList.toggle('hidden', this.checked)"> hide text</label>
  <label>opacity <input type="range" id="op" min="0" max="100" value="100"
        oninput="document.querySelectorAll('.w').forEach(w=>w.style.opacity=this.value/100)"></label>
  <span id="status">fix the yellow text where it disagrees with the page, then Save JSON</span>
</div>
<div class="stage">
  <img src="data:image/png;base64,{b64}" alt="page {page_no}">
  {''.join(grid_lines)}
  {''.join(spans_html)}
</div>
<script>
function save() {{
  const lines = [];
  document.querySelectorAll('.w').forEach(w => {{
    const li = +w.dataset.line;
    while (lines.length <= li) lines.push({{ cells: [] }});
    lines[li].cells.push({{ band: w.dataset.band, text: w.textContent.trim() }});
  }});
  const data = {{ page: {page_no}, scale: 1, lines }};
  const blob = new Blob([JSON.stringify(data, null, 2)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'page_{page_no:03d}.overlay.json';
  a.click();
  document.getElementById('status').textContent = 'saved ' + new Date().toLocaleTimeString();
}}
</script>
</body>
</html>"""
    return body, json.dumps(layer_data, ensure_ascii=False, indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf")
    ap.add_argument("page", type=int)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--boxes", type=Path, default=Path("output/gold/boxes.json"),
                    help="boxes.json with column bands (default output/gold/boxes.json); "
                         "falls back to spatial.GRID_BOUNDS if absent")
    args = ap.parse_args(argv)

    body, seed = make_overlay(args.pdf, args.page, args.boxes)
    out = args.out or Path(f"page_{args.page:03d}.overlay.html")
    out.write_text(body)
    seed_path = out.with_suffix(".seed.json")
    seed_path.write_text(seed)
    print(f"overlay:   {out}")
    print(f"seed data: {seed_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
