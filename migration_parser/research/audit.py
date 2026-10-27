"""Phase 0 data audit for migration research.

Checks the shipped panel for double counting, template breaks, missing fiscal
years, arithmetic contradictions and source-quality problems. Writes a
self-contained HTML report, a JSON payload and a short Markdown memo.
"""

from __future__ import annotations

import base64
import html
import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .. import normalize
from ..paths import (MIGRATION_ARCHIVE_UNRESOLVED, MIGRATION_DIR,
                     MIGRATION_OUTPUT_DIR)
from .datasets import (
    archive_panel,
    country_gender_year,
    country_year,
    district_gender_year,
    district_year,
    load_panel,
    series,
)

OUTPUT_DIR = MIGRATION_OUTPUT_DIR / "research"
ANNUAL_GAP_TOLERANCE = 0.001
GROWTH_MIN_COUNT = 100
FEMALE_MIN_COUNT = 2000


def _fy_key(label: str):
    try:
        text = str(label)
        year = int(text[:4])
        half = text.split("/")[-1] if "/" in text else ""
        return year, int(half) if half.isdigit() else 0
    except (TypeError, ValueError):
        return 9999, 0


def _pct(value: float) -> float:
    return round(100.0 * float(value), 3)


def _hhi(values) -> float:
    total = float(sum(values))
    if not total:
        return 0.0
    return round(sum((float(v) / total) ** 2 for v in values), 4)


def _metric_block(grouped: pd.DataFrame, year: str, value: str = "count") -> dict:
    row = grouped.loc[year]
    values = row[row > 0].dropna().sort_values(ascending=False)
    total = float(values.sum())
    return {
        "fiscal_year": year,
        "count": int(total),
        "n_entities": int(len(values)),
        "hhi": _hhi(values),
        "top5_share_pct": _pct(values.head(5).sum() / total) if total else 0.0,
        "top10_share_pct": _pct(values.head(10).sum() / total) if total else 0.0,
        "top_entity": str(values.index[0]) if len(values) else "",
        "top_entity_count": int(values.iloc[0]) if len(values) else 0,
    }


def _concentration(frame: pd.DataFrame) -> list[dict]:
    grouped = frame.pivot_table(index="fiscal_year", columns="country",
                                values="count", aggfunc="sum", fill_value=0)
    return [_metric_block(grouped, fy) for fy in sorted(grouped.index, key=_fy_key)]


def _growth_outliers(frame: pd.DataFrame, entity: str,
                     min_count: int = GROWTH_MIN_COUNT) -> list[dict]:
    grouped = frame.pivot_table(index="fiscal_year", columns=entity,
                                values="count", aggfunc="sum", fill_value=0)
    rows = []
    years = sorted(grouped.index, key=_fy_key)
    for prev, cur in zip(years, years[1:]):
        for name in grouped.columns:
            a = float(grouped.loc[prev, name])
            b = float(grouped.loc[cur, name])
            if a < min_count or b < min_count:
                continue
            rows.append({
                "from": prev, "to": cur, "entity": str(name),
                "previous": int(a), "current": int(b),
                "growth_pct": round((b / a - 1) * 100, 2),
            })
    if not rows:
        return []
    growth = pd.Series([r["growth_pct"] for r in rows])
    median = float(growth.median())
    mad = float((growth - median).abs().median()) or 1.0
    for r in rows:
        r["robust_z"] = round((r["growth_pct"] - median) / (1.4826 * mad), 2)
    rows.sort(key=lambda r: r["robust_z"], reverse=True)
    return rows[:10] + rows[-10:]


