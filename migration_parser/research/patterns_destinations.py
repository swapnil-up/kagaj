"""Deep destination analysis for the Phase 1 migration pattern book.

All metrics read the safe, single-basis ``country_year`` builder and exclude
the partial 2083/84 fiscal year from every trend and decomposition output.
"""

from __future__ import annotations

import math

import pandas as pd

from .audit import _fy_key
from .datasets import country_year, load_panel

BASE_FY = "2079/80"
LATEST_FY = "2082/83"
PARTIAL_FY = "2083/84"

ACTIVE_THRESHOLD = 100
RANK_MIN_COUNT = 1000
GROWTH_MIN_BASE = 100
VOLUME_MIN = 1000
TOP_N = 15
OUTLIER_N = 10


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _pivot(cy: pd.DataFrame) -> pd.DataFrame:
    return cy.pivot_table(index="fiscal_year", columns="country", values="count",
                          aggfunc="sum", fill_value=0)


def _full_years(cy: pd.DataFrame) -> list[str]:
    years = sorted({str(fy) for fy in cy["fiscal_year"]}, key=_fy_key)
    return [fy for fy in years if _fy_key(fy) <= _fy_key(LATEST_FY)]


def annual_rank_panel(pivot: pd.DataFrame, years: list[str]) -> list[dict]:
    """Top-15 destination counts and shares for each complete fiscal year."""
    out = []
    for fy in years:
        row = pivot.loc[fy]
        total = float(row.sum())
        top = row.sort_values(ascending=False).head(TOP_N)
        out.append({
            "fiscal_year": fy,
            "total": int(total),
            "n_destinations": int((row > 0).sum()),
            "rows": [
                {"rank": rank,
                 "country": str(name),
                 "count": int(value),
                 "share_pct": _round(value / total * 100, 3) if total else 0.0}
                for rank, (name, value) in enumerate(top.items(), start=1)
            ],
        })
    return out


def rank_stability(pivot: pd.DataFrame, years: list[str]) -> list[dict]:
    """Year-over-year Spearman rank correlation above a minimum base."""
    out = []
    for previous, current in zip(years, years[1:]):
        pre = pivot.loc[previous]
        post = pivot.loc[current]
        names = [str(c) for c in pivot.columns
                 if float(pre[c]) >= RANK_MIN_COUNT
                 and float(post[c]) >= RANK_MIN_COUNT]
        if len(names) < 3:
            spearman = None
        else:
            spearman = _round(
                pd.Series([float(pre[c]) for c in names]).corr(
                    pd.Series([float(post[c]) for c in names]),
                    method="spearman"), 3)
        pre_top = set(str(c) for c in pre.sort_values(ascending=False).head(10).index)
        post_top = set(str(c) for c in post.sort_values(ascending=False).head(10).index)
        out.append({
            "from": previous,
            "to": current,
            "n_common_above_min": len(names),
            "spearman": spearman,
            "top10_overlap": len(pre_top & post_top),
            "top10_churn": len(post_top - pre_top),
        })
    return out


