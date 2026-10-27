"""Run the Phase 1 migration pattern scan."""

from __future__ import annotations

import argparse
import sys

from ..research.pattern_book import write_outputs
from ..research.patterns import build_patterns


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="migration patterns")
    p.add_argument("--out", default=None, help="output directory")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    report = build_patterns()
    paths = write_outputs(report, args.out)
    print(f"wrote {paths['html']}")
    print(f"wrote {paths['json']}")
    print(f"wrote {paths['markdown']}")
    print(f"safe rows={report['basis']['rows']} "
          f"docs={report['basis']['documents']} "
          f"latest={report['basis']['latest_fy']} "
          f"hypotheses={len(report['hypotheses'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
