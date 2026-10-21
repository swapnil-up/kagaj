"""Spatial column classification for DDA drug price tables.

Uses user-marked column regions (from mark-boxes) to classify OCR text lines
into structured columns, building rows of drug data.

Usage:
    python spatial_dda.py <ocr.json> [--regions dda_column_regions.json]
    python spatial_dda.py output/dda/gazette_page1_ocr.json
"""

import json
import sys
from pathlib import Path

from config import DDA_COLUMN_REGIONS, load_env


def load_regions(regions_path: Path = DDA_COLUMN_REGIONS) -> dict:
    """Load column region definitions from JSON.

    Expected format (created by mark-boxes):
    {
        "gazette_table": {
            "dpi": 300,
            "columns": {
                "serial":    {"px": [left, top, right, bottom]},
                "drug_name": {"px": [left, top, right, bottom]},
                ...
            },
            "row_scan": {
                "y_start": <int>,
                "row_gap": <int>,
                "header_skip_y": <int>  // skip lines above this y
            }
        }
    }
    """
    if not regions_path.exists():
        print(f"[error] column regions not found: {regions_path}", file=sys.stderr)
        print(
            "  Run mark-boxes on a rendered page first to define columns.",
            file=sys.stderr,
        )
        sys.exit(1)
    return json.loads(regions_path.read_text())


def classify_line(x: int, y: int, w: int, columns: dict) -> str | None:
    """Determine which column a text line falls into based on x-center.

    Uses horizontal overlap: the column whose [left, right] range contains
    the line's center x-coordinate.
    """
    center_x = x + w / 2
    for col_name, region in columns.items():
        px = region["px"]
        left, right = px[0], px[2]
        if left <= center_x <= right:
            return col_name
    return None


def group_into_rows(
    lines: list[dict], row_gap: int = 40, y_start: int = 0
) -> list[list[dict]]:
    """Group OCR lines into rows based on vertical proximity.

    Lines with y-coordinates within row_gap pixels of each other are
    considered part of the same row.
    """
    if not lines:
        return []

    # Filter to lines after y_start
    filtered = [l for l in lines if l["y"] >= y_start]
    if not filtered:
        return []

    # Sort by y then x
    filtered.sort(key=lambda r: (r["y"], r["x"]))

    rows = []
    current_row = [filtered[0]]
    current_y = filtered[0]["y"]

    for line in filtered[1:]:
        if abs(line["y"] - current_y) <= row_gap:
            current_row.append(line)
        else:
            # Sort row by x for left-to-right order
            current_row.sort(key=lambda r: r["x"])
            rows.append(current_row)
            current_row = [line]
            current_y = line["y"]

    # Don't forget the last row
    current_row.sort(key=lambda r: r["x"])
    rows.append(current_row)

    return rows


def classify_rows(
    rows: list[list[dict]], columns: dict, header_skip_y: int = 0
) -> list[dict]:
    """Classify each row's lines into columns and build structured rows.

    Returns list of dicts, each dict keyed by column name with the text
    that fell into that column.
    """
    structured = []
    for row in rows:
        # Skip header rows (above header_skip_y)
        if row[0]["y"] < header_skip_y:
            continue

        row_data = {}
        for line in row:
            col = classify_line(line["x"], line["y"], line["w"], columns)
            if col:
                if col in row_data:
                    row_data[col] += " " + line["text"]
                else:
                    row_data[col] = line["text"]

        # Only include rows that have at least a drug name or price
        if row_data.get("drug_name") or row_data.get("price"):
            structured.append(row_data)

    return structured


def spatial_classify(
    ocr_result: dict, region_key: str = "gazette_table", regions: dict = None
) -> list[dict]:
    """Classify OCR lines into structured rows using column regions.

    Args:
        ocr_result: Dict from ocr_dda.py with "lines" list.
        region_key: Key in column regions JSON (e.g. "gazette_table").
        regions: Pre-loaded regions dict, or None to load from default path.

    Returns:
        List of structured row dicts.
    """
    if regions is None:
        regions = load_regions()

    if region_key not in regions:
        print(
            f"[error] region key '{region_key}' not found in {DDA_COLUMN_REGIONS}",
            file=sys.stderr,
        )
        print(
            f"  Available keys: {list(regions.keys())}",
            file=sys.stderr,
        )
        return []

    region = regions[region_key]
    columns = region["columns"]
    row_scan = region.get("row_scan", {})
    row_gap = row_scan.get("row_gap", 40)
    y_start = row_scan.get("y_start", 0)
    header_skip_y = row_scan.get("header_skip_y", 0)

    lines = ocr_result.get("lines", [])
    rows = group_into_rows(lines, row_gap=row_gap, y_start=y_start)
    structured = classify_rows(rows, columns, header_skip_y=header_skip_y)

    return structured


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Classify DDA OCR lines into structured columns"
    )
    parser.add_argument("ocr_json", type=Path, help="OCR result JSON from ocr_dda.py")
    parser.add_argument(
        "--regions",
        type=Path,
        default=DDA_COLUMN_REGIONS,
        help="Column regions JSON (default: dda_column_regions.json)",
    )
    parser.add_argument(
        "--key",
        default="gazette_table",
        help="Region key to use (default: gazette_table)",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help="Output directory (default: same as input)",
    )
    args = parser.parse_args()

    if not args.ocr_json.exists():
        print(f"[error] file not found: {args.ocr_json}", file=sys.stderr)
        sys.exit(1)

    regions = load_regions(args.regions)
    ocr_result = json.loads(args.ocr_json.read_text())
    structured = classify_rows(
        group_into_rows(ocr_result.get("lines", [])),
        regions[args.key]["columns"],
        regions[args.key].get("row_scan", {}).get("header_skip_y", 0),
    )

    outdir = args.outdir or args.ocr_json.parent
    out_path = outdir / args.ocr_json.name.replace("_ocr.json", "_rows.json")
    out_path.write_text(json.dumps(structured, indent=2, ensure_ascii=False))
    print(
        f"[done] {len(structured)} rows -> {out_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    load_env()
    main()
