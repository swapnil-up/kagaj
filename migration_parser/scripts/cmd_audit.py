"""Run the Phase 0 research data audit."""

from __future__ import annotations

import argparse
import sys

from ..research.audit import build_audit, write_outputs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="migration audit")
    p.add_argument("--out", default=None, help="output directory")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    report = build_audit()
    paths = write_outputs(report, args.out)
    critical = sum(
        1 for issue in report["issues"] if issue["severity"] == "critical")
    warnings = sum(
        1 for issue in report["issues"] if issue["severity"] == "warning")
    print(f"wrote {paths['html']}")
    print(f"wrote {paths['json']}")
    print(f"wrote {paths['markdown']}")
    print(f"safe rows={report['panel']['rows_safe']} "
          f"docs={report['panel']['docs_safe']} "
          f"critical={critical} warnings={warnings}")
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
