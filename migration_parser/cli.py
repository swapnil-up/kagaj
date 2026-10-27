"""CLI: migration <command> ...

Commands:
  extract    extract + verify country/district rows from PDFs (library demo)
  scrape     scrape the DoFE listings into the manifest
  process    download + extract + verify the live wide tables
  annex      extract the migration_2020 Annex tables
  backfill   extract archive.org reports (family (a): monthly country-wise)
  archivepanel  build tracked panel_archive.csv.gz from verified backfill docs
  agencies   extract pre-approval / institutional agency detail
  series     extract historical metric-series tables
  normalize  add canonical entity/channel/fiscal-year columns
  reconcile  cross-document reconciliation + dedup -> panel_canonical.csv
  verify     panel-wide math-invariant audit -> verification.json
  crosscheck cross-check against opendatanepal -> crosscheck.json
  driftcheck detect source-PDF revision drift vs recorded hashes
  provenance freeze/verify per-page source fingerprints (offline check)
  audit      Phase 0 research data audit -> output/migration/research/
  patterns   Phase 1 pattern scan -> output/migration/research/
  build      one-command reproducible build + packaging
"""

import argparse
import csv
import json
import os
import sys

from .parser import extract_doc, melt
from .verify import verify


def _dispatch(stage: str) -> callable:
    if stage == "scrape":
        from .scripts import cmd_scrape as m
    elif stage == "process":
        from .scripts import cmd_process as m
    elif stage == "annex":
        from .scripts import cmd_annex as m
    elif stage == "backfill":
        from .scripts import cmd_backfill as m
    elif stage == "archivepanel":
        from .scripts import cmd_archive_panel as m
    elif stage == "agencies":
        from .scripts import cmd_agencies as m
    elif stage == "series":
        from .scripts import cmd_series as m
    elif stage == "normalize":
        from .scripts import cmd_normalize as m
    elif stage == "reconcile":
        from .scripts import cmd_reconcile as m
    elif stage == "verify":
        from .scripts import cmd_verify as m
    elif stage == "crosscheck":
        from .scripts import cmd_crosscheck as m
    elif stage == "driftcheck":
        from .scripts import cmd_driftcheck as m
    elif stage == "provenance":
        from .scripts import cmd_provenance as m
    elif stage == "audit":
        from .scripts import cmd_audit as m
    elif stage == "patterns":
        from .scripts import cmd_patterns as m
    elif stage == "build":
        from .scripts import cmd_build as m
    else:  # pragma: no cover - guarded by argparse choices
        raise SystemExit(f"unknown stage: {stage}")
    return m.main


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


STAGES = ("scrape", "process", "annex", "backfill", "archivepanel",
          "agencies", "series",
          "normalize", "reconcile", "verify", "crosscheck", "driftcheck",
          "provenance", "audit", "patterns", "build")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="migration")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="extract + verify country/district rows")
    e.add_argument("pdfs", nargs="+")
    e.add_argument("-o", "--output", help="write tidy CSV to this path")
    e.add_argument("--json", help="also dump tidy rows as JSON")
    e.set_defaults(func=cmd_extract)

    for name in STAGES:
        s = sub.add_parser(name, help=f"run the {name} pipeline stage",
                           add_help=False)
        s.set_defaults(func=_dispatch(name))

    args, extra = p.parse_known_args(argv)
    if args.cmd == "extract":
        return args.func(args)
    # forward stage-specific flags to the stage's own parser
    return args.func(extra)


if __name__ == "__main__":
    sys.exit(main())