def _entry_exit(frame: pd.DataFrame, entity: str, first: str, last: str,
                threshold: int = 1000) -> tuple[list[dict], list[dict]]:
    grouped = frame.pivot_table(index="fiscal_year", columns=entity,
                                values="count", aggfunc="sum", fill_value=0)
    if first not in grouped.index or last not in grouped.index:
        return [], []
    starts = grouped.loc[first]
    ends = grouped.loc[last]
    entries = [{"entity": str(name), "first_count": int(starts[name]),
                "last_count": int(ends[name])}
               for name in grouped.columns
               if starts[name] < 50 and ends[name] >= threshold]
    exits = [{"entity": str(name), "first_count": int(starts[name]),
              "last_count": int(ends[name])}
             for name in grouped.columns
             if starts[name] >= threshold and ends[name] < 50]
    entries.sort(key=lambda r: r["last_count"], reverse=True)
    exits.sort(key=lambda r: r["first_count"], reverse=True)
    return entries, exits


def _female_shares(frame: pd.DataFrame, year: str,
                   min_count: int = FEMALE_MIN_COUNT,
                   entity: str = "country") -> list[dict]:
    d = frame[frame["fiscal_year"] == year]
    pivot = d.pivot_table(index=entity, columns="gender", values="count",
                          aggfunc="sum", fill_value=0)
    if not {"male", "female"}.issubset(pivot.columns):
        return []
    pivot["total"] = pivot["male"] + pivot["female"]
    pivot["female_share_pct"] = pivot["female"] / pivot["total"].replace(0, pd.NA) * 100
    pivot = pivot[pivot["total"] >= min_count].dropna(subset=["female_share_pct"])
    pivot = pivot.sort_values("female_share_pct")
    return [{"entity": str(name),
             "female_share_pct": round(float(row.female_share_pct), 2),
             "total": int(row.total)}
            for name, row in pd.concat([pivot.head(8), pivot.tail(8)]).iterrows()]


