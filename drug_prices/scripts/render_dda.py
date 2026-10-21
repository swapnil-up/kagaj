"""Render DDA PDF pages to PNG images for mark-boxes and OCR.

Usage:
    python render_dda.py <pdf_path> [--dpi 300] [--outdir output/dda]
    python render_dda.py output/dda/gazette.pdf
"""

import sys
from pathlib import Path

import pymupdf

DEFAULT_DPI = 300
DEFAULT_OUTDIR = Path(__file__).resolve().parent.parent.parent / "output" / "dda"


def render_pdf(pdf_path: Path, dpi: int = DEFAULT_DPI, outdir: Path = DEFAULT_OUTDIR) -> list[Path]:
    """Render each page of a PDF to a PNG file.

    Returns list of output PNG paths.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf_path)
    stem = pdf_path.stem
    zoom = dpi / 72
    mat = pymupdf.Matrix(zoom, zoom)
    paths = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat)
        out_path = outdir / f"{stem}_page{i + 1}.png"
        pix.save(out_path)
        paths.append(out_path)
        print(f"  rendered page {i + 1}/{len(doc)} -> {out_path}", file=sys.stderr)
    doc.close()
    return paths


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Render DDA PDF pages to PNG")
    parser.add_argument("pdf", type=Path, help="Path to PDF file")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="Render DPI (default: 300)")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=DEFAULT_OUTDIR,
        help="Output directory (default: output/dda/)",
    )
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"[error] file not found: {args.pdf}", file=sys.stderr)
        sys.exit(1)

    paths = render_pdf(args.pdf, dpi=args.dpi, outdir=args.outdir)
    print(f"[done] rendered {len(paths)} pages", file=sys.stderr)
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
