"""Build the tracked archive.org backfill panel (``datasets/labour-migration/panel_archive.csv.gz``).

Consumes the downloaded ``output/migration/archive_pdfs/`` cache + the tracked
``datasets/labour-migration/manifests/migration_archive_manifest.json`` and emits tidy-long rows for the
**fully verified** monthly country reports (BS 2067-2075).

Family (a) is the 12-col *labour-approval* table ("कामदार गएको मुलुक" ×
संस्थागत/व्यक्तिगत × three period-scopes), so each country contributes an
``institutional`` and an ``individual`` **approval type**. The newer BS 2073-2075
stage template adds ``pre_permission`` / ``final_approved`` scopes and
``re_entry`` / ``new`` / ``legalization`` entry types.

This is a *separate* artifact from ``panel.csv``: the period-scopes
(``previous_cumulative`` / ``month`` / ``cumulative`` and the newer stage scopes)
do not map onto the live monthly-detail schema, so they are kept out of the
shipped panel and joined at analysis time via ``period_bs`` + ``scope``.

The ``approval_type`` axis is **not** the modern delivery-channel axis
(``recruiting_agency`` / ``individual_new`` / ``g2g`` / ...). No verified mapping
exists yet (see the explicit ``channel_map: null/TBD`` block in
``channels.json``); do not join the two panels on channel string equality.

    python -m migration_parser archivepanel
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys

from .. import normalize
from ..historical import SCOPE_CLASS
from ..paths import (
    ARCHIVE_PANEL_COLUMNS,
    MIGRATION_ARCHIVE_BUILD,
    MIGRATION_ARCHIVE_MANIFEST,
    MIGRATION_ARCHIVE_PANEL,
    MIGRATION_ARCHIVE_UNRESOLVED,
    REPO_ROOT,
)
from ..periods import BS_MONTHS_EN, BS_MONTHS_NP, _norm_digits
from . import cmd_backfill as backfill


def _period_key(period_bs: str) -> tuple[int, int] | None:
    """Normalise ``"2069 Shrawan"`` / ``"2069 श्रावण"`` to ``(year, month)``."""
    if not period_bs:
        return None
    t = _norm_digits(period_bs)
    ym = re.search(r"(20\d\d)", t)
    if not ym:
        return None
    low = t.lower()
    for name, num in BS_MONTHS_NP.items():
        if name in t:
            return int(ym.group(1)), num
    for name, num in BS_MONTHS_EN.items():
        if re.search(rf"\b{name}\b", low):
            return int(ym.group(1)), num
    return None


def _period_month(period_bs: str) -> int | None:
    """Return the month number even when the catalog year is ``unknown``."""
    if not period_bs:
        return None
    t = _norm_digits(period_bs)
    low = t.lower()
    for name, num in BS_MONTHS_NP.items():
        if name in t:
            return num
    for name, num in BS_MONTHS_EN.items():
        if re.search(rf"\b{name}\b", low):
            return num
    return None


def build(include_unverified: bool = False) -> tuple[list[dict], dict]:
    entries = json.loads(MIGRATION_ARCHIVE_MANIFEST.read_text())
    # A Wayback capture can serve another month's bytes under this URL (identical
    # sha). Keep one row-set per unique source content, preferring the copy whose
    # printed header agrees with its catalog month.
    seen_sha: dict[str, dict] = {}
    dropped: list[dict] = []
    for e in entries:
        if e.get("status") != "fetched":
            continue
        # ``local_path`` is authoritative: serials change when the resolve
        # heuristic picks up new candidates, but the downloaded bytes do not.
        lp = e.get("local_path")
        pdf = (REPO_ROOT / lp if lp else backfill.ARCHIVE_PDFS / (
            f"{e['serial']:03d}_{e['period_bs'].replace(' ', '_')}.pdf"))
        if not pdf.exists():
            print(f"  [skip] missing cache: {pdf.name}", file=sys.stderr)
            continue
        res = backfill.extract_one(pdf)
        if not res["verified"] and not include_unverified:
            continue
        prev = seen_sha.get(e["source_pdf_sha256"])
        if prev is None:
            seen_sha[e["source_pdf_sha256"]] = (e, res)
            continue
        best, other = _pick((e, res), prev)
        dropped.append({"serial": other[0]["serial"],
                        "period_bs": other[0]["period_bs"],
                        "duplicate_of": best[0]["serial"]})
        if other is prev:
            seen_sha[e["source_pdf_sha256"]] = (e, res)

    # Distinct captures can resolve to the same printed month (misfiled
    # filenames, stale captures). Keep one row-set per period, preferring the
    # capture whose header agrees with its catalog month. If neither capture
    # agrees, drop both rather than relabel a month on a guess.
    groups: dict[tuple[int, int], list[tuple[dict, dict]]] = {}
    unkeyed: list[tuple[dict, dict]] = []
    for pair in seen_sha.values():
        key = _period_key(pair[1]["period_bs"])
        if key is None:
            unkeyed.append(pair)
        else:
            groups.setdefault(key, []).append(pair)
    kept = list(unkeyed)
    for pairs in groups.values():
        agreeing = [pair for pair in pairs if _agrees(pair)]
        if not agreeing:
            if len(pairs) == 1:
                # Sole capture for the month: keep it and let the mismatch
                # surface in provenance rather than silently dropping a month.
                kept.append(pairs[0])
            else:
                for pair in pairs:
                    dropped.append({"serial": pair[0]["serial"],
                                    "period_bs": pair[0]["period_bs"],
                                    "reason": "no_catalog_agreement"})
            continue
        best = min(agreeing, key=lambda pair: pair[0]["serial"])
        for pair in pairs:
            if pair is not best:
                dropped.append({"serial": pair[0]["serial"],
                                "period_bs": pair[0]["period_bs"],
                                "duplicate_of": best[0]["serial"],
                                "reason": "same_period"})
        kept.append(best)

    rows: list[dict] = []
    docs: list[dict] = []
    entity_cache: dict[str, dict] = {}
    for e, res in sorted(kept, key=lambda t: t[0]["serial"]):
        granularity = normalize.doc_granularity(res["doc_type"])
        for r in res["data"]:
            if r["row_type"] == "detail":
                if r["name"] not in entity_cache:
                    entity_cache[r["name"]] = normalize.normalize_name(
                        "country", r["name"])
                info = entity_cache[r["name"]]
                name_canonical = info.get("canonical", r["name"])
                iso3 = info.get("iso3", "")
                entity_resolved = bool(info.get("resolved", False))
            else:
                name_canonical = r["name"]
                iso3 = ""
                entity_resolved = True
            rows.append({
                "source_kind": "archive_org",
                "doc_id": res["doc_id"],
                "period_bs": res["period_bs"],
                "doc_type": res["doc_type"],
                "section": r["section"],
                "row_type": r["row_type"],
                "name": r["name"],
                "sn": r["sn"],
                "approval_type": r["approval_type"],
                "entry_type": r.get("entry_type", ""),
                "gender": r["gender"],
                "count": r["count"],
                "scope": r["scope"],
                "scope_class": r["scope_class"],
                "granularity": granularity,
                "source_page": r["source_page"],
                "name_canonical": name_canonical,
                "iso3": iso3,
                "entity_resolved": entity_resolved,
                "analysis_safe": bool(res["verified"] and entity_resolved),
                "verified": res["verified"],
                "source_url": e["wayback_url"],
                "source_pdf_sha256": e["source_pdf_sha256"],
            })
        docs.append({
            "serial": e["serial"],
            "period_bs": res["period_bs"],
            "header_period_bs": res["header_period_bs"],
            "doc_id": res["doc_id"],
            "source_pdf_sha256": e["source_pdf_sha256"],
            "wayback_url": e["wayback_url"],
            "verified": res["verified"],
            "n_rows": len(res["data"]),
        })
    meta = {
        "n_docs": len(docs),
        "n_rows": len(rows),
        "scopes": sorted({r["scope"] for r in rows}),
        "scope_classes": dict(SCOPE_CLASS),
        "approval_types": sorted({r["approval_type"] for r in rows}),
        "entry_types": sorted({r["entry_type"] for r in rows if r["entry_type"]}),
        "n_analysis_safe": sum(1 for r in rows if r["analysis_safe"]),
        "n_unresolved": sum(1 for r in rows if not r["entity_resolved"]),
        "dropped_duplicates": dropped,
        "docs": docs,
    }
    return rows, meta


def _agrees(pair: tuple[dict, dict]) -> bool:
    """True when the printed header does not contradict the catalog month."""
    res, entry = pair[1], pair[0]
    h = _period_key(res.get("header_period_bs", ""))
    if h is None:
        return True
    cat = _period_key(entry.get("period_bs", ""))
    if cat is not None:
        return h == cat
    # Catalog year is unknown (``"unknown Kartik"``): the month is still
    # comparable, and a mismatch means the downloaded bytes are mislabeled.
    cm = _period_month(entry.get("period_bs", ""))
    return cm is None or h[1] == cm


def _pick(a: tuple[dict, dict], b: tuple[dict, dict]
          ) -> tuple[tuple[dict, dict], tuple[dict, dict]]:
    """Return ``(keeper, dropped)`` ``(entry, result)`` pairs.

    Lowest manifest serial wins unless its printed header disagrees with its
    catalog month while the other's agrees.
    """
    if a[0]["serial"] > b[0]["serial"]:
        a, b = b, a
    keep_a = _agrees(a) or not _agrees(b)
    return (a, b) if keep_a else (b, a)


def _write_gz(rows: list[dict], path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            text = io.TextIOWrapper(gz, encoding="utf-8", newline="")
            w = csv.DictWriter(text, fieldnames=ARCHIVE_PANEL_COLUMNS)
            w.writeheader()
            w.writerows(rows)
            text.detach()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="migration archivepanel")
    p.add_argument("--include-unverified", action="store_true",
                   help="also emit docs whose printed totals do not reconcile")
    p.add_argument("--out", default=None, help="override output .csv.gz path")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    rows, meta = build(include_unverified=args.include_unverified)
    if not rows:
        print("no verified archive rows (run `backfill --fetch` first)",
              file=sys.stderr)
        return 1
    resolved = [r for r in rows if r["entity_resolved"]]
    unresolved = [r for r in rows if not r["entity_resolved"]]
    out = MIGRATION_ARCHIVE_PANEL if args.out is None else args.out
    _write_gz(resolved, out)
    _write_gz(unresolved, MIGRATION_ARCHIVE_UNRESOLVED)
    meta["n_rows_all"] = len(rows)
    meta["n_rows"] = len(resolved)
    meta["output"] = str(out.relative_to(REPO_ROOT))
    meta["n_unresolved"] = len(unresolved)
    meta["output_unresolved"] = str(MIGRATION_ARCHIVE_UNRESOLVED.relative_to(REPO_ROOT))
    MIGRATION_ARCHIVE_BUILD.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    periods = {d["period_bs"] for d in meta["docs"]}
    first = min(periods, key=lambda p: _period_key(p) or (0, 0))
    last = max(periods, key=lambda p: _period_key(p) or (0, 0))
    print(f"wrote {out} ({meta['n_docs']} docs, {len(resolved)} resolved rows, "
          f"{len(unresolved)} quarantined, {first}..{last})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
