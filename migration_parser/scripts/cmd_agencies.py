"""Extract pre-approval (पूर्व अनुमति) and institutional (संस्थागत) tables.

Writes:
* country-summary rows for #030–#032 into output/migration/docs/ (picked up by
  the panel rebuild → datasets/labour-migration/panel.csv, channel="preapproval");
* agency-level detail (pre-approval + institutional) into the tracked
  datasets/labour-migration/agencies.csv.

  python -m migration_parser agencies
"""

from __future__ import annotations

import csv
import json
import sys

from ..agencies import (
    AGENCY_COLUMNS,
    INSTITUTIONAL,
    PREAPPROVAL,
    extract_detail,
    extract_institutional,
    extract_summary,
)
from ..paths import MIGRATION_MANIFEST
from . import cmd_process as process


def _urls() -> dict[str, str]:
    man = json.loads(MIGRATION_MANIFEST.read_text())
    return {f"{e['serial']:03d}": e.get("pdf_url", "") for e in man}


def main(argv: list[str] | None = None) -> int:
    urls = _urls()
    pdfs = process.PDFS_DIR
    both: list[dict] = []

    for f, cfg in PREAPPROVAL.items():
        path = pdfs / f"{f}.pdf"
        if not path.exists():
            print(f"  [missing] {path}", file=sys.stderr)
            continue
        url = urls.get(f[:3], "")
        summary, sp = extract_summary(str(path), cfg, url)
        detail, dp = extract_detail(str(path), cfg, url)
        process._write_csv(
            summary, process.DOCS_DIR / f"{cfg['doc_id']}.csv")
        both.extend(detail)
        print(f"[{cfg['doc_id']}] summary={len(summary)} detail={len(detail)} "
              f"problems={len(sp) + len(dp)}", file=sys.stderr)
        for p in sp + dp:
            print(f"    [problem] {p}", file=sys.stderr)

    for f, cfg in INSTITUTIONAL.items():
        path = pdfs / f"{f}.pdf"
        if not path.exists():
            print(f"  [missing] {path}", file=sys.stderr)
            continue
        recs, probs = extract_institutional(str(path), cfg, urls.get(f[:3], ""))
        both.extend(recs)
        print(f"[{cfg['doc_id']}] agency rows={len(recs)} problems={len(probs)}",
              file=sys.stderr)
        for p in probs:
            print(f"    [problem] {p}", file=sys.stderr)

    out = process.MIGRATION_DATA_DIR / "agencies.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=AGENCY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(both)
    print(f"\nWrote {len(both)} rows to {out}", file=sys.stderr)

    process.rebuild_panel()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
