"""Time, seasonality, and historical-series patterns for the migration panel.

The module is deliberately descriptive. It separates the modern monthly panel
from the archive.org monthly panel, never pools the two, and treats the
partial 2083/84 fiscal year as coverage-only. Every public value is
JSON-serializable.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .datasets import archive_panel, country_year, load_panel, series

BS_MONTHS = [
    "Baishakh", "Jestha", "Ashar", "Shrawan", "Bhadra", "Ashwin",
    "Kartik", "Mangsir", "Poush", "Magh", "Falgun", "Chaitra",
]
MONTH_INDEX = {month: idx for idx, month in enumerate(BS_MONTHS)}

MONTH_ALIASES = {
    "baishakh": "Baishakh", "baisakh": "Baishakh", "vaisakh": "Baishakh",
    "बैशाख": "Baishakh", "बैसाख": "Baishakh",
    "jestha": "Jestha", "jeth": "Jestha", "जेठ": "Jestha",
    "ज्येष्ठ": "Jestha",
    "ashar": "Ashar", "asar": "Ashar", "asadh": "Ashar", "ashad": "Ashar",
    "असार": "Ashar", "अषाढ": "Ashar", "आषाढ": "Ashar",
    "shrawan": "Shrawan", "shravan": "Shrawan", "साउन": "Shrawan",
    "श्रावण": "Shrawan",
    "bhadra": "Bhadra", "भदौ": "Bhadra", "भाद्र": "Bhadra",
    "ashwin": "Ashwin", "ashoj": "Ashwin", "असोज": "Ashwin",
    "आश्विन": "Ashwin",
    "kartik": "Kartik", "कार्तिक": "Kartik",
    "mangsir": "Mangsir", "मंसिर": "Mangsir", "मार्ग": "Mangsir",
    "poush": "Poush", "push": "Poush", "पौष": "Poush", "पुष": "Poush",
    "magh": "Magh", "माघ": "Magh",
    "falgun": "Falgun", "फागुन": "Falgun", "फाल्गुन": "Falgun",
    "chaitra": "Chaitra", "चैत": "Chaitra", "चैत्र": "Chaitra",
}

ANNUAL_GAP_TOLERANCE = 0.001
PARTIAL_FY = "2083/84"
LATEST_FY = "2082/83"
MODERN_COUNTRY = (
    ("section", "country"), ("row_type", "detail"), ("gender", "total"),
)


def _fy_key(label: str):
    try:
        text = str(label)
        year = int(text[:4])
        half = text.split("/")[-1] if "/" in text else ""
        return year, int(half) if half.isdigit() else 0
    except (TypeError, ValueError):
        return 9999, 0


def _f(value, digits=2):
    return None if value is None or pd.isna(value) else round(float(value), digits)


def _int(value):
    return None if value is None or pd.isna(value) else int(value)


def _month_token(text) -> str | None:
    token = str(text).strip()
    if not token:
        return None
    low = token.lower()
    if low in MONTH_ALIASES:
        return MONTH_ALIASES[low]
    for part in low.replace("-", " ").split():
        if part in MONTH_ALIASES:
            return MONTH_ALIASES[part]
    return None


def _parse_period_bs(value):
    if value is None or pd.isna(value):
        return None, None
    text = str(value).strip()
    year = None
    for token in text.replace("-", " ").split():
        if token.isdigit() and len(token) == 4:
            year = int(token)
            break
    month = _month_token(text)
    if month is None:
        for part in text.replace("-", " ").split():
            month = _month_token(part)
            if month:
                break
    return year, month


def _approx_month(start) -> str | None:
    if pd.isna(start):
        return None
    month = int(start.month)
    return {
        4: "Baishakh", 5: "Jestha", 6: "Ashar", 7: "Shrawan",
        8: "Bhadra", 9: "Ashwin", 10: "Kartik", 11: "Mangsir",
        12: "Poush", 1: "Magh", 2: "Falgun", 3: "Chaitra",
    }.get(month)


def _annual_totals(panel: pd.DataFrame) -> dict[str, int]:
    d = panel
    for col, value in MODERN_COUNTRY:
        d = d[d[col] == value]
    d = d[d["granularity"] == "year"]
    if "entity_resolved" in d:
        d = d[d["entity_resolved"]]
    return {str(fy): int(v) for fy, v in d.groupby("reconciled_fiscal_year")["count"].sum().items()}


def _modern_periods(panel: pd.DataFrame) -> list[dict]:
    d = panel
    for col, value in MODERN_COUNTRY:
        d = d[d[col] == value]
    d = d[d["granularity"] == "month"].copy()
    if d.empty:
        return []
    d["start"] = pd.to_datetime(d["period_ad_start"], errors="coerce")
    rows = []
    for doc_id, block in d.groupby("doc_id", sort=False):
        raw = block["period_bs"].dropna().astype(str)
        raw_label = raw.iloc[0] if len(raw) else None
        year, month = _parse_period_bs(raw_label)
        start = block["start"].dropna().min()
        inferred = False
        if month is None:
            month = _approx_month(start)
            inferred = month is not None
        rows.append({
            "doc_id": str(doc_id),
            "period_bs_raw": raw_label,
            "bs_year": _int(year),
            "bs_month": month,
            "inferred_month": inferred,
            "start": start.date().isoformat() if pd.notna(start) else None,
            "fiscal_year": str(block["reconciled_fiscal_year"].iloc[0]),
            "count": int(block["count"].sum()),
        })
    return sorted(rows, key=lambda r: (r["start"] or "", r["doc_id"]))


def _modern_coverage(periods: list[dict], annual: dict[str, int]) -> list[dict]:
    by_fy: dict[str, list[dict]] = {}
    for row in periods:
        by_fy.setdefault(row["fiscal_year"], []).append(row)
    out = []
    for fy in sorted(by_fy, key=_fy_key):
        rows = sorted(by_fy[fy], key=lambda r: r["start"] or "")
        monthly_sum = sum(r["count"] for r in rows)
        annual_total = annual.get(fy)
        gap = abs(annual_total - monthly_sum) if annual_total else None
        gap_pct = (gap / annual_total * 100) if annual_total else None
        months = [r["bs_month"] for r in rows if r["bs_month"]]
        out.append({
            "fiscal_year": fy,
            "periods": [{
                "period_bs": r["period_bs_raw"],
                "bs_year": r["bs_year"],
                "bs_month": r["bs_month"],
                "inferred_month": r["inferred_month"],
                "start": r["start"],
                "doc_id": r["doc_id"],
                "count": r["count"],
            } for r in rows],
            "n_periods": len(rows),
            "n_docs": len({r["doc_id"] for r in rows}),
            "distinct_months": len(set(months)),
            "monthly_sum": monthly_sum,
            "annual_total": annual_total,
            "gap": gap,
            "gap_pct": _f(gap_pct, 4),
            "complete_monthly": len(set(months)) >= 12,
            "partial": fy == PARTIAL_FY,
            "within_tolerance": bool(
                annual_total and len(set(months)) >= 12
                and gap is not None
                and gap / annual_total <= ANNUAL_GAP_TOLERANCE
            ),
        })
    return out


def _modern_seasonality(periods: list[dict], fy: str = LATEST_FY) -> dict:
    rows = sorted([r for r in periods if r["fiscal_year"] == fy],
                  key=lambda r: r["start"] or "")
    rows = [r for r in rows if r["bs_month"] in MONTH_INDEX]
    if not rows:
        return {"fiscal_year": fy, "monthly": [], "n_periods": 0}
    total = sum(r["count"] for r in rows)
    mean = total / len(rows) if rows else 0
    shares = []
    for r in rows:
        share = r["count"] / total * 100 if total else 0
        shares.append(share)
    mean_share = sum(shares) / len(shares)
    peak = max(rows, key=lambda r: r["count"])
    trough = min(rows, key=lambda r: r["count"])
    counts = pd.Series([r["count"] for r in rows], dtype="float64")
    return {
        "fiscal_year": fy,
        "n_periods": len(rows),
        "n_docs": len({r["doc_id"] for r in rows}),
        "complete_monthly": len({r["bs_month"] for r in rows}) >= 12,
        "total": total,
        "monthly": [{
            "period_bs": r["period_bs_raw"],
            "bs_month": r["bs_month"],
            "bs_month_index": MONTH_INDEX[r["bs_month"]] + 1,
            "start": r["start"],
            "doc_id": r["doc_id"],
            "count": r["count"],
            "share_pct": _f(r["count"] / total * 100 if total else 0, 3),
            "index": _f(r["count"] / mean * 100 if mean else 0, 2),
        } for r in rows],
        "peak": {"bs_month": peak["bs_month"], "count": peak["count"],
                 "start": peak["start"]},
        "trough": {"bs_month": trough["bs_month"], "count": trough["count"],
                   "start": trough["start"]},
        "peak_to_trough_ratio": _f(peak["count"] / trough["count"], 3)
        if trough["count"] else None,
        "mean_monthly": _f(mean, 2),
        "volatility_cv_pct": _f(counts.std(ddof=0) / counts.mean() * 100, 2)
        if counts.mean() else None,
        "share_range_pct": _f(max(shares) - min(shares), 3),
        "mean_share_pct": _f(mean_share, 3),
        "months_covered": [r["bs_month"] for r in rows],
    }


def _archive_periods(arc: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    d = arc
    for col, value in MODERN_COUNTRY:
        d = d[d[col] == value]
    candidates = []
    for (raw_period, doc_id), block in d.groupby(["period_bs", "doc_id"],
                                                 dropna=False, sort=False):
        scopes = set(block["scope"].dropna().astype(str))
        chosen = "final_approved" if "final_approved" in scopes else (
            "month" if "month" in scopes else None)
        if chosen is None:
            continue
        selected = block[block["scope"] == chosen]
        year, month = _parse_period_bs(raw_period)
        candidates.append({
            "period_bs_raw": str(raw_period),
            "bs_year": year,
            "bs_month": month,
            "doc_id": str(doc_id),
            "scope": chosen,
            "available_scopes": sorted(scopes),
            "count": int(selected["count"].sum()),
        })
    candidates.sort(key=lambda r: (r["bs_year"] or 0,
                                   MONTH_INDEX.get(r["bs_month"], 99),
                                   {"final_approved": 0, "month": 1}.get(r["scope"], 9),
                                   r["doc_id"]))
    chosen, dropped = {}, []
    for row in candidates:
        key = (row["bs_year"], row["bs_month"])
        if row["bs_year"] is None or row["bs_month"] is None:
            dropped.append({**row, "reason": "unparsed period"})
            continue
        if key in chosen:
            dropped.append({**row, "reason": "duplicate canonical period"})
            continue
        chosen[key] = row
    periods = sorted(chosen.values(), key=lambda r: (
        r["bs_year"], MONTH_INDEX.get(r["bs_month"], 99)))
    return periods, dropped


def _archive_coverage(periods: list[dict]) -> list[dict]:
    by_year: dict[int, list[dict]] = {}
    for row in periods:
        by_year.setdefault(row["bs_year"], []).append(row)
    out = []
    for year in sorted(by_year):
        rows = by_year[year]
        present = [r["bs_month"] for r in rows]
        missing = [m for m in BS_MONTHS if m not in present]
        scopes: dict[str, int] = {}
        for r in rows:
            scopes[r["scope"]] = scopes.get(r["scope"], 0) + 1
        out.append({
            "bs_year": year,
            "n_periods": len(rows),
            "n_docs": len({r["doc_id"] for r in rows}),
            "present_months": present,
            "missing_months": missing,
            "n_missing": len(missing),
            "complete_year": len(missing) == 0,
            "scopes": dict(sorted(scopes.items())),
            "periods": [{
                "period_bs": r["period_bs_raw"],
                "bs_month": r["bs_month"],
                "month_index": MONTH_INDEX[r["bs_month"]] + 1,
                "scope": r["scope"],
                "available_scopes": r["available_scopes"],
                "doc_id": r["doc_id"],
                "count": r["count"],
            } for r in rows],
        })
    return out


def _archive_seasonality(periods: list[dict]) -> dict:
    by_year: dict[int, list[dict]] = {}
    for row in periods:
        by_year.setdefault(row["bs_year"], []).append(row)
    ratios: dict[str, list[float]] = {m: [] for m in BS_MONTHS}
    year_rows = []
    for year in sorted(by_year):
        rows = by_year[year]
        obs_mean = sum(r["count"] for r in rows) / len(rows) if rows else 0
        year_rows.append({
            "bs_year": year,
            "n_months": len(rows),
            "observed_total": sum(r["count"] for r in rows),
            "observed_mean": _f(obs_mean, 2),
            "complete_year": len(rows) == 12,
        })
        for r in rows:
            if obs_mean:
                ratios[r["bs_month"]].append(r["count"] / obs_mean)
    monthly = []
    for month in BS_MONTHS:
        values = ratios[month]
        index = sum(values) / len(values) * 100 if values else None
        std = pd.Series(values, dtype="float64").std(ddof=0) * 100 if values else None
        monthly.append({
            "bs_month": month,
            "month_index": MONTH_INDEX[month] + 1,
            "n_years": len(values),
            "index": _f(index, 2),
            "std_index_points": _f(std, 2),
            "cv_pct": _f(std / index * 100, 2) if index else None,
            "complete_year_support": len(values),
        })
    scored = [m for m in monthly if m["index"] is not None]
    peak = max(scored, key=lambda m: m["index"]) if scored else None
    trough = min(scored, key=lambda m: m["index"]) if scored else None
    indices = pd.Series([m["index"] for m in scored], dtype="float64")
    all_years = sorted(by_year)
    return {
        "years": all_years,
        "n_years": len(all_years),
        "year_detail": year_rows,
        "monthly": monthly,
        "peak": peak,
        "trough": trough,
        "index_mean": _f(indices.mean(), 2) if len(indices) else None,
        "index_std": _f(indices.std(ddof=0), 2) if len(indices) else None,
        "peak_to_trough_ratio": _f(peak["index"] / trough["index"], 3)
        if peak and trough and trough["index"] else None,
        "missingness_flagged": True,
        "sparse_months": [m["bs_month"] for m in monthly
                          if m["n_years"] < max(2, len(all_years) // 2)],
        "complete_year_count": sum(1 for r in year_rows if r["complete_year"]),
    }


def _break_scan(years: list[str], values: list[float], min_segment: int = 2) -> dict:
    n = len(years)
    if n < min_segment * 2:
        return {"years": years, "best": None, "candidates": []}
    grand_mean = sum(values) / n
    total_sse = sum((v - grand_mean) ** 2 for v in values)
    candidates = []
    for split_idx in range(min_segment, n - min_segment + 1):
        pre = values[:split_idx]
        post = values[split_idx:]
        pre_mean = sum(pre) / len(pre)
        post_mean = sum(post) / len(post)
        sse = (sum((v - pre_mean) ** 2 for v in pre)
               + sum((v - post_mean) ** 2 for v in post))
        reduction = 1 - sse / total_sse if total_sse else None
        candidates.append({
            "split_after": years[split_idx - 1],
            "split_before": years[split_idx],
            "pre_n": len(pre),
            "post_n": len(post),
            "pre_mean": _f(pre_mean, 4),
            "post_mean": _f(post_mean, 4),
            "difference": _f(post_mean - pre_mean, 4),
            "difference_pct": _f((post_mean / pre_mean - 1) * 100, 2)
            if pre_mean else None,
            "sse": _f(sse, 4),
            "sse_reduction": _f(reduction, 4),
        })
    best = max(candidates, key=lambda r: r["sse_reduction"] or -1)
    return {
        "years": years,
        "n_years": n,
        "min_segment": min_segment,
        "total_sse": _f(total_sse, 4),
        "best": best,
        "candidates": candidates,
        "method": "single two-regime mean split; descriptive, not a formal break test",
    }


def _deaths_sources(ser: pd.DataFrame) -> list[dict]:
    cand = ser[(ser["metric"] == "deaths") & (ser["gender"] == "total")]
    if "year_basis" in cand:
        cand = cand[cand["year_basis"].fillna("fiscal") == "fiscal"]
    if "unit" in cand:
        cand = cand[cand["unit"].fillna("count") == "count"]
    rows = []
    for key, block in cand.groupby("series_key"):
        years = sorted([str(y) for y in block["fiscal_year"].dropna().unique()],
                       key=_fy_key)
        rows.append({
            "series_key": str(key),
            "report": str(block["report"].iloc[0]),
            "caption": str(block["caption"].iloc[0]),
            "n_rows": int(len(block)),
            "n_years": len(years),
            "first_year": years[0] if years else None,
            "last_year": years[-1] if years else None,
            "years": years,
            "sum_count": int(block["count"].sum()),
            "selected": False,
        })
    rows.sort(key=lambda r: (r["n_years"], r["report"]), reverse=True)
    if rows:
        rows[0]["selected"] = True
    return rows


def _deaths_block(ser: pd.DataFrame, annual: dict[str, int]) -> dict:
    sources = _deaths_sources(ser)
    selected = next((r for r in sources if r["selected"]), None)
    if selected is None:
        return {"sources": sources, "annual": [], "unmatched_years": [],
                "rate_method": "no usable deaths series"}
    block = ser[(ser["series_key"] == selected["series_key"])
                & (ser["metric"] == "deaths") & (ser["gender"] == "total")]
    grouped = block.groupby("fiscal_year")["count"].sum()
    annual_deaths = [{"fiscal_year": str(fy), "deaths": int(v)}
                     for fy, v in sorted(grouped.items(), key=lambda kv: _fy_key(kv[0]))]
    matched, unmatched = [], []
    for row in annual_deaths:
        ad_fy = row["fiscal_year"]
        start = int(ad_fy[:4]) if ad_fy[:4].isdigit() else None
        bs_start = start + 57 if start is not None else None
        bs_fy = (f"{bs_start}/{str(bs_start + 1)[-2:]}"
                 if bs_start is not None else None)
        approvals = annual.get(bs_fy) if bs_fy else None
        item = {
            "deaths_fiscal_year": ad_fy,
            "approx_bs_fiscal_year": bs_fy,
            "deaths": row["deaths"],
            "safe_approvals": approvals,
            "deaths_per_100k": _f(row["deaths"] / approvals * 100000, 2)
            if approvals else None,
        }
        if approvals:
            matched.append(item)
        else:
            unmatched.append(item)
    return {
        "selected_series_key": selected["series_key"],
        "selected_caption": selected["caption"],
        "selected_report": selected["report"],
        "sources": sources,
        "annual": annual_deaths,
        "matched": matched,
        "unmatched_years": unmatched,
        "approval_years_without_deaths": [
            fy for fy in sorted(annual, key=_fy_key)
            if fy not in {m["approx_bs_fiscal_year"] for m in matched}
            and fy != PARTIAL_FY
        ],
        "rate_method": ("deaths / safe annual approvals * 100,000; AD fiscal "
                        "years mapped to BS by start-year + 57"),
    }


def build() -> dict:
    panel = load_panel(safe=True)
    arc = archive_panel(safe=True)
    ser = series()

    annual = _annual_totals(panel)
    modern_periods = _modern_periods(panel)
    modern_cov = _modern_coverage(modern_periods, annual)
    season = _modern_seasonality(modern_periods)
    archive_periods, archive_dropped = _archive_periods(arc)
    archive_cov = _archive_coverage(archive_periods)
    archive_season = _archive_seasonality(archive_periods)

    cy = country_year(panel)
    cy = cy[cy["fiscal_year"] != PARTIAL_FY]
    approval_years = sorted(cy["fiscal_year"].unique(), key=_fy_key)
    approval_values = [float(cy.loc[cy["fiscal_year"] == fy, "count"].sum())
                       for fy in approval_years]
    hhi_frames = cy.pivot_table(index="fiscal_year", columns="country",
                                values="count", aggfunc="sum", fill_value=0)
    hhi_years = sorted(hhi_frames.index, key=_fy_key)
    hhi_values = []
    for fy in hhi_years:
        row = hhi_frames.loc[fy]
        total = float(row.sum())
        hhi_values.append(sum((float(v) / total) ** 2
                              for v in row if total) if total else 0.0)

    recent = next((c for c in modern_cov if c["fiscal_year"] == LATEST_FY), None)
    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "latest_fy": LATEST_FY,
            "partial_fy": PARTIAL_FY,
            "annual_gap_tolerance": ANNUAL_GAP_TOLERANCE,
            "modern_coverage_dates": {
                "first_period": modern_periods[0]["start"] if modern_periods else None,
                "last_period": modern_periods[-1]["start"] if modern_periods else None,
            },
            "archive_range_bs": sorted({r["bs_year"] for r in archive_periods}),
            "definitions": {
                "modern_monthly": "safe country-section, row_type=detail, gender=total, granularity=month",
                "archive_monthly": "safe archive.org country-section detail totals; prefer final_approved, else month",
                "seasonal_index": "month count divided by the year's mean observed monthly count, times 100",
                "annual_gap": "|annual country total - sum of monthly periods|",
                "deaths_rate": "deaths per 100,000 safe annual approvals",
                "structural_break": "best single two-regime mean split, descriptive only",
            },
            "scope_decisions": {
                "modern_vs_archive": "never pooled; separate calendars and vintages",
                "archive": "final_approved where present, otherwise month; one document per canonical BS month",
                "partial_fy": f"{PARTIAL_FY} is coverage-only and excluded from trend/break analysis",
            },
            "caveats": [
                "The modern panel starts in BS 2081/82 for monthly documents; 2081/82 has only 3 monthly periods.",
                "The archive panel is sparse and no BS year has all 12 months; seasonal indices are indicative only.",
                "Month labels inferred from period start dates when period_bs is blank; flagged per period.",
                "Deaths and approvals come from different calendars/sources; AD-to-BS mapping is approximate (+57 years).",
                "Deaths underreport and approvals are a flow denominator, not a migrant stock.",
                "Break scans are descriptive and do not control for policy, shocks, or reporting changes.",
            ],
        },
        "modern_monthly_coverage": {
            "fiscal_years": modern_cov,
            "latest_complete_fiscal_year": LATEST_FY,
            "latest_reconciliation": recent,
            "incomplete_fiscal_years": [
                c["fiscal_year"] for c in modern_cov if not c["complete_monthly"]
            ],
        },
        "modern_seasonality": season,
        "archive_monthly_coverage": {
            "years": archive_cov,
            "n_periods": len(archive_periods),
            "n_docs": len({r["doc_id"] for r in archive_periods}),
            "dropped_candidates": archive_dropped,
            "years_with_missing_months": [
                y["bs_year"] for y in archive_cov if y["n_missing"] > 0
            ],
        },
        "archive_seasonality": archive_season,
        "structural_breaks": {
            "annual_approvals": {
                **_break_scan(approval_years, approval_values),
                "series": [{"fiscal_year": fy, "count": int(v)}
                           for fy, v in zip(approval_years, approval_values)],
            },
            "destination_hhi": {
                **_break_scan(hhi_years, hhi_values),
                "series": [{"fiscal_year": fy, "hhi": _f(v, 4)}
                           for fy, v in zip(hhi_years, hhi_values)],
            },
        },
        "deaths": _deaths_block(ser, annual),
    }
