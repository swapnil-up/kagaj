"""Command line entry points for the crime dataset pipeline."""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

from .build import OUT, build, load_parsed
from .extract import analyze_pdf, write_json
from .scrape import PDF_DIR, discover, download, load_manifest, sha256, write_manifest
from .schema import Issue

PARSED = Path(__file__).resolve().parent.parent / "output" / "crime" / "parsed"


def cmd_scrape(args: argparse.Namespace) -> None:
    warnings.filterwarnings("ignore")
    rows = discover()
    write_manifest(rows)
    print(f"{len(rows)} bulletins in manifest")
    if args.download:
        for idx, row in enumerate(rows, start=1):
            path = download(row)
            print(f"[{idx}/{len(rows)}] {row['month_key']} {path.name} {path.stat().st_size // 1024} KiB")


def cmd_extract(args: argparse.Namespace) -> None:
    warnings.filterwarnings("ignore")
    rows = load_manifest()
    if args.limit:
        rows = rows[-args.limit:]
    for idx, row in enumerate(rows, start=1):
        path = PDF_DIR / f"{row['month_key']}.pdf"
        if not path.exists():
            path = download(row)
        issue = Issue(row["bs_year"], row["bs_month"], row["issue_no"])
        data = analyze_pdf(path, issue, row["url"])
        write_json(data, PARSED)
        if args.verbose:
            print(
                f"[{idx}/{len(rows)}] {row['month_key']}: "
                f"violent={len(data.violent)} totals={len(data.monthly_totals)} annual={len(data.annual)}"
            )
    print(f"parsed {len(rows)} bulletins into {PARSED}")


def cmd_build(_: argparse.Namespace) -> None:
    warnings.filterwarnings("ignore")
    info = build()
    print(json.dumps({k: v for k, v in info.items() if k not in ("artifacts", "pdf_sha256")}, indent=2))
    print(f"wrote {OUT}")


def cmd_verify(_: argparse.Namespace) -> None:
    import pandas as pd

    read = {"dtype": {"month": str}}
    issues: list[str] = []
    warnings: list[str] = []
    violent = pd.read_csv(OUT / "violent_monthly.csv.gz", **read)
    national = pd.read_csv(OUT / "violent_national.csv.gz", **read)
    totals = pd.read_csv(OUT / "total_cases_monthly.csv.gz", **read)
    annual = pd.read_csv(OUT / "annual_totals.csv", dtype={"fy": str, "as_of": str})
    coverage = pd.read_csv(OUT / "category_coverage.csv.gz", dtype=read["dtype"])
    status = pd.read_csv(OUT / "month_status.csv.gz", dtype=read["dtype"])
    total_rev = pd.read_csv(OUT / "total_case_revisions.csv.gz", dtype=read["dtype"])
    rates = pd.read_csv(OUT / "annual_rates.csv", dtype={"fy": str})
    national_totals = pd.read_csv(OUT / "total_cases_national.csv.gz", dtype={"month": str})
    national_rev = pd.read_csv(OUT / "national_total_revisions.csv.gz", dtype={"month": str})

    dup = violent.duplicated(subset=["month", "chart_kind", "offense", "province"]).sum()
    if dup:
        issues.append(f"{dup} duplicate violent rows")
    if (violent["value"] < 0).any():
        issues.append("negative violent values")
    bad_dates = (~violent["month"].astype(str).str.fullmatch(r"\d{4}-\d{2}")).sum()
    if bad_dates:
        issues.append(f"{bad_dates} malformed months")
    if "method" not in violent.columns or "confidence" not in violent.columns:
        issues.append("violent rows missing method/confidence")
    elif violent["method"].isna().any() or violent["confidence"].isna().any():
        issues.append("violent rows with empty method/confidence")
    if (violent["basis"] == "derived").sum() and (violent.loc[violent["basis"] == "derived", "value"] < 0).any():
        issues.append("negative derived values")
    partial = status[status.get("partial_chart", False) == True] if "partial_chart" in status else status.iloc[0:0]
    if not partial.empty:
        warnings.append(
            "partial charts: " + ", ".join(
                f"{row.month} {row.chart_kind} ({row.offenses_reported} series)"
                for row in partial.itertuples()
            )
        )
    if status.empty:
        issues.append("empty month_status")
    if rates["population"].isna().any():
        issues.append("annual rates missing population")

    violent["ex_valley"] = violent["province"] != "kathmandu_valley"
    recomputed = (
        violent.groupby(["month", "chart_kind", "offense"], as_index=False)
        .agg(expect_total=("value", "sum"), expect_ex=("value", lambda s: s[violent.loc[s.index, "ex_valley"]].sum()))
    )
    check = national.merge(recomputed, on=["month", "chart_kind", "offense"], how="left")
    mismatch = (
        (check["value"] != check["expect_total"])
        | (check["value_ex_valley"] != check["expect_ex"])
    ).sum()
    if mismatch:
        issues.append(f"{mismatch} national rows disagree with province detail")

    dup = totals.duplicated(subset=["month", "province"]).sum()
    if dup:
        issues.append(f"{dup} duplicate total rows")
    revised = int(total_rev["differs"].sum())
    if revised:
        warnings.append(f"{revised} month/province totals differ across bulletins; see total_case_revisions.csv.gz")
    national_months = sorted(national_totals["month"].unique())
    expected = [f"{year}-{month:02d}" for year in range(2078, 2084) for month in range(1, 13)]
    expected = [m for m in expected if "2078-07" <= m <= "2083-06"]
    gaps = [m for m in expected if m not in set(national_months)]
    if gaps:
        issues.append(f"national totals missing months: {', '.join(gaps)}")
    if national_totals["value"].le(0).any():
        issues.append("non-positive national totals")

    if annual.duplicated(subset=["fy", "series"]).sum():
        issues.append("duplicate annual fiscal-year/series rows")
    for fy, group in annual.groupby("fy"):
        reg = group[group["series"] == "registered"]["value"]
        disposed = group[group["series"] == "disposed"]["value"]
        pending = group[group["series"] == "pending"]["value"]
        if len(reg) == 1 and not disposed.empty and not pending.empty:
            delta = int(reg.iloc[0] - disposed.iloc[0] - pending.iloc[0])
            if delta:
                warnings.append(
                    f"{fy}: disposed + pending differs from registered by {delta}"
                )

    report = {
        "parsed_bulletins": len(load_parsed()),
        "rows": {
            "violent_monthly": len(violent),
            "violent_national": len(national),
            "total_cases_monthly": len(totals),
            "annual_totals": len(annual),
        },
        "months": {
            "violent": int(violent["month"].nunique()),
            "totals": int(totals["month"].nunique()),
        },
        "methods": violent["method"].value_counts().to_dict(),
        "derived_months": sorted(violent.loc[violent["basis"] == "derived", "month"].unique().tolist()),
        "partial_charts": int(len(partial)),
        "revision_conflicts": revised,
        "national_total_conflicts": int(national_rev["differs"].sum()),
        "issues": issues or ["ok"],
        "warnings": warnings,
    }
    (OUT / "verify.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m crime.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scrape", help="refresh the bulletin manifest and optionally download PDFs")
    p.add_argument("--download", action="store_true")
    p.set_defaults(func=cmd_scrape)

    p = sub.add_parser("extract", help="parse downloaded PDFs into intermediate JSON")
    p.add_argument("--limit", type=int, help="only process the most recent N bulletins")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("build", help="write the committed dataset and charts")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help="run integrity checks on the built dataset")
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
