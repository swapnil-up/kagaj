#!/usr/bin/env python3
"""
OCR nep-eng.pdf and extract clean English-Nepali bilingual word pairs.
Self-contained — does not depend on pdf_to_text.py.

Resumes automatically — saves after each page. Cancel anytime and re-run.

Usage:
  ocr-env/bin/python dictionary/extract_pairs.py                     # all 148 pages
  ocr-env/bin/python dictionary/extract_pairs.py --pages 1-5          # first 5
  ocr-env/bin/python dictionary/extract_pairs.py --pages 1,3,5        # specific pages
  ocr-env/bin/python dictionary/extract_pairs.py --inspect            # show column layout
"""

import argparse
import re
import sys
from pathlib import Path

import numpy as np
from pdf2image import convert_from_path

from kagaj_core import ocr as core_ocr

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "dictionary-data"
PDF_PATH = DATA_DIR / "nep-eng.pdf"

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

_ocr = None


def get_ocr():
    global _ocr
    if _ocr is None:
        _ocr = core_ocr.create_engine()
    return _ocr

DEVANAGARI_X_MIN = 700
DEVANAGARI_X_MAX = 1200


def ocr_page(img) -> list:
    arr = np.array(img)
    detections = []
    for word in core_ocr.ocr_array(get_ocr(), arr):
        x1, y1, x2, y2 = [int(v) for v in word.bbox]
        detections.append({
            "x": (x1 + x2) / 2, "y": (y1 + y2) / 2,
            "x1": x1, "y1": y1, "x2": x2, "y2": y2, "text": word.text,
        })
    detections.sort(key=lambda d: (d["y"], d["x"]))
    return detections


def inspect_layout(detections: list, img_width: int):
    xs = [d["x"] for d in detections]
    if not xs:
        print("  No detections"); return
    xs.sort()
    print(f"  X range: {min(xs):.0f} – {max(xs):.0f} (img width: {img_width})")
    gaps = [(xs[i] + xs[i+1]) / 2 for i in range(len(xs)-1) if xs[i+1] - xs[i] > 80]
    if gaps:
        print(f"  Column gaps at: {', '.join(f'{g:.0f}' for g in gaps)}")
    print(f"  Detections: {len(detections)}")
    print("  First 15:")
    for d in detections[:15]:
        print(f"    y={d['y']:6.0f}  x={d['x']:6.0f}  {d['text'][:70]}")


def group_into_rows(detections: list, tol: float = 16) -> list:
    if not detections:
        return []
    rows = []
    cur = [detections[0]]
    for d in detections[1:]:
        if abs(d["y"] - cur[-1]["y"]) <= tol:
            cur.append(d)
        else:
            rows.append(sorted(cur, key=lambda x: x["x"]))
            cur = [d]
    if cur:
        rows.append(sorted(cur, key=lambda x: x["x"]))
    return rows


def has_devanagari_column(row: list) -> bool:
    for d in row:
        if DEVANAGARI_X_MIN <= d["x"] <= DEVANAGARI_X_MAX and DEVANAGARI_RE.search(d["text"]):
            return True
    return False


def clean_trailing_junk(s: str) -> str:
    return re.sub(r'[\d\[\]\(\)\{\}\.\#\$@\*\+\=\!\?\/\\|&%^~`<>:;\"\'_]+$', '', s).strip()


def process_page(img, page_num: int) -> list:
    """OCR one page and return list of (english, nepali) pairs."""
    detections = ocr_page(img)
    rows = group_into_rows(detections)
    pairs = []
    current = None
    for row in rows:
        is_new = has_devanagari_column(row)
        eng = re.sub(r'\s+', ' ', " ".join(
            d["text"] for d in row if not DEVANAGARI_RE.search(d["text"])
        )).strip()
        nep = re.sub(r'\s+', ' ', " ".join(
            d["text"] for d in row if DEVANAGARI_RE.search(d["text"])
        )).strip()
        if is_new:
            if current:
                en, ne = current
                if en and ne and len(ne) >= 2:
                    pairs.append((clean_trailing_junk(en), ne))
            current = [eng, nep]
        else:
            if current and eng:
                current[0] = re.sub(r'\s+', ' ', current[0] + " " + eng)
            if current and nep:
                current[1] = re.sub(r'\s+', ' ', current[1] + " " + nep)
    if current:
        en, ne = current
        if en and ne and len(ne) >= 2:
            pairs.append((clean_trailing_junk(en), ne))
    return pairs


