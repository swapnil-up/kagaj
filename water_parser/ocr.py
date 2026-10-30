"""Coordinate-aware OCR: PNG/PDF page → lines with bounding boxes.

Same PaddleOCR Devanagari setup as the DDA/notice pipelines. Unlike
``text.pdf_to_text`` (which joins words into a string and drops geometry), this
keeps ``{text,x,y,w,h,page,conf}`` for every detected box so
:mod:`water_parser.spatial` can assign boxes to columns by x and rows by y.

Coordinates are in the render pixel space (see :mod:`water_parser.render`).
"""

from __future__ import annotations

import json
from pathlib import Path

from kagaj_core import ocr as core_ocr

_ENGINE = None


def _ocr_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = core_ocr.create_engine()
    return _ENGINE


def ocr_image(image_path: str | Path, engine=None, page: int = 1,
              log=None) -> list[dict]:
    """OCR one PNG; return line dicts sorted by (y, x)."""
    engine = engine or _ocr_engine()
    words = core_ocr.ocr_image(engine, image_path, page=page)

    lines: list[dict] = []
    for word in words:
        text = word.text
        score = word.score
        if score < 0.3 or not text:
            continue
        if (not core_ocr.is_devanagari(text) and len(text) >= 2
                and score < 0.7):
            continue
        x1, y1, x2, y2 = (int(v) for v in word.bbox)
        lines.append({
            "text": text,
            "x": x1,
            "y": y1,
            "w": max(x2 - x1, 1),
            "h": max(y2 - y1, 1),
            "conf": round(score, 3),
            "page": page,
        })
    lines.sort(key=lambda r: (r["y"], r["x"]))
    if log:
        log(f"[ocr] {Path(image_path).name}: {len(lines)} lines")
    return lines


def ocr_pngs(png_paths: list[Path], log=None) -> list[dict]:
    """OCR a sequence of page PNGs; page index is 1-based by list order."""
    engine = _ocr_engine()
    out: list[dict] = []
    for i, p in enumerate(png_paths, 1):
        out.extend(ocr_image(p, engine=engine, page=i, log=log))
    return out


def save_lines(lines: list[dict], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(lines, ensure_ascii=False, indent=1))


def load_lines(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text())