def corridor_turnover(pivot: pd.DataFrame, years: list[str]) -> dict:
    """Active-set turnover using an approvals threshold to define active."""
    transitions = []
    for previous, current in zip(years, years[1:]):
        pre = pivot.loc[previous]
        post = pivot.loc[current]
        active_pre = {str(c) for c in pivot.columns
                      if float(pre[c]) >= ACTIVE_THRESHOLD}
        active_post = {str(c) for c in pivot.columns
                       if float(post[c]) >= ACTIVE_THRESHOLD}
        union = active_pre | active_post
        new = [
            {"country": str(c), "count": int(post[c])}
            for c in sorted(active_post - active_pre,
                            key=lambda n: float(post[n]), reverse=True)
        ]
        retired = [
            {"country": str(c), "count": int(pre[c])}
            for c in sorted(active_pre - active_post,
                            key=lambda n: float(pre[n]), reverse=True)
        ]
        pre_top = set(str(c) for c in pre.sort_values(ascending=False).head(10).index)
        post_top = set(str(c) for c in post.sort_values(ascending=False).head(10).index)
        transitions.append({
            "from": previous,
            "to": current,
            "active_pre": len(active_pre),
            "active_post": len(active_post),
            "new": new,
            "retired": retired,
            "jaccard": _round(len(active_pre & active_post) / len(union), 4)
            if union else 0.0,
            "top10_overlap": len(pre_top & post_top),
            "top10_churn": len(post_top - pre_top),
            "top10_new": sorted(post_top - pre_top),
            "top10_dropped": sorted(pre_top - post_top),
        })

    pre = pivot.loc[BASE_FY] if BASE_FY in pivot.index else None
    post = pivot.loc[LATEST_FY] if LATEST_FY in pivot.index else None
    summary = {}
    if pre is not None and post is not None:
        active_pre = {str(c) for c in pivot.columns
                      if float(pre[c]) >= ACTIVE_THRESHOLD}
        active_post = {str(c) for c in pivot.columns
                       if float(post[c]) >= ACTIVE_THRESHOLD}
        union = active_pre | active_post
        summary = {
            "from": BASE_FY,
            "to": LATEST_FY,
            "active_pre": len(active_pre),
            "active_post": len(active_post),
            "new": [{"country": str(c), "count": int(post[c])}
                    for c in sorted(active_post - active_pre,
                                    key=lambda n: float(post[n]), reverse=True)],
            "retired": [{"country": str(c), "count": int(pre[c])}
                        for c in sorted(active_pre - active_post,
                                        key=lambda n: float(pre[n]), reverse=True)],
            "jaccard": _round(len(active_pre & active_post) / len(union), 4)
            if union else 0.0,
        }
    return {"threshold": ACTIVE_THRESHOLD, "transitions": transitions,
            "base_to_latest": summary}


def recovery_decomposition(pivot: pd.DataFrame, pre: str = BASE_FY,
                           post: str = LATEST_FY) -> dict:
    """Additive base-to-latest change by entrant, exit and continuing corridor."""
    if pre not in pivot.index or post not in pivot.index:
        return {}
    before = pivot.loc[pre]
    after = pivot.loc[post]
    total_pre = float(before.sum())
    total_post = float(after.sum())
    total_change = total_post - total_pre

    rows = []
    for name in sorted(set(str(c) for c in pivot.columns)):
        a = int(before.get(name, 0))
        b = int(after.get(name, 0))
        if a == 0 and b == 0:
            continue
        if a == 0:
            status = "entrant"
        elif b == 0:
            status = "exit"
        else:
            status = "continuing"
        contribution = b - a
        rows.append({
            "country": name,
            "status": status,
            "pre": a,
            "latest": b,
            "change": contribution,
            "contribution": contribution,
            "contribution_share_pct": _round(contribution / total_change * 100, 3)
            if total_change else None,
        })

    rows.sort(key=lambda r: (r["contribution"], r["country"]), reverse=True)
    continuing = sum(r["contribution"] for r in rows if r["status"] == "continuing")
    entrants = sum(r["contribution"] for r in rows if r["status"] == "entrant")
    exits = sum(r["contribution"] for r in rows if r["status"] == "exit")
    accounted = continuing + entrants + exits
    positive = [r for r in rows if r["contribution"] > 0][:OUTLIER_N]
    negative = [r for r in rows if r["contribution"] < 0][-OUTLIER_N:][::-1]
    return {
        "pre": pre,
        "latest": post,
        "total_pre": int(total_pre),
        "total_latest": int(total_post),
        "total_change": int(total_change),
        "decomposition": {
            "continuing": int(continuing),
            "entrants": int(entrants),
            "exits": int(exits),
            "accounted_change": int(accounted),
            "unexplained": int(total_change - accounted),
            "sums_correctly": abs(accounted - total_change) < 1e-6,
        },
        "top_positive": positive,
        "top_negative": negative,
        "contributions": rows,
    }