def load_progress(progress_path: Path) -> set:
    if progress_path.exists():
        return {int(line.strip()) for line in progress_path.read_text().splitlines() if line.strip()}
    return set()


def save_progress(progress_path: Path, page: int):
    with open(progress_path, "a", encoding="utf-8") as f:
        f.write(f"{page}\n")


def append_pairs(output_path: Path, pairs: list):
    with open(output_path, "a", encoding="utf-8") as f:
        for en, ne in pairs:
            f.write(f"{en}\t{ne}\n")


def main():
    parser = argparse.ArgumentParser(description="Extract bilingual pairs from nep-eng.pdf")
    parser.add_argument("--pages", help="Range like 1-5 or list 1,3,5")
    parser.add_argument("--inspect", action="store_true", help="Show layout for 3 pages")
    parser.add_argument("--reset", action="store_true", help="Clear progress and restart")
    parser.add_argument("-o", "--output", help="Output file")
    args = parser.parse_args()

    if not PDF_PATH.exists():
        print(f"Error: {PDF_PATH} not found"); sys.exit(1)

    page_list = None
    if args.pages:
        if "-" in args.pages:
            a, b = args.pages.split("-")
            page_list = list(range(int(a), int(b) + 1))
        else:
            page_list = [int(p) for p in args.pages.split(",")]

    if args.inspect:
        images = convert_from_path(str(PDF_PATH), dpi=300, first_page=1, last_page=3)
        for i, img in enumerate(images):
            print(f"\n--- Page {i+1} ---")
            dets = ocr_page(img)
            inspect_layout(dets, img.size[0])
            rows = group_into_rows(dets)
            print(f"  Rows: {len(rows)}")
            for row in rows[:12]:
                is_new = has_devanagari_column(row)
                eng = re.sub(r'\s+', ' ', " ".join(
                    d["text"] for d in row if not DEVANAGARI_RE.search(d["text"])
                )).strip()
                nep = re.sub(r'\s+', ' ', " ".join(
                    d["text"] for d in row if DEVANAGARI_RE.search(d["text"])
                )).strip()
                tag = "NEW" if is_new else "   "
                print(f"  [{tag}] EN: {eng[:60]}")
                if nep:
                    print(f"        NE: {nep[:60]}")
        return

    out_path = Path(args.output or SCRIPT_DIR / "eng_nep_pairs.txt")
    progress_path = out_path.with_suffix(".progress")

    total_pages = 148
    pages_to_process = list(range(1, total_pages + 1))
    if page_list:
        pages_to_process = page_list

    if args.reset:
        progress_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)
        print("Progress reset.")

    done = load_progress(progress_path)
    remaining = [p for p in pages_to_process if p not in done]

    if not remaining:
        print(f"All {len(done)} pages already done. Use --reset to redo.")
        print(f"Output: {out_path}")
        return

    print(f"OCR: {PDF_PATH}")
    print(f"Total: {len(pages_to_process)} pages, done: {len(done)}, remaining: {len(remaining)}")
    print(f"Output: {out_path}")
    print()

    # Load remaining pages in batches of 1 to allow granular resume
    for page_num in remaining:
        print(f"  Page {page_num}/{total_pages}...", end=" ", flush=True)
        img = convert_from_path(str(PDF_PATH), dpi=300, first_page=page_num, last_page=page_num)[0]
        pairs = process_page(img, page_num)
        append_pairs(out_path, pairs)
        save_progress(progress_path, page_num)
        print(f"{len(pairs)} pairs")

    total = len(load_progress(progress_path))
    print(f"\nDone. {total} pages → {out_path}")


if __name__ == "__main__":
    main()
