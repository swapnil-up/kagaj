"""Cross-document reconciliation for the migration panel.

Applies the documented rule in ``migration/reconciliation.json`` and:
  1. collapses rows that resolve to the same canonical entity within one document
     (e.g. the source's ``Combodia`` + ``Cambodia`` typo-rows) by summing counts,
  2. asserts no canonical key is produced by more than one document (no
     cross-document double count after the Table X year override),
  3. reconciles overlapping sources (annual vs months; country-vs-district pairs),
  4. writes ``migration/panel_canonical.csv`` (gitignored).

Key = (granularity, reconciled_fiscal_year, period_ad_start, section,
       name_canonical, gender, channel_canonical, row_type). Rows whose entity
could not be resolved are keyed additionally by (doc_id, sn) so they stay
distinct.

    python -m migration_parser reconcile
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict

from .. import normalize
from ..paths import MIGRATION_DIR

EXTRA = ["merged_rows", "raw_names"]


def _load() -> tuple[list[dict], list[str]]:
    with (MIGRATION_DIR / "panel_normalized.csv").open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r), r.fieldnames


def _totals(rows, doc_id: str, channel: str, gender: str = "total") -> int:
    return sum(int(x["count"]) for x in rows
               if x["doc_id"] == doc_id and x["row_type"] == "detail"
               and x["gender"] == gender and x["channel_canonical"] == channel)


def reconcile(rows: list[dict]) -> tuple[list[dict], int]:
    key_cols = normalize.dedup_key_columns()
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for x in rows:
        k = tuple(x[c] for c in key_cols)
        if x["entity_resolved"] != "true":
            k = k + (x["doc_id"], x["sn"])
        groups[k].append(x)

    canonical: list[dict] = []
    merges = 0
    cross_doc = 0
    for g in groups.values():
        out = dict(g[0])
        if len(g) > 1:
            merges += 1
            docs = {r["doc_id"] for r in g}
            if len(docs) > 1:
                cross_doc += 1
                print(f"  CROSS-DOC {out['name_canonical']} {out['granularity']} "
                      f"{out['reconciled_fiscal_year']} {out['channel_canonical']} docs={docs}")
        out["count"] = str(sum(int(r["count"]) for r in g))
        out["merged_rows"] = str(len(g))
        out["raw_names"] = ";".join(sorted({r["name"] for r in g}))
        canonical.append(out)
    print(f"[1] {len(rows)} rows -> {len(canonical)} canonical keys "
          f"({merges} entity merges, {cross_doc} cross-document conflicts)")
    return canonical, cross_doc


def overlap_report(rows: list[dict]) -> int:
    fails = 0
    for g in normalize.reconciliation()["overlap_groups"]:
        if g["kind"] == "annual_vs_months":
            ann = g["annual"][0]
            for chan in ("recruiting_agency", "total_with_reentry"):
                a = _totals(rows, ann, chan)
                ms = sum(_totals(rows, m, chan) for m in g["months"])
                ok = abs(a - ms) <= max(50, a * 0.001)
                print(f"[2] {g['fiscal_year']} {chan}: annual {ann}={a} vs Σmonths={ms} "
                      f"({'match' if ok else 'DIFF'})")
                fails += 0 if ok else 1
        elif g["kind"] == "dimension_pair":
            a = _totals(rows, g["country"][0], "recruiting_agency")
            b = _totals(rows, g["district"][0], "recruiting_agency")
            print(f"[2] {g['fiscal_year']} RA: country={a} vs district={b}")
    return fails


def main(argv: list[str] | None = None) -> int:
    rows, cols = _load()
    print(f"loaded {len(rows)} rows from panel_normalized.csv")
    fails = overlap_report(rows)
    canonical, cross_doc = reconcile(rows)
    fails += cross_doc
    out = MIGRATION_DIR / "panel_canonical.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols + EXTRA)
        w.writeheader()
        w.writerows(canonical)
    print(f"wrote {out.name} ({len(canonical)} rows)")
    if fails:
        print(f"AUDIT FAILED: {fails} problem(s)")
        return 1
    print("AUDIT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
