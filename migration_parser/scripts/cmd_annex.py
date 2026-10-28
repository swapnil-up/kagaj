"""Extract the migration_2020 Annex labour-approval tables into the panel.

The Nepal Labour Migration Report 2020 prints FY2017/18 & FY2018/19 labour
approvals in annexes that predate the live wide template (no S.N. column,
report-specific channel typologies, compact district Men/Women/Total tables).
This driver writes them as per-doc CSVs under output/migration/docs/ (picked up
automatically by the panel rebuild) and then rebuilds datasets/labour-migration/panel.csv.

  python -m migration_parser annex
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import requests
import urllib3

from ..annex import extract_annex
from ..paths import MIGRATION_REPORTS, MIGRATION_REPORTS_DIR
from . import cmd_process as process

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
HEADERS = {"User-Agent": "Mozilla/5.0"}
REPORT = "migration_2020"


def ensure_report() -> Path:
    MIGRATION_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = MIGRATION_REPORTS_DIR / f"{REPORT}.pdf"
    if path.exists() and path.stat().st_size > 1000:
        return path
    url = MIGRATION_REPORTS[REPORT]
    r = requests.get(url, headers=HEADERS, timeout=180, verify=True)
    r.raise_for_status()
    path.write_bytes(r.content)
    print(f"downloaded {REPORT}: {len(r.content) / 1024:.0f} KB", file=sys.stderr)
    return path


def main(argv: list[str] | None = None) -> int:
    path = ensure_report()
    rows, problems = extract_annex(str(path), MIGRATION_REPORTS[REPORT])

    docs = defaultdict(list)
    for r in rows:
        docs[r["doc_id"]].append(r)

    process.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for doc_id, drow in docs.items():
        name = doc_id.replace("report2020_annex_", "")
        process._write_csv(drow, process.DOCS_DIR / f"annex_{name}.csv")

    for doc_id in sorted(docs):
        n_c = sum(1 for r in docs[doc_id] if r["section"] == "country")
        n_d = sum(1 for r in docs[doc_id] if r["section"] == "district")
        print(f"[{doc_id}] {len(docs[doc_id])} rows (country={n_c} district={n_d})",
              file=sys.stderr)
    for p in problems:
        print(f"  [problem] {p}", file=sys.stderr)

    process.rebuild_panel()
    print(f"annex rows: {len(rows)}, problems: {len(problems)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
