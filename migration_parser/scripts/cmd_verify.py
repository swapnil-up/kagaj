"""Panel-wide verification pass.

Re-checks the math invariants of ``datasets/labour-migration/panel.csv`` independently of
extraction (see ``migration_parser.panel_verify``) and writes a tracked
``datasets/labour-migration/verification.json`` summary. Failures listed in
``datasets/labour-migration/reconciliation.json`` → ``known_arithmetic_errors`` are counted but
tolerated; any other failure is unexpected and makes the script exit non-zero.

    python -m migration_parser verify
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter

from .. import normalize
from ..panel_verify import verify_panel
from ..paths import MIGRATION_DIR

FIELDS = ("doc_id", "section", "name", "channel", "gender", "kind")


def _key(f) -> tuple:
    return tuple(getattr(f, c) for c in FIELDS)


def main(argv: list[str] | None = None) -> int:
    with (MIGRATION_DIR / "panel.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fails = verify_panel(rows)
    known = {
        tuple(e[c] for c in FIELDS)
        for e in normalize.reconciliation()["known_arithmetic_errors"]
    }
    unexpected = [f for f in fails if _key(f) not in known]

    by_kind = Counter(f.kind for f in fails)
    contract = "verified=True on a row means it came from a document whose extraction math audit passed"
    print(f"{len(rows)} rows; {len(fails)} panel-check failures "
          f"({len(fails) - len(unexpected)} known, {len(unexpected)} unexpected)")
    for kind, n in by_kind.most_common():
        print(f"  {kind}: {n}")
    for f in unexpected:
        print(f"  UNEXPECTED {f}")

    summary = {
        "rows": len(rows),
        "failures": len(fails),
        "known": len(fails) - len(unexpected),
        "unexpected": len(unexpected),
        "by_kind": dict(by_kind),
        "verified_contract": contract,
        "documents_unverified": sorted({r["doc_id"] for r in rows if r["verified"] != "True"}),
        "unexpected_detail": [vars(f) for f in unexpected],
        "known_detail": [vars(f) for f in fails if _key(f) in known],
    }
    (MIGRATION_DIR / "verification.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote datasets/labour-migration/verification.json ({contract})")
    return 1 if unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
