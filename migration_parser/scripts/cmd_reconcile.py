"""Cross-document reconciliation for the migration panel.

Applies the documented rule in ``datasets/labour-migration/reconciliation.json`` and:
  1. collapses rows that resolve to the same canonical entity within one document
     (e.g. the source's ``Combodia`` + ``Cambodia`` typo-rows) by summing counts,
  2. asserts no canonical key is produced by more than one document (no
     cross-document double count after the Table X year override),
  3. reconciles overlapping sources (annual vs months; country-vs-district pairs),
  4. writes ``datasets/labour-migration/panel_canonical.csv`` (additive component detail only) and
     ``datasets/labour-migration/panel_rollup.csv`` (aggregates, measures, printed totals), both
     gitignored.

Key = (granularity, reconciled_fiscal_year, period_ad_start, section,
       name_canonical, gender, channel_canonical, row_type). Rows whose entity
could not be resolved are keyed additionally by (doc_id, sn) so they stay
distinct; source-clipped names are also suffixed at normalisation time so
``name_canonical`` itself never collides across entities.

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


def split_primary_rollup(canonical: list[dict]) -> tuple[list[dict], list[dict]]:
    """Primary = additive component detail rows; rollup = everything else.

    Shipping aggregates/totals/measures in the same file as their components makes
    a naive ``groupby(channel).sum()`` double-count. The primary file therefore
    contains only ``row_type=='detail'`` rows whose ``channel_class=='component'``
    (which are guaranteed to sum to Total-with-Re-Entry); all aggregate, measure
    and printed-total rows go to the rollup companion.
    """
    def is_primary(r: dict) -> bool:
        return r["row_type"] == "detail" and r["channel_class"] == "component"

    primary = [r for r in canonical if is_primary(r)]
    rollup = [r for r in canonical if not is_primary(r)]
    return primary, rollup


def assert_sum_safe(primary: list[dict]) -> None:
    bad_class = sorted({r["channel_class"] for r in primary} - {"component"})
    bad_type = sorted({r["row_type"] for r in primary} - {"detail"})
    if bad_class or bad_type:
        raise SystemExit(f"panel_canonical not sum-safe: classes={bad_class} row_types={bad_type}")


def assert_unique_key(rows: list[dict], cols: list[str]) -> None:
    key_cols = normalize.dedup_key_columns()
    missing = [c for c in key_cols if c not in cols]
    if missing:
        raise SystemExit(f"dedup_key columns missing from output: {missing}")
    seen: dict[tuple, int] = defaultdict(int)
    for r in rows:
        seen[tuple(r[c] for c in key_cols)] += 1
    dups = {k: n for k, n in seen.items() if n > 1}
    if dups:
        example = next(iter(dups))
        raise SystemExit(f"panel_canonical not unique on dedup_key ({len(dups)} duplicate "
                         f"groups, e.g. {example})")


def main(argv: list[str] | None = None) -> int:
    rows, cols = _load()
    print(f"loaded {len(rows)} rows from panel_normalized.csv")
    fails = overlap_report(rows)
    canonical, cross_doc = reconcile(rows)
    fails += cross_doc

    try:
        assert_unique_key(canonical, cols + EXTRA)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 1

    primary, rollup = split_primary_rollup(canonical)
    try:
        assert_sum_safe(primary)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 1

    for path, data in ((MIGRATION_DIR / "panel_canonical.csv", primary),
                       (MIGRATION_DIR / "panel_rollup.csv", rollup)):
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols + EXTRA)
            w.writeheader()
            w.writerows(data)
        print(f"wrote {path.name} ({len(data)} rows)")

    if fails:
        print(f"AUDIT FAILED: {fails} problem(s)")
        return 1
    print("AUDIT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
