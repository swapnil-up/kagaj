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

import numpy as np

DEVANAGARI_RE = None  # compiled lazily


def _ocr_engine():
    from paddleocr import PaddleOCR  # heavy; import on first use

    return PaddleOCR(
        text_recognition_model_name="devanagari_PP-OCRv5_mobile_rec",
        text_detection_model_name="PP-OCRv5_mobile_det",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def _dev_ratio(text: str) -> float:
    global DEVANAGARI_RE
    import re

    if DEVANAGARI_RE is None:
        DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
    return len(DEVANAGARI_RE.findall(text)) / max(len(text), 1)


def ocr_image(image_path: str | Path, engine=None, page: int = 1,
              log=None) -> list[dict]:
    """OCR one PNG; return line dicts sorted by (y, x)."""
    from PIL import Image

    engine = engine or _ocr_engine()
    img = Image.open(image_path)
    result = engine.predict(np.array(img))

    lines: list[dict] = []
    for record in result:
        texts = record["rec_texts"]
        scores = record["rec_scores"]
        boxes = record["rec_boxes"]
        for i in range(len(texts)):
            t = texts[i].strip()
            s = float(scores[i])
            if s < 0.3 or not t:
                continue
            if _dev_ratio(t) < 0.4 and len(t) >= 2 and s < 0.7:
                continue
            x1, y1, x2, y2 = (int(boxes[i][j]) for j in range(4))
            lines.append({
                "text": t,
                "x": x1,
                "y": y1,
                "w": max(x2 - x1, 1),
                "h": max(y2 - y1, 1),
                "conf": round(s, 3),
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
