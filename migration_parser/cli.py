"""CLI: migration extract <pdf> ... | migration verify <pdf> ..."""

import argparse
import csv
import json
import os
import sys

from .parser import extract_doc, melt
from .verify import verify


def cmd_extract(args) -> int:
    rc = 0
    all_rows: list[dict] = []
    for pdf in args.pdfs:
        if not os.path.exists(pdf):
            print(f"Error: {pdf} not found", file=sys.stderr)
            rc = 1
            continue
        result = extract_doc(pdf)
        report = verify(result)
        nc = sum(1 for r in result.wide_rows if r.section == "country")
        nd = sum(1 for r in result.wide_rows if r.section == "district")
        ok = report.ok and not result.problems
        status = "OK " if ok else "FAIL"
        extra = f" +{len(result.problems)} orphan" if result.problems else ""
        print(f"[{status}] {os.path.basename(pdf)}: country={nc} district={nd} "
              f"| {report.summary()}{extra}", file=sys.stderr)
        for c in report.failures[:10]:
            print(f"      {c}", file=sys.stderr)
        for p in result.problems[:10]:
            print(f"      {p}", file=sys.stderr)
        if not ok:
            rc = 1
        all_rows.extend(melt(result))

    if args.output and all_rows:
        _write_csv(all_rows, args.output)
        print(f"Wrote {len(all_rows)} rows to {args.output}", file=sys.stderr)
    if args.json and all_rows:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(all_rows, f, ensure_ascii=False, indent=2)
    return rc


def _write_csv(rows: list[dict], path: str) -> None:
    fields = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="migration")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="extract + verify country/district rows")
    e.add_argument("pdfs", nargs="+")
    e.add_argument("-o", "--output", help="write tidy CSV to this path")
    e.add_argument("--json", help="also dump tidy rows as JSON")
    e.set_defaults(func=cmd_extract)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
