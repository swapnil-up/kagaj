"""Cross-check the DoFE panel against the (independent) opendatanepal CSVs.

opendatanepal digitised part of the same DoFE data (Nepal Labor Migration
Report 2022) into tidy CSVs. They are a **cross-check only** — never a source
for filling gaps (see MIGRATION_NOTES). This script joins opendata rows to the
panel on ``(fiscal_year, entity, channel, gender)`` and reports agreement.

Checks (entity is country unless noted):
  * ra_by_country          recruiting_agency / total      (opendata: RA by country)
  * women_renewing         individual_reentry / female    (opendata: women renewing)
  * new_approvals_total    total_without_reentry / total  (opendata: skill-profile
                                                           "Total Migrants (N)")
  * new_individual         individual_new / total         (NOT comparable: the
                            opendata file is a top-N per-year ranking — only 10-12
                            destinations listed each year — not the full country
                            distribution; reported for information only)

Writes ``migration/crosscheck.json``. Exits non-zero if any *comparable* check
misses the tolerance.

    python -m migration_parser crosscheck
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict

from .. import normalize
from ..paths import MIGRATION_DIR, MIGRATION_OPENDATA_DIR

OPENDATA = MIGRATION_OPENDATA_DIR
TOL = 0.005  # aggregate tolerance (0.5%)
AGG_LABELS = {"others", "other", "other countries", "gcc countries", "gcc", "total"}

CHECKS = [
    {"id": "ra_by_country",
     "file": "nepal-labor-migratio__labour-approvals-issued-through-recruitment-agencies-by-country-of-destination.csv",
     "entity": "Destination Country", "year": "Year", "value": "Number",
     "section": "country", "channel": "recruiting_agency", "gender": "total",
     "comparable": True},
    {"id": "women_renewing",
     "file": "nepal-labor-migratio__women-migrant-workers-renewing-labor-approvals.csv",
     "entity": "Country", "year": "Year", "value": "Number",
     "section": "country", "channel": "individual_reentry", "gender": "female",
     "comparable": True},
    {"id": "new_approvals_total",
     "file": "nepal-labor-migratio__labour-approvals-issued-by-skills-profile-and-destination.csv",
     "entity": "Destination", "year": "Fiscal Year", "value": "Total Migrants (N)",
     "section": "country", "channel": "total_without_reentry", "gender": "total",
     "comparable": True},
    {"id": "new_individual",
     "file": "nepal-labor-migratio__new-individual-labour-approvals-issued-by-country-of-destination.csv",
     "entity": "Destination Country", "year": "Year", "value": "Number",
      "section": "country", "channel": "individual_new", "gender": "total",
      "comparable": False,
      "reason": "opendata dataset is a top-N per-year ranking (10-12 destinations/yr), "
                "not the full country distribution; not comparable to a full-table channel."},
]


def _num(x: str):
    if x is None:
        return None
    x = re.sub(r"[%\s]", "", str(x)).replace(",", "")
    try:
        return int(round(float(x)))
    except ValueError:
        return None


def _entity(section: str, raw: str) -> str | None:
    if raw is None or raw.strip().lower() in AGG_LABELS:
        return None
    e = normalize.canonical_country(raw) if section == "country" else normalize.canonical_district(raw)
    return e["name"] if e else raw


def _panel_index() -> dict[tuple, int]:
    idx: dict[tuple, int] = defaultdict(int)
    with (MIGRATION_DIR / "panel_normalized.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["row_type"] != "detail":
                continue
            k = (r["reconciled_fiscal_year"], r["section"], r["name_canonical"],
                 r["channel_canonical"], r["gender"])
            idx[k] += int(r["count"])
    return idx


def run_check(chk: dict, panel: dict[tuple, int]) -> dict:
    op: dict[tuple, int] = defaultdict(int)
    skipped = 0
    with (OPENDATA / chk["file"]).open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ent = _entity(chk["section"], r.get(chk["entity"]))
            fy = normalize.fiscal_year_for_ad(r.get(chk["year"], ""))
            val = _num(r.get(chk["value"]))
            if ent is None:
                skipped += 1
                continue
            if fy is None or val is None:
                skipped += 1
                continue
            op[(fy, chk["section"], ent, chk["channel"], chk["gender"])] += val

    matched = [k for k in op if k in panel]
    op_total = sum(op.values())
    matched_op = sum(op[k] for k in matched)
    matched_panel = sum(panel[k] for k in matched)
    diffs = sorted(({"fy": k[0], "entity": k[2], "opendata": op[k], "panel": panel[k],
                     "diff": panel[k] - op[k]} for k in matched),
                   key=lambda d: -abs(d["diff"]))
    frac = abs(matched_panel - matched_op) / matched_op if matched_op else 0.0
    if chk["comparable"]:
        status = "match" if frac <= TOL else "divergent"
    else:
        status = "not_comparable"
    return {
        "id": chk["id"], "file": chk["file"],
        "panel": {"section": chk["section"], "channel": chk["channel"], "gender": chk["gender"]},
        "comparable": chk["comparable"],
        "reason": chk.get("reason"),
        "matched_keys": len(matched), "opendata_keys": len(op), "skipped_rows": skipped,
        "opendata_total": op_total, "matched_opendata_total": matched_op,
        "matched_panel_total": matched_panel,
        "abs_frac_diff": round(frac, 5),
        "status": status,
        "top_diffs": [d for d in diffs if d["diff"] != 0][:10],
        "opendata_only": sorted({k[2] for k in op if k not in panel})[:10],
    }


def main(argv: list[str] | None = None) -> int:
    panel = _panel_index()
    results = [run_check(c, panel) for c in CHECKS]
    fails = [r for r in results if r["comparable"] and r["status"] != "match"]

    print(f"{'check':22} {'keys':>5} {'opendata':>12} {'panel':>12} {'Δ%':>7}  status")
    for r in results:
        tag = "" if r["comparable"] else " (info)"
        print(f"{r['id']:22} {r['matched_keys']:>5} {r['matched_opendata_total']:>12,} "
              f"{r['matched_panel_total']:>12,} {r['abs_frac_diff']*100:>6.3f}%  "
              f"{r['status']}{tag}")

    out = {
        "note": "opendatanepal is a cross-check only; never used to fill panel gaps.",
        "tolerance": TOL,
        "checks": results,
        "comparable_failures": [r["id"] for r in fails],
    }
    (MIGRATION_DIR / "crosscheck.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote migration/crosscheck.json ({len(fails)} comparable failures)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