def _coverage(panel: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    grouped = (panel.groupby(["reconciled_fiscal_year", "granularity"]).agg(
        rows=("doc_id", "size"), docs=("doc_id", "nunique")).reset_index())
    rows = []
    for fy in sorted(grouped["reconciled_fiscal_year"].unique(), key=_fy_key):
        block = grouped[grouped["reconciled_fiscal_year"] == fy]
        row = {"fiscal_year": fy}
        for item in block.itertuples():
            row[f"{item.granularity}_docs"] = int(item.docs)
            row[f"{item.granularity}_rows"] = int(item.rows)
        row.setdefault("month_docs", 0)
        row.setdefault("year_docs", 0)
        row.setdefault("measure_docs", 0)
        row.setdefault("month_rows", 0)
        row.setdefault("year_rows", 0)
        row.setdefault("measure_rows", 0)
        rows.append(row)
    gaps = []
    annual = {r["fiscal_year"]: r.get("year_docs", 0) for r in rows}
    any_rows = set(panel["reconciled_fiscal_year"])
    for fy in sorted(any_rows, key=_fy_key):
        if annual.get(fy, 0) == 0 and fy in annual:
            gaps.append({"fiscal_year": fy,
                         "panel_rows": int((panel["reconciled_fiscal_year"] == fy).sum()),
                         "reason": "no annual document in the safe panel"})
    return rows, gaps


def _annual_monthly_gaps(panel: pd.DataFrame) -> list[dict]:
    base = panel[(panel["section"] == "country") & (panel["row_type"] == "detail")
                 & (panel["gender"] == "total")]
    totals = base.groupby(["reconciled_fiscal_year", "granularity"])["count"].sum()
    docs = base.groupby(["reconciled_fiscal_year", "granularity"])["doc_id"].nunique()
    out = []
    for fy in sorted({fy for fy, _ in totals.index}, key=_fy_key):
        if (fy, "year") not in totals.index or (fy, "month") not in totals.index:
            continue
        annual = float(totals.loc[(fy, "year")])
        monthly = float(totals.loc[(fy, "month")])
        month_docs = int(docs.loc[(fy, "month")])
        gap = abs(annual - monthly) / annual if annual else 0.0
        out.append({"fiscal_year": fy, "annual": int(annual),
                    "monthly_sum": int(monthly), "month_docs": month_docs,
                    "gap_pct": _pct(gap), "complete_monthly": month_docs >= 12,
                    "within_tolerance": month_docs >= 12
                    and gap <= ANNUAL_GAP_TOLERANCE})
    return out


def _country_coverage_gaps(safe: pd.DataFrame,
                           full: pd.DataFrame) -> list[dict]:
    country = safe[safe["section"] == "country"]
    full_country = full[full["section"] == "country"]
    all_fy = set(safe["reconciled_fiscal_year"])
    country_fy = set(country["reconciled_fiscal_year"])
    gaps = []
    for fy in sorted(all_fy, key=_fy_key):
        block = country[country["reconciled_fiscal_year"] == fy]
        annual = int((block["granularity"] == "year").sum())
        months = int(block.loc[block["granularity"] == "month", "doc_id"].nunique())
        if fy not in country_fy:
            reason = "no safe country rows"
            if fy in set(full_country["reconciled_fiscal_year"]):
                reason = ("country rows exist but all are excluded by "
                          "analysis_safe")
            gaps.append({"fiscal_year": fy, "panel_rows": int(
                (safe["reconciled_fiscal_year"] == fy).sum()),
                "reason": reason})
        elif annual == 0 and months == 0:
            gaps.append({"fiscal_year": fy, "panel_rows": int(
                (safe["reconciled_fiscal_year"] == fy).sum()),
                "reason": "no safe country document"})
        elif annual == 0 and months < 12:
            gaps.append({"fiscal_year": fy, "panel_rows": int(
                (safe["reconciled_fiscal_year"] == fy).sum()),
                "reason": f"partial year: {months} monthly country documents"})
    return gaps


def _channel_breaks(panel: pd.DataFrame) -> list[dict]:
    out = []
    for fy in sorted(panel["reconciled_fiscal_year"].unique(), key=_fy_key):
        d = panel[panel["reconciled_fiscal_year"] == fy]
        channels = sorted(d["channel_canonical"].dropna().unique())
        out.append({"fiscal_year": fy, "channels": channels,
                    "granularity": sorted(d["granularity"].unique())})
    return out


def _arithmetic_checks(panel: pd.DataFrame) -> dict:
    key = ["granularity", "reconciled_fiscal_year", "period_ad_start", "section",
           "name_canonical", "channel_canonical", "row_type"]
    grouped = (panel.groupby(key + ["gender"], dropna=False)["count"].sum()
               .unstack("gender", fill_value=0))
    needed = {"male", "female", "total"}
    complete = grouped.dropna()
    if not needed.issubset(complete.columns):
        return {"groups_checked": int(len(complete)),
                "male_female_total_mismatches": 0}
    mismatch = complete[complete["male"] + complete["female"] != complete["total"]]
    return {"groups_checked": int(len(complete)),
            "male_female_total_mismatches": int(len(mismatch))}


def _duplicate_keys(panel: pd.DataFrame) -> int:
    cols = [c for c in normalize.dedup_key_columns() if c in panel.columns]
    return int(panel.duplicated(subset=cols).sum())


def _series_checks(df: pd.DataFrame) -> dict:
    key_cols = ["series_key"]
    inconsistent = 0
    for _, block in df.groupby(key_cols, dropna=False):
        for col in ("unit", "year_basis", "gender"):
            if col in block and block[col].fillna("").nunique() > 1:
                inconsistent += 1
    overlap = (df[df["metric"] == "labour_approval"]
               .groupby(["dimension", "name", "fiscal_year", "unit",
                         "year_basis", "gender"], dropna=False)["report"]
               .nunique())
    return {
        "rows": int(len(df)),
        "series_keys": int(df["series_key"].nunique()),
        "inconsistent_key_metadata": int(inconsistent),
        "metrics": {str(k): int(v) for k, v in df["metric"].value_counts().items()},
        "units": {str(k): int(v) for k, v in df["unit"].value_counts().items()},
        "year_bases": {str(k): int(v) for k, v in df["year_basis"].value_counts().items()},
        "reports": {str(k): int(v) for k, v in df["report"].value_counts().items()},
        "labour_approval_duplicate_entity_years": int((overlap > 1).sum()),
    }


def _archive_checks(df: pd.DataFrame, safe: pd.DataFrame,
                    quarantined: pd.DataFrame | None = None) -> dict:
    key = ["doc_id", "period_bs", "scope", "approval_type", "entry_type",
           "name_canonical", "row_type"]
    grouped = (safe.groupby(key + ["gender"], dropna=False)["count"].sum()
               .unstack("gender", fill_value=0))
    complete = grouped.dropna()
    if {"male", "female", "total"}.issubset(complete.columns):
        mismatch = int((complete["male"] + complete["female"]
                        != complete["total"]).sum())
    else:
        mismatch = 0
    periods = sorted(df["period_bs"].dropna().unique(),
                     key=lambda p: (int(str(p)[:4]), str(p)))
    quarantined = quarantined if quarantined is not None else df.iloc[0:0]
    unresolved = int(len(quarantined))
    return {
        "rows": int(len(safe)),
        "rows_all": int(len(df) + len(quarantined)),
        "docs": int(safe["doc_id"].nunique()),
        "periods": len(periods),
        "first_period": str(periods[0]) if periods else "",
        "last_period": str(periods[-1]) if periods else "",
        "unresolved_rows": unresolved,
        "quarantined_rows": unresolved,
        "scopes": {str(k): int(v) for k, v in safe["scope"].value_counts().items()},
        "approval_types": {str(k): int(v)
                           for k, v in safe["approval_type"].value_counts().items()},
        "entry_types": {str(k): int(v)
                        for k, v in safe["entry_type"].fillna("").value_counts().items()},
        "male_female_total_mismatches": mismatch,
    }


def _is_true(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _issue(issues: list[dict], severity: str, code: str, message: str,
           evidence=None) -> None:
    issues.append({"severity": severity, "code": code, "message": message,
                   "evidence": evidence})


def build_audit() -> dict:
    full = load_panel(safe=False)
    safe = load_panel(safe=True)
    cy = country_year(safe)
    cg = country_gender_year(safe)
    dist = district_year(safe)
    dgen = district_gender_year(safe)
    arc = archive_panel(safe=False)
    arc_safe = arc[arc["analysis_safe"]]
    arc_quarantined = (archive_panel(MIGRATION_ARCHIVE_UNRESOLVED, safe=False)
                       if MIGRATION_ARCHIVE_UNRESOLVED.exists()
                       else arc.iloc[0:0])
    ser = series()

    coverage, _ = _coverage(safe)
    coverage_gaps = _country_coverage_gaps(safe, full)
    gaps = _annual_monthly_gaps(safe)
    arithmetic = _arithmetic_checks(safe)
    duplicate_keys = _duplicate_keys(safe)
    verified_false = int((~full["verified"]).sum())
    unresolved = int((~full["entity_resolved"]).sum())
    negative = int((safe["count"] < 0).sum())

    dest_conc = _concentration(cy)
    district_conc = _concentration(dist.rename(columns={"district": "country"}))
    years = sorted(cy["fiscal_year"].unique(), key=_fy_key)
    first, last = years[0], years[-1]
    entries, exits = _entry_exit(cy, "country", first, last)
    female = _female_shares(cg, last)

    issues: list[dict] = []
    if duplicate_keys:
        _issue(issues, "critical", "duplicate_dedup_keys",
               f"{duplicate_keys} duplicate canonical dedup keys", duplicate_keys)
    if negative:
        _issue(issues, "critical", "negative_counts",
               f"{negative} negative count cells in the safe panel", negative)
    if arithmetic["male_female_total_mismatches"]:
        _issue(issues, "critical", "male_female_total",
               "Male + female does not equal total in "
               f"{arithmetic['male_female_total_mismatches']} grouped cells",
               arithmetic)
    for gap in gaps:
        if gap["complete_monthly"] and not gap["within_tolerance"]:
            _issue(issues, "warning", "annual_monthly_gap",
                   f"{gap['fiscal_year']}: annual and monthly totals differ by "
                   f"{gap['gap_pct']}%", gap)
        elif not gap["complete_monthly"]:
            _issue(issues, "info", "partial_monthly_coverage",
                   f"{gap['fiscal_year']}: only {gap['month_docs']} monthly "
                   "country documents; annual comparison is not meaningful", gap)
    for gap in coverage_gaps:
        severity = "info" if gap["reason"].startswith("partial year") else "warning"
        _issue(issues, severity, "country_coverage",
               f"{gap['fiscal_year']}: {gap['reason']}", gap)
    if verified_false:
        _issue(issues, "info", "unverified_rows",
               f"{verified_false} rows come from documents flagged verified=false",
               verified_false)
    if unresolved:
        _issue(issues, "info", "unresolved_entities",
               f"{unresolved} rows carry unresolved entity names and are excluded "
               "from analysis_safe", unresolved)
    channel_sets = _channel_breaks(safe)
    if len({tuple(r["channels"]) for r in channel_sets}) > 1:
        _issue(issues, "info", "template_breaks",
               "Channel vocabularies change across fiscal years; do not pool raw "
               "channel labels without the canonical mapping", channel_sets)
    series_checks = _series_checks(ser)
    if series_checks["inconsistent_key_metadata"]:
        _issue(issues, "warning", "series_key_metadata",
               "Some series keys mix unit/year_basis/gender values",
               series_checks["inconsistent_key_metadata"])
    if series_checks["labour_approval_duplicate_entity_years"]:
        _issue(issues, "info", "series_overlap",
               "Historical labour-approval series overlap across reports; "
               "deduplicate on entity-year and prefer the latest report",
               series_checks["labour_approval_duplicate_entity_years"])

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "panel": str((MIGRATION_DIR / "panel_canonical.csv.gz").relative_to(
                MIGRATION_DIR.parent.parent)),
            "archive": str((MIGRATION_DIR / "panel_archive.csv.gz").relative_to(
                MIGRATION_DIR.parent.parent)),
            "series": str((MIGRATION_DIR / "series.csv").relative_to(
                MIGRATION_DIR.parent.parent)),
        },
        "panel": {
            "rows_all": int(len(full)),
            "rows_safe": int(len(safe)),
            "share_safe_pct": _pct(len(safe) / len(full)) if len(full) else 0.0,
            "docs_safe": int(safe["doc_id"].nunique()),
            "fiscal_years": years,
            "granularity": {str(k): int(v)
                            for k, v in safe["granularity"].value_counts().items()},
            "channels": {str(k): int(v)
                         for k, v in safe["channel_canonical"].value_counts().items()},
            "row_type": {str(k): int(v)
                         for k, v in safe["row_type"].value_counts().items()},
        },
        "coverage": {"by_fy": coverage, "missing_annual_country": coverage_gaps},
        "checks": {
            "duplicate_dedup_keys": duplicate_keys,
            "negative_counts": negative,
            "verified_false_rows": verified_false,
            "unresolved_rows": unresolved,
            "arithmetic": arithmetic,
            "annual_monthly": gaps,
            "template_breaks": channel_sets,
        },
        "destinations": {
            "concentration": dest_conc,
            "growth_outliers": _growth_outliers(cy, "country"),
            "entries": entries,
            "exits": exits,
            "female_shares_latest": female,
        },
        "districts": {
            "concentration": district_conc,
            "growth_outliers": _growth_outliers(dist, "district"),
            "female_shares_latest": _female_shares(dgen, last,
                                                    entity="district"),
        },
        "archive": _archive_checks(arc, arc_safe, arc_quarantined),
        "series": series_checks,
        "issues": issues,
    }


