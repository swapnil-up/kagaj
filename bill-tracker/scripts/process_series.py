"""Extract metric-series tables from the historical DoFE report PDFs.

Reads the 5 narrative reports under output/migration/reports/, pulls every
name × fiscal-year matrix (labour approvals, deaths, deaths-by-cause,
disability compensation, complaints, assistance), and writes the tracked long
panel to migration/series.csv.

  python process_series.py
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from config import MIGRATION_DATA_DIR, MIGRATION_OUTPUT_DIR  # noqa: E402

from migration_parser.series import extract_series  # noqa: E402

REPORT_DIR = MIGRATION_OUTPUT_DIR / "reports"
REPORTS = [
    "status_2013_14",
    "status_2014_15",
    "status_2015_17",
    "country_intro_2019",
    "migration_2020",
]

COLUMNS = [
    "report", "source_page", "caption", "metric", "dimension", "unit",
    "name", "fiscal_year", "gender", "count", "note",
]


def main() -> int:
    all_rows: list[dict] = []
    all_problems: list[str] = []
    for report in REPORTS:
        path = REPORT_DIR / f"{report}.pdf"
        if not path.exists():
            print(f"  [missing] {path}", file=sys.stderr)
            continue
        rows, problems = extract_series(str(path), report)
        all_rows.extend(rows)
        all_problems.extend(problems)
        print(f"[{report}] {len(rows)} rows, {len(problems)} problems",
              file=sys.stderr)

    MIGRATION_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = MIGRATION_DATA_DIR / "series.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} rows to {out}", file=sys.stderr)
    if all_problems:
        print(f"{len(all_problems)} verification problems:", file=sys.stderr)
        for p in all_problems[:20]:
            print(f"  {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
