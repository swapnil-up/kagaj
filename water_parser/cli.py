"""CLI: ``python -m water_parser.cli <command>``.

Commands:
  scrape    fetch the KUKL schedule page → datasets/water/manifest.json
  process   download + extract selected manifest entries
  render    render PDF entries to page PNGs for mark-boxes
  validate  flag suspicious zones in per-branch extracts
  build     merge per-branch extracts → datasets/water/schedule.json
  list      show manifest entries and their status
"""

from __future__ import annotations

import argparse
import json
import sys

from . import paths


def _dispatch(stage: str):
    if stage == "scrape":
        from .scripts import cmd_scrape as m
    elif stage == "process":
        from .scripts import cmd_process as m
    elif stage == "render":
        from .scripts import cmd_render as m
    elif stage == "regions":
        from .scripts import cmd_regions as m
    elif stage == "validate":
        from .scripts import cmd_validate as m
    elif stage == "build":
        from .scripts import cmd_build as m
    else:  # pragma: no cover - guarded by argparse
        raise SystemExit(f"unknown command: {stage}")
    return m


def _cmd_list(args) -> int:
    if not paths.MANIFEST.exists():
        print("no manifest — run `scrape` first")
        return 1
    entries = json.loads(paths.MANIFEST.read_text())["entries"]
    for e in entries:
        if args.month and e["month_key"].lower() != args.month.lower():
            continue
        if args.branch and args.branch.lower() not in e["branch"].lower():
            continue
        print(f"{e['status']:<12} {e['month_key']:<12} {e['branch']:<16} {e['kind']:<5} {e['filename']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="water_parser.cli", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="stage", required=True)

    p_scrape = sub.add_parser("scrape", help="fetch the KUKL schedule page")
    p_scrape.set_defaults(func=lambda a: _dispatch("scrape").run(a))

    p_proc = sub.add_parser("process", help="download + extract selected entries")
    p_proc.add_argument("--month", help="only this month_key, e.g. 2083_Ashoj")
    p_proc.add_argument("--branch", help="substring match on branch name")
    p_proc.add_argument("--limit", type=int, help="process at most N entries")
    p_proc.add_argument("--force", action="store_true", help="reprocess already-done entries")
    p_proc.set_defaults(func=lambda a: _dispatch("process").run(a))

    p_build = sub.add_parser("build", help="merge per-branch extracts")
    p_build.set_defaults(func=lambda a: _dispatch("build").run(a))

    p_render = sub.add_parser("render", help="render PDFs to PNG for mark-boxes")
    p_render.add_argument("--month")
    p_render.add_argument("--branch")
    p_render.add_argument("--force", action="store_true", help="re-render existing")
    p_render.set_defaults(func=lambda a: _dispatch("render").run(a))

    p_regions = sub.add_parser("regions", help="auto-propose PDF column regions")
    p_regions.add_argument("--branch")
    p_regions.set_defaults(func=lambda a: _dispatch("regions").run(a))

    p_val = sub.add_parser("validate", help="flag suspicious zones")
    p_val.add_argument("--branch")
    p_val.add_argument("-v", "--verbose", action="store_true",
                       help="list each flagged zone")
    p_val.set_defaults(func=lambda a: _dispatch("validate").run(a))

    p_list = sub.add_parser("list", help="show manifest entries")
    p_list.add_argument("--month")
    p_list.add_argument("--branch")
    p_list.set_defaults(func=_cmd_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
