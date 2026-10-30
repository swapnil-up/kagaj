"""PaddleOCR extraction for DDA drug price documents.

Runs PaddleOCR with Devanagari model on PNG images, producing clean text
with bounding box coordinates for spatial column classification.

Usage:
    python ocr_dda.py <image.png> [--outdir output/dda]
    python ocr_dda.py output/dda/gazette_page1.png
"""

import json
import sys
from pathlib import Path

from kagaj_core import ocr as core_ocr

DEFAULT_OUTDIR = Path(__file__).resolve().parent.parent.parent / "output" / "dda"

_ocr_instance = None


def get_ocr():
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = core_ocr.create_engine()
    return _ocr_instance


def ocr_image(image_path: Path, page: int = 0) -> list[dict]:
    """Run PaddleOCR on a single PNG image.

    Returns list of dicts: {text, x, y, w, h, confidence, page}
    sorted by (y, x) for top-to-bottom, left-to-right reading order.
    """
    words = core_ocr.ocr_image(get_ocr(), image_path, page=page)

    lines = []
    for word in words:
        text = word.text
        score = word.score
        if score < 0.3 or not text:
            continue
        if (not core_ocr.is_devanagari(text) and len(text) >= 2
                and score < 0.7):
            continue
        x1, y1, x2, y2 = [int(v) for v in word.bbox]
        lines.append({
            "text": text,
            "x": x1,
            "y": y1,
            "w": max(x2 - x1, 60),
            "h": max(y2 - y1, 14),
            "confidence": round(score, 3),
            "page": page,
        })

    lines.sort(key=lambda r: (r["y"], r["x"]))
    return lines


def ocr_images(image_paths: list[Path], outdir: Path = DEFAULT_OUTDIR) -> dict:
    """OCR multiple images and save results.

    Returns dict keyed by image stem with per-image OCR results.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    all_results = {}
    for page, img_path in enumerate(image_paths, 1):
        stem = img_path.stem
        print(f"[ocr] processing {img_path.name}...", file=sys.stderr)
        lines = ocr_image(img_path, page=page)
        print(f"  -> {len(lines)} lines", file=sys.stderr)
        all_results[stem] = {
            "image": str(img_path),
            "lines": lines,
            "line_count": len(lines),
        }
        # Save per-image OCR JSON
        out_path = outdir / f"{stem}_ocr.json"
        out_path.write_text(json.dumps(all_results[stem], indent=2, ensure_ascii=False))
        print(f"  -> saved {out_path}", file=sys.stderr)
    return all_results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="OCR DDA drug price images")
    parser.add_argument("images", nargs="+", type=Path, help="PNG image(s) to OCR")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=DEFAULT_OUTDIR,
        help="Output directory (default: output/dda/)",
    )
    args = parser.parse_args()

    for img in args.images:
        if not img.exists():
            print(f"[error] file not found: {img}", file=sys.stderr)
            sys.exit(1)

    results = ocr_images(args.images, outdir=args.outdir)
    total_lines = sum(r["line_count"] for r in results.values())
    print(f"[done] {len(results)} images, {total_lines} total lines", file=sys.stderr)


if __name__ == "__main__":
    main()
