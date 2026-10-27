"""Deeper origin-district patterns for the migration research series.

The module reads the same safe, single-basis builders as the pattern book and
adds concentration, convergence, transition, contribution, volatility,
province and gender diagnostics. Every returned value is JSON-serializable.

The panel has origin-district totals only. It does not contain district x
destination flows, so none of these metrics identify a district's destination
mix. The partial fiscal year is excluded from every comparison.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .audit import _fy_key
from .datasets import district_gender_year, district_year, load_panel

FIRST_COMPLETE_FY = "2074/75"
LATEST_FY = "2082/83"
PARTIAL_FY = "2083/84"
TOP_N = 10
N_DECILES = 10
MIN_VOLATILITY_BASE = 1000
MIN_GENDER_TOTAL = 1000


def _complete_years(dist: pd.DataFrame) -> list[str]:
    years = [fy for fy in dist["fiscal_year"].dropna().unique()
             if str(fy) != PARTIAL_FY]
    years = sorted(years, key=_fy_key)
    return [str(fy) for fy in years if _fy_key(fy) <= _fy_key(LATEST_FY)]


def _first_year(years: list[str]) -> str:
    if FIRST_COMPLETE_FY in years:
        return FIRST_COMPLETE_FY
    return years[0]


def _latest_year(years: list[str]) -> str:
    if LATEST_FY in years:
        return LATEST_FY
    return years[-1]


def _r(value, digits: int = 6):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _int(value) -> int:
    return int(round(float(value)))


def _pct(value: float) -> float:
    return round(100.0 * float(value), 4)


def _pivot(dist: pd.DataFrame, years: list[str]) -> pd.DataFrame:
    d = dist[dist["fiscal_year"].isin(years)]
    return d.pivot_table(index="district", columns="fiscal_year",
                         values="count", aggfunc="sum", fill_value=0)


def _decile_labels(values: pd.Series) -> pd.Series:
    n = len(values)
    if n == 0:
        return pd.Series(dtype="int64")
    ranks = values.rank(method="first", ascending=True)
    labels = np.ceil(ranks / n * N_DECILES).astype(int).clip(1, N_DECILES)
    return pd.Series(labels, index=values.index, dtype="int64")


def annual_concentration(dist: pd.DataFrame, years: list[str]) -> list[dict]:
    rows = []
    for fy in years:
        block = dist[(dist["fiscal_year"] == fy) & (dist["count"] > 0)]
        values = block.groupby("district")["count"].sum().sort_values(
            ascending=False)
        total = float(values.sum())
        if not total:
            continue
        shares = values / total
        rows.append({
            "fiscal_year": fy,
            "count": _int(total),
            "active_districts": _int(len(values)),
            "hhi": _r(float((shares ** 2).sum()), 6),
            "effective_districts": _r(1.0 / float((shares ** 2).sum()), 3),
            "top5_share_pct": _r(_pct(shares.head(5).sum()), 4),
            "top10_share_pct": _r(_pct(shares.head(10).sum()), 4),
            "top_district": str(values.index[0]),
            "top_district_count": _int(values.iloc[0]),
            "top_district_share_pct": _r(_pct(shares.iloc[0]), 4),
        })
    return rows


def _common(first: pd.Series, last: pd.Series) -> pd.Index:
    return first.index.intersection(last.index)


def _beta_convergence(first: pd.Series, last: pd.Series) -> dict:
    names = _common(first, last)
    x, y = [], []
    for name in names:
        a = float(first[name])
        b = float(last[name])
        if a <= 0 or b <= 0:
            continue
        x.append(math.log(a))
        y.append(math.log(b / a))
    n = len(x)
    if n < 3:
        return {"n": n, "slope": None, "intercept": None, "stderr": None,
                "p_value": None, "r_squared": None, "converging": None}
    try:
        from scipy import stats

        fit = stats.linregress(x, y)
        slope = float(fit.slope)
        intercept = float(fit.intercept)
        stderr = float(fit.stderr)
        p_value = float(fit.pvalue)
        r_squared = float(fit.rvalue ** 2)
    except ImportError:  # pragma: no cover - scipy is a declared extra
        xa = np.asarray(x)
        ya = np.asarray(y)
        slope, intercept = np.polyfit(xa, ya, 1)
        fitted = slope * xa + intercept
        ss_res = float(((ya - fitted) ** 2).sum())
        ss_tot = float(((ya - ya.mean()) ** 2).sum())
        r_squared = 1.0 - ss_res / ss_tot if ss_tot else 0.0
        stderr = None
        p_value = None
    return {
        "n": n,
        "slope": _r(slope, 6),
        "intercept": _r(intercept, 6),
        "stderr": _r(stderr, 6),
        "p_value": _r(p_value, 6),
        "r_squared": _r(r_squared, 6),
        "converging": bool(slope < 0),
    }


def _sigma_series(pivot: pd.DataFrame, years: list[str]) -> list[dict]:
    balanced = pivot[(pivot[years] > 0).all(axis=1)]
    rows = []
    for fy in years:
        values = balanced[fy].astype(float)
        mean = float(values.mean()) if len(values) else 0.0
        sd = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        cv = sd / mean if mean else None
        logs = np.log(values[values > 0])
        rows.append({
            "fiscal_year": fy,
            "n": _int(len(values)),
            "mean": _r(mean, 3),
            "sd": _r(sd, 3),
            "cv": _r(cv, 6),
            "cv_pct": _r(_pct(cv) if cv is not None else None, 4),
            "log_sd": _r(float(logs.std(ddof=1)) if len(logs) > 1 else None, 6),
        })
    return rows


def _rank_mobility(first: pd.Series, last: pd.Series) -> dict:
    names = [name for name in _common(first, last)
             if float(first[name]) > 0 and float(last[name]) > 0]
    if len(names) < 3:
        return {"n": int(len(names)), "spearman": None, "mobility": None,
                "mean_abs_rank_change": None, "median_abs_rank_change": None,
                "share_moved_decile_pct": None}
    a = first[names].astype(float)
    b = last[names].astype(float)
    rho = float(a.corr(b, method="spearman"))
    rank_a = a.rank(method="average", ascending=True)
    rank_b = b.rank(method="average", ascending=True)
    move = (rank_a - rank_b).abs()
    dec_a = _decile_labels(a)
    dec_b = _decile_labels(b)
    moved = float((dec_a.to_numpy() != dec_b.to_numpy()).mean())
    return {
        "n": _int(len(names)),
        "spearman": _r(rho, 6),
        "mobility": _r(1.0 - rho, 6),
        "mean_abs_rank_change": _r(float(move.mean()), 4),
        "median_abs_rank_change": _r(float(move.median()), 4),
        "share_moved_decile_pct": _r(_pct(moved), 4),
    }


def decile_transitions(first: pd.Series, last: pd.Series) -> dict:
    names = [name for name in _common(first, last)
             if float(first[name]) > 0 and float(last[name]) > 0]
    labels = [f"D{i}" for i in range(1, N_DECILES + 1)]
    if len(names) < N_DECILES:
        return {"row_labels": labels, "col_labels": labels,
                "counts": [[0] * N_DECILES for _ in labels],
                "shares": [[None] * N_DECILES for _ in labels],
                "persistence_rate": None, "n": _int(len(names))}
    a = first[names].astype(float)
    b = last[names].astype(float)
    from_dec = _decile_labels(a).map(lambda i: f"D{i}")
    to_dec = _decile_labels(b).map(lambda i: f"D{i}")
    table = pd.crosstab(from_dec, to_dec).reindex(index=labels, columns=labels,
                                                  fill_value=0)
    counts = table.to_numpy(dtype="int64")
    row_totals = counts.sum(axis=1, keepdims=True)
    shares = np.divide(counts, row_totals, where=row_totals != 0,
                       out=np.full(counts.shape, np.nan, dtype=float))
    total = int(counts.sum())
    persistence = float(np.trace(counts) / total) if total else None
    mean_diagonal = float(np.nanmean(np.diag(shares))) if total else None
    return {
        "row_labels": labels,
        "col_labels": labels,
        "counts": counts.astype(int).tolist(),
        "row_totals": [int(v) for v in row_totals.ravel()],
        "shares": [[_r(v, 6) if math.isfinite(float(v)) else None
                    for v in row] for row in shares],
        "persistence_rate": _r(persistence, 6),
        "mean_diagonal_share": _r(mean_diagonal, 6),
        "n": total,
    }


def convergence(dist: pd.DataFrame, years: list[str],
                first: str, latest: str) -> dict:
    pivot = _pivot(dist, years)
    if first not in pivot.columns or latest not in pivot.columns:
        return {"first": first, "latest": latest}
    first_row = pivot[first]
    last_row = pivot[latest]
    beta = _beta_convergence(first_row, last_row)
    sigma = _sigma_series(pivot, years)
    mobility = _rank_mobility(first_row, last_row)
    first_cv = sigma[0]["cv"] if sigma else None
    latest_cv = sigma[-1]["cv"] if sigma else None
    change = (latest_cv - first_cv
              if first_cv is not None and latest_cv is not None else None)
    return {
        "first": first,
        "latest": latest,
        "beta": beta,
        "sigma": sigma,
        "sigma_change": _r(change, 6),
        "sigma_converging": bool(change < 0) if change is not None else None,
        "mobility": mobility,
    }


def contributions(dist: pd.DataFrame, first: str, latest: str) -> dict:
    pivot = _pivot(dist, [first, latest])
    if first not in pivot.columns or latest not in pivot.columns:
        return {"first": first, "latest": latest, "rows": []}
    base = pivot[first].astype(float)
    last = pivot[latest].astype(float)
    base_total = float(base.sum())
    last_total = float(last.sum())
    delta_total = last_total - base_total
    rows = []
    for name in base.index.union(last.index):
        a = float(base.get(name, 0.0))
        b = float(last.get(name, 0.0))
        delta = b - a
        rows.append({
            "district": str(name),
            "initial_count": _int(a),
            "latest_count": _int(b),
            "change": _int(delta),
            "change_pct": _r((b / a - 1) * 100 if a else None, 3),
            "contribution_pct": _r(delta / delta_total * 100
                                   if delta_total else None, 6),
        })
    positives = sorted([r for r in rows if r["change"] > 0],
                       key=lambda r: r["change"], reverse=True)
    negatives = sorted([r for r in rows if r["change"] < 0],
                       key=lambda r: r["change"])
    return {
        "first": first,
        "latest": latest,
        "initial_total": _int(base_total),
        "latest_total": _int(last_total),
        "national_change": _int(delta_total),
        "national_growth_pct": _r((last_total / base_total - 1) * 100
                                  if base_total else None, 3),
        "top_positive": positives[:TOP_N],
        "top_negative": negatives[:TOP_N],
        "rows": rows,
    }


def volatility(dist: pd.DataFrame, years: list[str],
               min_base: int = MIN_VOLATILITY_BASE) -> dict:
    pivot = _pivot(dist, years)
    balanced = pivot[(pivot[years] > 0).all(axis=1)]
    rows = []
    for name, row in balanced.iterrows():
        base = float(row[years[0]])
        if base < min_base:
            continue
        values = row[years].astype(float).to_numpy()
        log_growth = np.diff(np.log(values))
        level_mean = float(values.mean())
        level_sd = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        rows.append({
            "district": str(name),
            "initial_count": _int(base),
            "latest_count": _int(values[-1]),
            "mean_count": _r(level_mean, 3),
            "cv": _r(level_sd / level_mean if level_mean else None, 6),
            "log_growth_sd": _r(float(log_growth.std(ddof=1)), 6),
            "mean_log_growth": _r(float(log_growth.mean()), 6),
        })
    most = sorted(rows, key=lambda r: r["log_growth_sd"] or 0.0, reverse=True)
    least = sorted(rows, key=lambda r: r["log_growth_sd"] or 0.0)
    return {
        "years": years,
        "min_initial_count": int(min_base),
        "n_considered": _int(len(rows)),
        "most_volatile": most[:TOP_N],
        "least_volatile": least[:TOP_N],
    }


def province_aggregation(dist: pd.DataFrame, years: list[str],
                         first: str, latest: str) -> dict:
    d = dist[dist["fiscal_year"].isin(years) & dist["province"].notna()]
    totals = d.pivot_table(index="fiscal_year", columns="province",
                           values="count", aggfunc="sum", fill_value=0)
    totals = totals.reindex(years).fillna(0)
    share = totals.div(totals.sum(axis=1).replace(0, pd.NA), axis=0)
    by_year = []
    for fy in years:
        by_year.append({
            "fiscal_year": fy,
            "total": _int(totals.loc[fy].sum()),
            "provinces": {str(name): _int(value)
                          for name, value in totals.loc[fy].items()},
            "shares_pct": {str(name): _r(_pct(value), 4)
                           for name, value in share.loc[fy].items()
                           if pd.notna(value)},
        })
    change = []
    if first in totals.index and latest in totals.index:
        for name in totals.columns:
            a = float(totals.loc[first, name])
            b = float(totals.loc[latest, name])
            sa = float(share.loc[first, name]) if pd.notna(share.loc[first, name]) else None
            sb = float(share.loc[latest, name]) if pd.notna(share.loc[latest, name]) else None
            change.append({
                "province": str(name),
                "initial_count": _int(a),
                "latest_count": _int(b),
                "change": _int(b - a),
                "growth_pct": _r((b / a - 1) * 100 if a else None, 3),
                "initial_share_pct": _r(_pct(sa) if sa is not None else None, 4),
                "latest_share_pct": _r(_pct(sb) if sb is not None else None, 4),
                "share_change_pp": _r(_pct(sb - sa)
                                      if sa is not None and sb is not None
                                      else None, 4),
            })
    change.sort(key=lambda r: r["change"], reverse=True)
    return {
        "first": first,
        "latest": latest,
        "by_year": by_year,
        "change": change,
    }


def gender(dist_gender: pd.DataFrame, years: list[str],
           first: str, latest: str,
           min_total: int = MIN_GENDER_TOTAL) -> dict:
    d = dist_gender[dist_gender["fiscal_year"].isin(years)]
    pivot = d.pivot_table(index="district", columns=["fiscal_year", "gender"],
                          values="count", aggfunc="sum", fill_value=0)
    annual = []
    for fy in years:
        male = float(pivot.get((fy, "male"), pd.Series(dtype=float)).sum())
        female = float(pivot.get((fy, "female"), pd.Series(dtype=float)).sum())
        total = male + female
        annual.append({
            "fiscal_year": fy,
            "male": _int(male),
            "female": _int(female),
            "total": _int(total),
            "female_share_pct": _r(_pct(female / total) if total else None, 4),
        })
    rows = []
    if (first, "male") in pivot.columns and (latest, "male") in pivot.columns:
        for name in pivot.index:
            bm = float(pivot.loc[name].get((first, "male"), 0.0))
            bf = float(pivot.loc[name].get((first, "female"), 0.0))
            lm = float(pivot.loc[name].get((latest, "male"), 0.0))
            lf = float(pivot.loc[name].get((latest, "female"), 0.0))
            bt = bm + bf
            lt = lm + lf
            if bt < min_total or lt < min_total:
                continue
            bs = bf / bt if bt else None
            ls = lf / lt if lt else None
            rows.append({
                "district": str(name),
                "initial_total": _int(bt),
                "latest_total": _int(lt),
                "initial_female_share_pct": _r(_pct(bs) if bs is not None else None, 4),
                "latest_female_share_pct": _r(_pct(ls) if ls is not None else None, 4),
                "change_pp": _r(_pct(ls - bs)
                                if bs is not None and ls is not None else None, 4),
            })
    rows.sort(key=lambda r: r["change_pp"] if r["change_pp"] is not None else 0,
              reverse=True)
    return {
        "first": first,
        "latest": latest,
        "min_total": int(min_total),
        "annual_national": annual,
        "latest_share": sorted(rows,
                               key=lambda r: r["latest_female_share_pct"]
                               if r["latest_female_share_pct"] is not None else 0,
                               reverse=True),
        "increases": rows[:TOP_N],
        "decreases": list(reversed(rows[-TOP_N:])),
        "n": _int(len(rows)),
    }


def build() -> dict:
    panel = load_panel(safe=True)
    dist = district_year(panel)
    dgen = district_gender_year(panel)
    years = _complete_years(dist)
    first = _first_year(years)
    latest = _latest_year(years)

    meta = {
        "safe_rows": _int(len(panel)),
        "safe_documents": _int(panel["doc_id"].nunique()),
        "district_rows": _int(len(dist)),
        "district_gender_rows": _int(len(dgen)),
        "fiscal_years": years,
        "first_fy": first,
        "latest_fy": latest,
        "partial_fy_excluded": PARTIAL_FY,
        "thresholds": {
            "top_n": TOP_N,
            "n_deciles": N_DECILES,
            "min_volatility_base": MIN_VOLATILITY_BASE,
            "min_gender_total": MIN_GENDER_TOTAL,
        },
        "formulas": {
            "hhi": "sum((district_count / year_total) ** 2)",
            "top_k_share": "sum(top k district counts) / year_total",
            "beta_convergence": (
                "OLS slope of log(latest / initial) on log(initial), "
                "across districts present in both years"),
            "sigma_convergence": (
                "coefficient of variation of district counts within a year, "
                "on the balanced district panel; convergence if CV falls"),
            "rank_mobility": (
                "1 - Spearman rank correlation of initial and latest counts; "
                "higher mobility means more rank reshuffling"),
            "transition": (
                "deciles assigned by within-year count rank; cells are "
                "initial-decile x latest-decile counts and row shares"),
            "contribution": (
                "(latest - initial) / (national latest - national initial); "
                "sums to 100 percent across all districts"),
            "volatility": (
                "standard deviation of annual log growth, districts positive "
                "in every complete year and above the minimum initial count"),
            "gender": (
                "female / (male + female) per district; change is latest minus "
                "initial female share in percentage points"),
        },
        "caveats": [
            "The panel has no district x destination flows; destination mix "
            "cannot be inferred.",
            f"{PARTIAL_FY} is partial and excluded from all trend comparisons.",
            "Nawalparasi and Rukum split into East/West units during the "
            "series; those districts inflate raw contribution extremes.",
            "District rows are analysis_safe and use one granularity per year.",
            "Province is taken from the district row and is available for all "
            "resolved district entities.",
            "Beta and sigma results are descriptive, not causal.",
        ],
    }

    pivot = _pivot(dist, years)
    return {
        "meta": meta,
        "annual_concentration": annual_concentration(dist, years),
        "convergence": convergence(dist, years, first, latest),
        "transitions": {
            "deciles": decile_transitions(pivot[first], pivot[latest]),
        },
        "contributions": contributions(dist, first, latest),
        "volatility": volatility(dist, years),
        "provinces": province_aggregation(dist, years, first, latest),
        "gender": gender(dgen, years, first, latest),
    }
