"""Extract metric-series tables from the historical DoFE report PDFs.

Reads the 5 narrative reports under output/migration/reports/, pulls every
name × fiscal-year matrix (labour approvals, deaths, deaths-by-cause,
disability compensation, complaints, assistance), and writes the tracked long
panel to datasets/labour-migration/series.csv.

  python -m migration_parser series [--no-download]
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import requests
import urllib3

from ..paths import MIGRATION_DIR, MIGRATION_REPORTS, MIGRATION_REPORTS_DIR
from ..series import extract_series, series_key

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
HEADERS = {"User-Agent": "Mozilla/5.0"}

REPORTS = list(MIGRATION_REPORTS)

COLUMNS = [
    "series_key", "report", "source_page", "caption", "metric", "dimension",
    "name", "fiscal_year", "unit", "year_basis", "gender", "count", "note",
]


def ensure_reports(download: bool = True) -> list[tuple[str, Path]]:
    """Return (report, path) for each report, downloading any missing PDFs."""
    MIGRATION_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[tuple[str, Path]] = []
    for report in REPORTS:
        path = MIGRATION_REPORTS_DIR / f"{report}.pdf"
        if (not path.exists() or path.stat().st_size <= 1000) and download:
            url = MIGRATION_REPORTS[report]
            r = requests.get(url, headers=HEADERS, timeout=180, verify=True)
            r.raise_for_status()
            path.write_bytes(r.content)
            print(f"downloaded {report}: {len(r.content) / 1024:.0f} KB", file=sys.stderr)
        out.append((report, path))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    download = "--no-download" not in argv

    all_rows: list[dict] = []
    all_problems: list[str] = []
    for report, path in ensure_reports(download):
        if not path.exists():
            print(f"  [missing] {path}", file=sys.stderr)
            continue
        rows, problems = extract_series(str(path), report)
        all_rows.extend(rows)
        all_problems.extend(problems)
        print(f"[{report}] {len(rows)} rows, {len(problems)} problems",
              file=sys.stderr)

    for row in all_rows:
        row["series_key"] = series_key(row)

    MIGRATION_DIR.mkdir(parents=True, exist_ok=True)
    out = MIGRATION_DIR / "series.csv"
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