def concentration_decomposition(pivot: pd.DataFrame, pre: str = BASE_FY,
                                post: str = LATEST_FY) -> dict:
    """HHI change decomposed into squared-share contributions."""
    if pre not in pivot.index or post not in pivot.index:
        return {}
    before = pivot.loc[pre]
    after = pivot.loc[post]
    total_pre = float(before.sum())
    total_post = float(after.sum())
    names = sorted(set(str(c) for c in pivot.columns))

    rows = []
    raw_contributions = []
    for name in names:
        a = float(before.get(name, 0))
        b = float(after.get(name, 0))
        s_pre = a / total_pre if total_pre else 0.0
        s_post = b / total_post if total_post else 0.0
        contribution = s_post ** 2 - s_pre ** 2
        raw_contributions.append(contribution)
        rows.append({
            "country": name,
            "pre_count": int(a),
            "latest_count": int(b),
            "pre_share_pct": _round(s_pre * 100, 3),
            "latest_share_pct": _round(s_post * 100, 3),
            "share_change_pp": _round((s_post - s_pre) * 100, 3),
            "squared_share_contribution": _round(contribution, 6),
        })
    rows.sort(key=lambda r: (r["squared_share_contribution"], r["country"]),
              reverse=True)

    hhi_pre = sum((float(before.get(n, 0)) / total_pre) ** 2 for n in names) \
        if total_pre else 0.0
    hhi_post = sum((float(after.get(n, 0)) / total_post) ** 2 for n in names) \
        if total_post else 0.0
    hhi_change = hhi_post - hhi_pre
    accounted = sum(raw_contributions)
    top_name = str(after.idxmax()) if total_post else ""
    top_contribution = next(
        (r["squared_share_contribution"] for r in rows if r["country"] == top_name),
        0.0)
    return {
        "pre": pre,
        "latest": post,
        "hhi_pre": _round(hhi_pre, 6),
        "hhi_latest": _round(hhi_post, 6),
        "hhi_change": _round(hhi_change, 6),
        "sum_of_contributions": _round(accounted, 6),
        "sums_correctly": abs(accounted - hhi_change) < 1e-9,
        "top_destination": top_name,
        "top_destination_contribution": _round(top_contribution, 6),
        "rest_contribution": _round(accounted - top_contribution, 6),
        "top_positive": [r for r in rows
                         if r["squared_share_contribution"] > 0][:OUTLIER_N],
        "top_negative": [r for r in rows
                         if r["squared_share_contribution"] < 0]
        [-OUTLIER_N:][::-1],
        "contributions": rows,
    }


def destination_volatility(pivot: pd.DataFrame, years: list[str]) -> dict:
    """Coefficient of variation, log-growth volatility and drawdowns."""
    latest = years[-1]
    latest_total = float(pivot.loc[latest].sum())
    rows = []
    for name in sorted(str(c) for c in pivot.columns):
        values = [float(pivot.loc[fy, name]) for fy in years]
        if max(values) < VOLUME_MIN:
            continue
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        sd = math.sqrt(variance)
        log_growth = [
            math.log(current / previous)
            for previous, current in zip(values, values[1:])
            if previous > 0 and current > 0
        ]
        if len(log_growth) > 1:
            gm = sum(log_growth) / len(log_growth)
            gv = sum((x - gm) ** 2 for x in log_growth) / len(log_growth)
            log_vol = math.sqrt(gv)
        else:
            log_vol = None
        peak = 0.0
        drawdown = 0.0
        for value in values:
            peak = max(peak, value)
            if peak > 0:
                drawdown = max(drawdown, (peak - value) / peak)
        latest_share = (float(pivot.loc[latest, name]) / latest_total * 100
                        if latest_total else 0.0)
        rows.append({
            "country": name,
            "n_years": len(years),
            "total": int(sum(values)),
            "mean": _round(mean, 2),
            "sd": _round(sd, 2),
            "cv": _round(sd / mean, 4) if mean else None,
            "log_growth_volatility": _round(log_vol, 4)
            if log_vol is not None else None,
            "max_drawdown_pct": _round(drawdown * 100, 3),
            "latest_share_pct": _round(latest_share, 3),
        })
    rows.sort(key=lambda r: (r["cv"] if r["cv"] is not None else -1,
                             r["country"]), reverse=True)

    thresholds = {}
    for threshold in (1.0, 5.0, 10.0):
        above = [r["country"] for r in rows
                 if r["latest_share_pct"] >= threshold]
        thresholds[f"above_{int(threshold)}pct"] = above
    return {
        "years": years,
        "latest": latest,
        "min_max_count": VOLUME_MIN,
        "destinations": rows,
        "counts_above_threshold": {
            key: {"count": len(value), "countries": value}
            for key, value in thresholds.items()
        },
    }


