"""Apply canonical entity + fiscal-year normalisation to the migration outputs.

Reads the raw tracked outputs (``migration/panel.csv``, ``migration/agencies.csv``)
and writes normalised companions with added canonical columns. Raw columns are
kept intact; normalisation only appends.

    python -m migration_parser normalize
"""

from __future__ import annotations

import csv
import sys

from .. import normalize
from ..paths import MIGRATION_DIR

PANEL_EXTRA = ["entity_type", "name_canonical", "iso3", "province", "entity_note",
               "entity_resolved", "fiscal_year", "channel_canonical", "channel_class",
               "granularity", "reconciled_fiscal_year", "period_override"]
AGENCY_EXTRA = ["country_canonical", "country_iso3", "fiscal_year"]


def _bool(x) -> str:
    return "true" if x else "false"


def normalize_panel() -> int:
    src = MIGRATION_DIR / "panel.csv"
    dst = MIGRATION_DIR / "panel_normalized.csv"
    n = 0
    with src.open(newline="", encoding="utf-8") as f, dst.open("w", newline="", encoding="utf-8") as g:
        r = csv.DictReader(f)
        w = csv.DictWriter(g, fieldnames=r.fieldnames + PANEL_EXTRA)
        w.writeheader()
        for row in r:
            section = row["section"]
            row = dict(row)
            if row.get("row_type") == "detail":
                info = normalize.normalize_name(section, row["name"])
                row["entity_type"] = section if section in ("country", "district") else ""
                row["name_canonical"] = info.get("canonical", row["name"])
                row["iso3"] = info.get("iso3", "")
                row["province"] = info.get("province", "")
                row["entity_note"] = info.get("note", "")
                row["entity_resolved"] = _bool(info.get("resolved", True))
            else:
                # printed Total / Grand Total rows are not entities
                row["entity_type"] = ""
                row["name_canonical"] = row["name"]
                row["iso3"] = ""
                row["province"] = ""
                row["entity_note"] = ""
                row["entity_resolved"] = "true"
            row["fiscal_year"] = normalize.fiscal_year_for_row(row["doc_id"], row["period_bs"]) or ""
            ch = normalize.canonical_channel(row["channel"])
            row["channel_canonical"] = ch["canonical"]
            row["channel_class"] = ch["class"]
            row["granularity"] = normalize.doc_granularity(row["doc_type"], ch["class"])
            row["reconciled_fiscal_year"] = normalize.reconciled_fiscal_year(row["doc_id"], row["fiscal_year"])
            row["period_override"] = _bool(row["reconciled_fiscal_year"] != row["fiscal_year"])
            w.writerow(row)
            n += 1
    return n


def normalize_agencies() -> int:
    src = MIGRATION_DIR / "agencies.csv"
    dst = MIGRATION_DIR / "agencies_normalized.csv"
    n = 0
    with src.open(newline="", encoding="utf-8") as f, dst.open("w", newline="", encoding="utf-8") as g:
        r = csv.DictReader(f)
        w = csv.DictWriter(g, fieldnames=r.fieldnames + AGENCY_EXTRA)
        w.writeheader()
        for row in r:
            row = dict(row)
            e = normalize.canonical_country(row["country"]) if row["country"] else None
            row["country_canonical"] = e["name"] if e else (row["country"] or "")
            row["country_iso3"] = (e.get("iso3") or "") if e else ""
            row["fiscal_year"] = normalize.fiscal_year_for_row(row["doc_id"], row["period_bs"]) or ""
            w.writerow(row)
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    np = normalize_panel()
    na = normalize_agencies()
    print(f"panel_normalized.csv: {np} rows")
    print(f"agencies_normalized.csv: {na} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