def _coverage_png(panel: pd.DataFrame) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grouped = (panel.groupby(["reconciled_fiscal_year", "granularity"])
               .agg(docs=("doc_id", "nunique")).unstack(fill_value=0))
    grouped = grouped.reindex(columns=["month", "year", "measure"], fill_value=0)
    fig, ax = plt.subplots(figsize=(8.6, 3.3))
    bottom = pd.Series(0, index=grouped.index)
    colors = {"month": "#2b6cb0", "year": "#27ae60", "measure": "#95a5a6"}
    labels = {"month": "monthly docs", "year": "annual docs", "measure": "pre-approval"}
    for col in grouped.columns:
        ax.bar(grouped.index, grouped[col], bottom=bottom, label=labels[col],
               color=colors[col], width=0.7)
        bottom = bottom + grouped[col]
    ax.set_title("Source-document coverage in the safe panel", loc="left",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("documents", color="#7b8794", fontsize=9)
    ax.grid(axis="y", color="#e4e7eb", lw=0.7)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(colors="#7b8794", labelsize=8)
    ax.set_xticks(range(len(grouped.index)))
    ax.set_xticklabels(grouped.index, rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=8, ncol=3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _table(headers: list[str], rows: list[list]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>"
        for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def write_outputs(report: dict, outdir: str | Path | None = None) -> dict:
    out = Path(outdir) if outdir else OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "data_audit.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    panel = load_panel(safe=False)
    image = _coverage_png(panel)

    issues = report["issues"]
    critical = sum(1 for i in issues if i["severity"] == "critical")
    warning = sum(1 for i in issues if i["severity"] == "warning")
    cards = [
        ("safe rows", f"{report['panel']['rows_safe']:,}"),
        ("safe documents", f"{report['panel']['docs_safe']:,}"),
        ("fiscal years", f"{len(report['panel']['fiscal_years'])}"),
        ("critical / warnings", f"{critical} / {warning}"),
    ]
    card_html = "".join(
        f'<div class="card"><div class="v">{_esc(v)}</div>'
        f'<div class="l">{_esc(k)}</div></div>' for k, v in cards)
    issue_rows = [[i["severity"], i["code"], i["message"]] for i in issues]
    coverage_rows = [[r["fiscal_year"], r["year_docs"], r["month_docs"],
                      r["year_rows"], r["month_rows"], r["measure_docs"]]
                     for r in report["coverage"]["by_fy"]]
    annual_rows = [[r["fiscal_year"], f"{r['count']:,}", r["n_entities"],
                    f"{r['top5_share_pct']:.1f}%", f"{r['top10_share_pct']:.1f}%",
                    f"{r['hhi']:.3f}", r["top_entity"]]
                   for r in report["destinations"]["concentration"]]
    growth_rows = [[r["from"], r["to"], r["entity"], f"{r['previous']:,}",
                    f"{r['current']:,}", f"{r['growth_pct']:+.1f}%",
                    f"{r['robust_z']:+.2f}"]
                   for r in report["destinations"]["growth_outliers"]]
    entry_rows = [[r["entity"], f"{r['first_count']:,}", f"{r['last_count']:,}"]
                  for r in report["destinations"]["entries"]]
    exit_rows = [[r["entity"], f"{r['first_count']:,}", f"{r['last_count']:,}"]
                 for r in report["destinations"]["exits"]]
    female_rows = [[r["entity"], f"{r['female_share_pct']:.1f}%", f"{r['total']:,}"]
                   for r in report["destinations"]["female_shares_latest"]]
    gap_rows = [[r["fiscal_year"], f"{r['annual']:,}", f"{r['monthly_sum']:,}",
                 f"{r['gap_pct']:.3f}%"] for r in report["checks"]["annual_monthly"]]
    arc = report["archive"]
    ser = report["series"]

    html_text = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Migration panel — Phase 0 data audit</title>
<style>
  :root {{ --ink:#1f2933; --muted:#7b8794; --line:#e4e7eb; --accent:#c0392b; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#f5f6f8; color:var(--ink);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         line-height:1.55; }}
  header {{ background:linear-gradient(135deg,#1f2933,#313f4d); color:#fff;
            padding:38px 28px 30px; }}
  header h1 {{ margin:0 0 6px; font-size:25px; }}
  header p {{ margin:0; color:#cbd2d9; max-width:880px; }}
  main {{ max-width:1080px; margin:0 auto; padding:24px; }}
  section {{ background:#fff; border:1px solid var(--line); border-radius:10px;
            padding:20px 22px; margin:18px 0; }}
  h2 {{ font-size:17px; margin:0 0 6px; }}
  .sub {{ color:var(--muted); font-size:13px; margin:0 0 12px; }}
  img {{ width:100%; height:auto; display:block; margin:8px 0; }}
  .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }}
  .card {{ background:#f5f6f8; border:1px solid var(--line); border-radius:8px;
          padding:12px 14px; }}
  .card .v {{ font-size:22px; font-weight:700; }}
  .card .l {{ font-size:12px; color:var(--muted); }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; margin-top:8px; }}
  th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line);
          vertical-align:top; }}
  th {{ color:var(--muted); font-weight:600; }}
  .critical {{ color:#c0392b; font-weight:700; }}
  .warning {{ color:#b7791f; font-weight:700; }}
  .info {{ color:#2b6cb0; font-weight:700; }}
  code {{ background:#eef1f4; padding:1px 5px; border-radius:4px; font-size:12px; }}
  footer {{ color:var(--muted); font-size:12px; text-align:center; padding:24px; }}
  @media(max-width:720px) {{ .cards {{ grid-template-columns:repeat(2,1fr); }} }}
</style></head><body>
<header><h1>Migration panel — Phase 0 data audit</h1>
<p>Generated {_esc(report['generated_at'])}. Safe panel only:
<code>analysis_safe=true</code>, one granularity per fiscal year, component detail
rows only. This is an audit, not a results report.</p></header>
<main>
<section><h2>At a glance</h2><div class="cards">{card_html}</div></section>
<section><h2>Issues and flags</h2>
<p class="sub">Critical checks block analysis; warnings need a documented decision;
info explains expected exclusions.</p>
{_table(["severity", "code", "message"], issue_rows) if issue_rows else "<p>No issues flagged.</p>"}
</section>
<section><h2>Coverage</h2>
<p class="sub">Documents and rows by fiscal year and granularity. Monthly and annual
documents overlap in the final years; the analysis builders keep exactly one basis
per fiscal year.</p>
<img src="data:image/png;base64,{image}" alt="coverage">
{_table(["FY", "annual docs", "monthly docs", "annual rows", "monthly rows", "pre-approval docs"], coverage_rows)}
</section>
<section><h2>Annual and monthly overlap</h2>
{_table(["FY", "annual total", "monthly sum", "gap"], gap_rows) if gap_rows else "<p>No overlapping years.</p>"}
</section>
<section><h2>Destination concentration</h2>
<p class="sub">Safe country × FY totals. HHI falls when the destination mix
diversifies. Shares are of total component approvals.</p>
{_table(["FY", "approvals", "countries", "top 5", "top 10", "HHI", "largest"], annual_rows)}
</section>
<section><h2>Destination growth outliers</h2>
<p class="sub">Robust z-scores on year-over-year growth, requiring at least
{GROWTH_MIN_COUNT} approvals in both years. Use as leads to verify, not findings.</p>
{_table(["from", "to", "country", "previous", "current", "growth", "robust z"], growth_rows)}
</section>
<section><h2>Destination entries and exits</h2>
<p class="sub">Entries: &lt;50 in {_esc(report['panel']['fiscal_years'][0])} and
≥1,000 in {_esc(report['panel']['fiscal_years'][-1])}. Exits: the reverse.</p>
<h3>Entries</h3>{_table(["country", "first", "last"], entry_rows) if entry_rows else "<p>None.</p>"}
<h3>Exits</h3>{_table(["country", "first", "last"], exit_rows) if exit_rows else "<p>None.</p>"}
</section>
<section><h2>Female share, latest year</h2>
<p class="sub">Top and bottom destinations with at least {FEMALE_MIN_COUNT:,}
male+female approvals in {_esc(report['panel']['fiscal_years'][-1])}.</p>
{_table(["country", "female share", "total"], female_rows)}
</section>
<section><h2>Archive backfill</h2>
<p class="sub">Separate monthly panel. Do not join its <code>approval_type</code>
to modern <code>channel_canonical</code>.</p>
{_table(["metric", "value"], [
 ["resolved rows", f"{arc['rows']:,}"],
 ["quarantined rows", f"{arc['quarantined_rows']:,}"],
 ["all rows", f"{arc['rows_all']:,}"], ["documents", arc["docs"]],
 ["periods", arc["periods"]], ["first", arc["first_period"]],
 ["last", arc["last_period"]],
 ["M+F≠T groups", arc["male_female_total_mismatches"]],
 ["scopes", ", ".join(f"{k}={v}" for k, v in arc["scopes"].items())],
 ["approval types", ", ".join(f"{k}={v}" for k, v in arc["approval_types"].items())],
])}
</section>
<section><h2>Historical series</h2>
<p class="sub">Rows are additive only within <code>series_key</code>; never sum
across units, bases or sexes.</p>
{_table(["metric", "value"], [
 ["rows", f"{ser['rows']:,}"], ["series keys", ser["series_keys"]],
 ["inconsistent key metadata", ser["inconsistent_key_metadata"]],
 ["labour-approval duplicate entity-years", ser["labour_approval_duplicate_entity_years"]],
 ["units", ", ".join(f"{k}={v}" for k, v in ser["units"].items())],
 ["year bases", ", ".join(f"{k}={v}" for k, v in ser["year_bases"].items())],
])}
</section>
</main>
<footer>Phase 0 audit · safe panel · generated from tracked artifacts</footer>
</body></html>
"""
    (out / "data_audit.html").write_text(html_text)

    lines = [
        "# Migration panel — Phase 0 data audit", "",
        f"Generated: {report['generated_at']}", "",
        "## At a glance", "",
        f"- Safe rows: {report['panel']['rows_safe']:,} of {report['panel']['rows_all']:,}",
        f"- Safe documents: {report['panel']['docs_safe']}",
        f"- Fiscal years: {', '.join(report['panel']['fiscal_years'])}",
        f"- Critical issues: {critical}; warnings: {warning}", "",
        "## Issues", "",
    ]
    if issues:
        lines += ["| severity | code | message |", "|---|---|---|"]
        lines += [f"| {i['severity']} | `{i['code']}` | {i['message']} |"
                  for i in issues]
    else:
        lines.append("No issues flagged.")
    lines += ["", "## Annual totals", "",
              "| FY | approvals | countries | top 5 | top 10 | HHI | largest |",
              "|---|---:|---:|---:|---:|---:|---|"]
    lines += [f"| {r['fiscal_year']} | {r['count']:,} | {r['n_entities']} | "
              f"{r['top5_share_pct']:.1f}% | {r['top10_share_pct']:.1f}% | "
              f"{r['hhi']:.3f} | {r['top_entity']} |"
              for r in report["destinations"]["concentration"]]
    lines += ["", "## Notes", "",
              "- The safe panel excludes unreviewed legalization and old-template "
              "new-entry channels.",
              "- 2075/76 has no safe annual country document; district rows exist.",
              "- Monthly and annual documents overlap in the final fiscal years; "
              "the builders keep one basis per FY.",
              "- Archive and modern channel labels are not comparable."]
    (out / "data_issues.md").write_text("\n".join(lines) + "\n")
    return {"html": out / "data_audit.html", "json": out / "data_audit.json",
            "markdown": out / "data_issues.md"}