def growth_outliers(pivot: pd.DataFrame, years: list[str]) -> dict:
    """Robust-z outliers in year-over-year growth with a minimum base."""
    records = []
    for previous, current in zip(years, years[1:]):
        pre = pivot.loc[previous]
        post = pivot.loc[current]
        for name in sorted(str(c) for c in pivot.columns):
            a = float(pre[name])
            b = float(post[name])
            if a < GROWTH_MIN_BASE or b < GROWTH_MIN_BASE:
                continue
            records.append({
                "from": previous,
                "to": current,
                "country": name,
                "previous": int(a),
                "current": int(b),
                "growth_pct": _round((b / a - 1) * 100, 2),
            })
    if not records:
        return {"method": "robust_z", "min_base": GROWTH_MIN_BASE,
                "n_pairs": 0, "positive": [], "negative": []}
    growth = pd.Series([r["growth_pct"] for r in records])
    median = float(growth.median())
    mad = float((growth - median).abs().median())
    scale = 1.4826 * mad if mad > 0 else 1.0
    for record in records:
        record["robust_z"] = _round((record["growth_pct"] - median) / scale, 2)
    records.sort(key=lambda r: r["robust_z"], reverse=True)
    return {
        "method": "robust_z",
        "min_base": GROWTH_MIN_BASE,
        "n_pairs": len(records),
        "median_growth_pct": _round(median, 3),
        "mad_pct": _round(mad, 3),
        "robust_scale_pct": _round(scale, 3),
        "positive": records[:OUTLIER_N],
        "negative": records[-OUTLIER_N:][::-1],
    }


def build() -> dict:
    panel = load_panel(safe=True)
    cy = country_year(panel)
    pivot = _pivot(cy)
    years = _full_years(cy)
    present = [fy for fy in years if fy in set(pivot.index)]
    volatility = destination_volatility(pivot, present)
    latest_total = float(pivot.loc[present[-1]].sum())

    meta = {
        "source": "migration_parser.research.datasets.country_year",
        "safe_rows": int(len(panel)),
        "safe_documents": int(panel["doc_id"].nunique()),
        "country_year_rows": int(len(cy)),
        "fiscal_years": present,
        "missing_fiscal_years": sorted(
            {str(fy) for fy in cy["fiscal_year"]}
            - {str(fy) for fy in present}, key=_fy_key),
        "base_fy": BASE_FY,
        "latest_fy": LATEST_FY,
        "partial_fy": PARTIAL_FY,
        "partial_excluded": True,
        "thresholds": {
            "active_destination": ACTIVE_THRESHOLD,
            "rank_min_count": RANK_MIN_COUNT,
            "growth_min_base": GROWTH_MIN_BASE,
            "volatility_min_max_count": VOLUME_MIN,
            "top_n": TOP_N,
            "outlier_n": OUTLIER_N,
        },
        "latest_total": int(latest_total),
        "caveats": [
            "Safe panel only: analysis_safe=true, one granularity per FY, "
            "country detail rows with gender=total.",
            "2083/84 is partial and is excluded from all trends and "
            "decompositions.",
            "2080/81 to 2081/82 and earlier transitions use adjacent observed "
            "fiscal years; 2075/76 has no safe country rows.",
            "Active means >=100 approvals in a fiscal year; new/retired "
            "corridors are threshold crossings, not necessarily first-ever "
            "migration.",
            "Approvals are events/permits, not unique individuals; re-entry "
            "and repeat migration are not identified here.",
            "There are no district-by-destination flows in this panel.",
            "HHI uses squared shares on a 0-1 scale, not multiplied by 10,000.",
            "Robust z uses median growth and 1.4826*MAD; a zero MAD falls back "
            "to a scale of 1 percentage point.",
        ],
    }

    return {
        "meta": meta,
        "rank_panel": annual_rank_panel(pivot, present),
        "rank_stability": rank_stability(pivot, present),
        "turnover": corridor_turnover(pivot, present),
        "recovery": recovery_decomposition(pivot),
        "concentration": concentration_decomposition(pivot),
        "volatility": volatility,
        "outliers": growth_outliers(pivot, present),
    }
