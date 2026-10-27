"""Deep country-level gender analysis for the migration pattern book.

This module extends the destination and gender/channel pattern modules with a
country-focused view of approved permits. It reads the safe, single-basis
``country_gender_year`` builder, keeps only complete fiscal years, and treats
sex as a characteristic reported at approval time.

Nothing here is causal: the outputs describe approved permits, not arrivals,
returnees, or the resident population.
"""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from .audit import _fy_key
from .datasets import country_gender_year, country_year, load_panel

BASE_FY = "2079/80"
LATEST_FY = "2082/83"
PARTIAL_FY = "2083/84"

MIN_VOLUME = 1000
THRESHOLD_VARIANTS = (500, 1000, 2000)
LARGE_VOLUME = 5000
TOP_DESTINATIONS = 12
TOP_CONTRIBUTORS = 5
TOP_ROWS = 10

SEX_CAVEAT = (
    "Sex is reported when an approval is recorded, not at arrival, return, or "
    "in the resident stock. Female shares therefore describe approved permits."
)


def _r(value, digits: int = 4):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits)


def _int(value) -> int:
    return int(round(float(value)))


def _share_pct(female: float, total: float):
    if total <= 0:
        return None
    return 100.0 * float(female) / float(total)


def _growth_pct(before: float, after: float):
    if before is None or after is None or before <= 0:
        return None
    return (float(after) / float(before) - 1.0) * 100.0


def _safe_corr(x: list[float], y: list[float], method: str = "pearson"):
    if len(x) < 3 or len(y) < 3:
        return None
    sx = pd.Series(x, dtype="float64")
    sy = pd.Series(y, dtype="float64")
    if sx.nunique() < 2 or sy.nunique() < 2:
        return None
    value = sx.corr(sy, method=method)
    return _r(value, 4)


def _regression(x: list[float], y: list[float]) -> dict:
    n = len(x)
    if n < 3:
        return {"n": n, "slope": None, "intercept": None, "r": None,
                "r_squared": None}
    sx = pd.Series(x, dtype="float64")
    sy = pd.Series(y, dtype="float64")
    if sx.nunique() < 2:
        return {"n": n, "slope": None, "intercept": None, "r": None,
                "r_squared": None}
    slope = float(sy.cov(sx) / sx.var())
    intercept = float(sy.mean() - slope * sx.mean())
    r = float(sx.corr(sy))
    return {
        "n": n,
        "slope": _r(slope, 4),
        "intercept": _r(intercept, 4),
        "r": _r(r, 4),
        "r_squared": _r(r * r, 4),
    }


def _gender_frame(cg: pd.DataFrame, fiscal_year: str) -> pd.DataFrame:
    block = cg[cg["fiscal_year"] == fiscal_year]
    frame = block.pivot_table(index="country", columns="gender",
                              values="count", aggfunc="sum", fill_value=0)
    for column in ("male", "female"):
        if column not in frame:
            frame[column] = 0
    frame["total"] = frame["male"] + frame["female"]
    return frame


def _complete_years(cg: pd.DataFrame) -> list[str]:
    years = sorted({str(fy) for fy in cg["fiscal_year"]}, key=_fy_key)
    return [fy for fy in years if fy != PARTIAL_FY]


def _annual(cg: pd.DataFrame, cy: pd.DataFrame,
            years: list[str]) -> list[dict]:
    gender = cg.groupby(["fiscal_year", "gender"])["count"].sum().unstack(
        fill_value=0)
    country_totals = cy.groupby("fiscal_year")["count"].sum()
    rows = []
    for fy in years:
        female = int(gender.loc[fy].get("female", 0)) if fy in gender.index else 0
        male = int(gender.loc[fy].get("male", 0)) if fy in gender.index else 0
        total = female + male
        block = _gender_frame(cg, fy)
        positive = block[block["total"] > 0]
        female_destinations = int((block["female"] > 0).sum())
        male_destinations = int((block["male"] > 0).sum())
        country_total = int(country_totals.get(fy, 0))
        rows.append({
            "fiscal_year": fy,
            "female": female,
            "male": male,
            "total": total,
            "female_share_pct": _r(_share_pct(female, total), 2),
            "female_change_prior": None,
            "n_destinations": int(len(block)),
            "n_positive_destinations": int(len(positive)),
            "n_destinations_with_female": female_destinations,
            "n_destinations_with_male": male_destinations,
            "share_destinations_with_female_pct": _r(
                _share_pct(female_destinations, len(block)), 2),
            "country_year_total": country_total,
            "gender_total": total,
            "reconciles_with_country_year": bool(total == country_total),
            "is_base": fy == BASE_FY,
            "is_latest": fy == LATEST_FY,
            "complete_year": True,
        })
    for previous, current in zip(rows, rows[1:]):
        if previous["total"]:
            current["female_change_prior"] = _r(
                current["female_share_pct"] - previous["female_share_pct"], 2)
    return rows


def _country_deep(b: pd.DataFrame, n: pd.DataFrame,
                  threshold: int) -> list[dict]:
    rows = []
    for country in sorted(set(b.index) | set(n.index)):
        nb = b.loc[country] if country in b.index else None
        nn = n.loc[country] if country in n.index else None
        if nn is None:
            continue
        latest_total = float(nn["total"])
        if latest_total < threshold:
            continue
        base_total = float(nb["total"]) if nb is not None else 0.0
        base_female = float(nb["female"]) if nb is not None else 0.0
        base_male = float(nb["male"]) if nb is not None else 0.0
        latest_female = float(nn["female"])
        latest_male = float(nn["male"])
        base_share = _share_pct(base_female, base_total)
        latest_share = _share_pct(latest_female, latest_total)
        female_change = latest_female - base_female
        male_change = latest_male - base_male
        female_growth = _growth_pct(base_female, latest_female)
        male_growth = _growth_pct(base_male, latest_male)
        total_growth = _growth_pct(base_total, latest_total)
        rows.append({
            "country": str(country),
            "base_total": _int(base_total),
            "latest_total": _int(latest_total),
            "base_female": _int(base_female),
            "base_male": _int(base_male),
            "latest_female": _int(latest_female),
            "latest_male": _int(latest_male),
            "female_change": _int(female_change),
            "male_change": _int(male_change),
            "total_change": _int(latest_total - base_total),
            "base_female_share_pct": _r(base_share, 2),
            "latest_female_share_pct": _r(latest_share, 2),
            "female_share_change_pp": _r(latest_share - base_share, 2)
            if base_share is not None else None,
            "female_growth_pct": _r(female_growth, 2),
            "male_growth_pct": _r(male_growth, 2),
            "female_minus_male_growth_pp": _r(
                female_growth - male_growth, 2)
            if female_growth is not None and male_growth is not None else None,
            "total_growth_pct": _r(total_growth, 2),
            "female_growth_exceeds_male": (
                female_growth > male_growth
                if female_growth is not None and male_growth is not None
                else None),
            "female_additions_exceed_male": bool(female_change > male_change),
            "base_above_threshold": bool(base_total >= threshold),
        })
    rows.sort(key=lambda row: row["latest_total"], reverse=True)
    return rows


def _country_trajectories(cg: pd.DataFrame, years: list[str]) -> dict:
    latest = _gender_frame(cg, LATEST_FY)
    latest = latest.sort_values("total", ascending=False)
    top = list(latest.head(TOP_DESTINATIONS).index)
    frames = {fy: _gender_frame(cg, fy) for fy in years}
    rows = []
    for country in top:
        series = []
        for fy in years:
            frame = frames[fy]
            if country not in frame.index:
                series.append({
                    "fiscal_year": fy, "female": 0, "male": 0, "total": 0,
                    "female_share_pct": None})
                continue
            row = frame.loc[country]
            total = float(row["total"])
            series.append({
                "fiscal_year": fy,
                "female": _int(row["female"]),
                "male": _int(row["male"]),
                "total": _int(total),
                "female_share_pct": _r(_share_pct(row["female"], total), 2),
            })
        latest_row = latest.loc[country]
        rows.append({
            "country": str(country),
            "latest_total": _int(latest_row["total"]),
            "latest_female_share_pct": _r(
                _share_pct(latest_row["female"], latest_row["total"]), 2),
            "series": series,
        })
    return {"years": list(years), "destinations": rows}


def _country_ranks(deep: list[dict]) -> dict:
    by_share = sorted(deep, key=lambda row: (
        row["latest_female_share_pct"] is None,
        -(row["latest_female_share_pct"] or 0),
        row["country"],
    ))
    by_change = sorted(
        [row for row in deep if row["female_share_change_pp"] is not None],
        key=lambda row: (-row["female_share_change_pp"], row["country"]))
    return {
        "by_latest_female_share": [
            {
                "rank": rank,
                "country": row["country"],
                "latest_total": row["latest_total"],
                "latest_female_share_pct": row["latest_female_share_pct"],
            }
            for rank, row in enumerate(by_share, start=1)
        ],
        "by_female_share_change": [
            {
                "rank": rank,
                "country": row["country"],
                "latest_total": row["latest_total"],
                "female_share_change_pp": row["female_share_change_pp"],
            }
            for rank, row in enumerate(by_change, start=1)
        ],
    }


def _distribution(cg: pd.DataFrame, years: list[str],
                  threshold: int) -> list[dict]:
    rows = []
    for fy in years:
        frame = _gender_frame(cg, fy)
        frame = frame[frame["total"] >= threshold]
        if frame.empty:
            rows.append({
                "fiscal_year": fy, "n_countries": 0,
                "unweighted_mean_female_share_pct": None,
                "median_female_share_pct": None,
                "weighted_female_share_pct": None,
                "sd_female_share_pp": None,
                "min_female_share_pct": None,
                "max_female_share_pct": None,
            })
            continue
        shares = (100.0 * frame["female"] / frame["total"]).astype("float64")
        rows.append({
            "fiscal_year": fy,
            "n_countries": int(len(frame)),
            "unweighted_mean_female_share_pct": _r(shares.mean(), 2),
            "median_female_share_pct": _r(shares.median(), 2),
            "weighted_female_share_pct": _r(
                _share_pct(frame["female"].sum(), frame["total"].sum()), 2),
            "sd_female_share_pp": _r(shares.std(ddof=0), 2),
            "min_female_share_pct": _r(shares.min(), 2),
            "max_female_share_pct": _r(shares.max(), 2),
        })
    return rows


def _volatility_persistence(cg: pd.DataFrame, years: list[str],
                            threshold: int) -> dict:
    latest = _gender_frame(cg, LATEST_FY)
    eligible = sorted(latest[latest["total"] >= threshold].index)
    frames = {fy: _gender_frame(cg, fy) for fy in years}
    rows = []
    base_pairs = []
    latest_pairs = []
    for country in eligible:
        shares = []
        for fy in years:
            frame = frames[fy]
            if country not in frame.index:
                continue
            total = float(frame.loc[country, "total"])
            if total <= 0:
                continue
            shares.append(100.0 * float(frame.loc[country, "female"]) / total)
        if len(shares) < 2:
            continue
        changes = [current - previous
                   for previous, current in zip(shares, shares[1:])]
        mean = sum(shares) / len(shares)
        sd = math.sqrt(sum((value - mean) ** 2 for value in shares)
                       / len(shares))
        rows.append({
            "country": str(country),
            "n_years": len(shares),
            "mean_female_share_pct": _r(mean, 2),
            "sd_female_share_pp": _r(sd, 2),
            "range_pp": _r(max(shares) - min(shares), 2),
            "mean_abs_yoy_change_pp": _r(
                sum(abs(value) for value in changes) / len(changes), 2),
            "latest_female_share_pct": _r(shares[-1], 2),
        })
        if len(shares) == len(years):
            base_pairs.append((shares[0], shares[-1]))
    rows.sort(key=lambda row: row["sd_female_share_pp"], reverse=True)
    if base_pairs:
        base_shares = [pair[0] for pair in base_pairs]
        latest_shares = [pair[1] for pair in base_pairs]
        persistence = _safe_corr(base_shares, latest_shares)
        rank_persistence = _safe_corr(base_shares, latest_shares, "spearman")
        mean_abs = sum(abs(b - a) for a, b in base_pairs) / len(base_pairs)
    else:
        persistence = None
        rank_persistence = None
        mean_abs = None
    return {
        "threshold": threshold,
        "n_countries": len(rows),
        "mean_within_country_sd_pp": _r(
            sum(row["sd_female_share_pp"] for row in rows) / len(rows), 2)
        if rows else None,
        "cross_sectional_sd_latest_pp": _r(
            _cross_sd([row["latest_female_share_pct"] for row in rows]), 2)
        if rows else None,
        "base_latest_share_correlation": persistence,
        "base_latest_rank_correlation": rank_persistence,
        "mean_abs_base_to_latest_change_pp": _r(mean_abs, 2),
        "destinations": rows,
    }


def _cross_sd(values: list[float]):
    clean = [float(value) for value in values if value is not None]
    if len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    return math.sqrt(sum((value - mean) ** 2 for value in clean) / len(clean))


def _convergence(b: pd.DataFrame, n: pd.DataFrame, threshold: int) -> dict:
    pairs = []
    for country in sorted(set(b.index) & set(n.index)):
        base_total = float(b.loc[country, "total"])
        latest_total = float(n.loc[country, "total"])
        if base_total <= 0 or latest_total < threshold:
            continue
        base_share = 100.0 * float(b.loc[country, "female"]) / base_total
        latest_share = 100.0 * float(n.loc[country, "female"]) / latest_total
        pairs.append((str(country), base_share, latest_share, latest_total))
    x = [pair[1] for pair in pairs]
    y = [pair[2] - pair[1] for pair in pairs]
    regression = _regression(x, y)
    if pairs:
        ordered = sorted(pairs, key=lambda pair: pair[1])
        half = max(1, len(ordered) // 2)
        low = ordered[:half]
        high = ordered[half:]
        low_change = sum(pair[2] - pair[1] for pair in low) / len(low)
        high_change = sum(pair[2] - pair[1] for pair in high) / len(high)
    else:
        low_change = high_change = None
    return {
        "threshold": threshold,
        "n_countries": len(pairs),
        "slope_pp_per_initial_pp": regression["slope"],
        "intercept_pp": regression["intercept"],
        "correlation": regression["r"],
        "r_squared": regression["r_squared"],
        "low_initial_half_mean_change_pp": _r(low_change, 2),
        "high_initial_half_mean_change_pp": _r(high_change, 2),
        "converges_upward": bool(regression["slope"] is not None
                                 and regression["slope"] < 0),
        "pairs": [
            {"country": pair[0], "base_female_share_pct": _r(pair[1], 2),
             "latest_female_share_pct": _r(pair[2], 2),
             "change_pp": _r(pair[2] - pair[1], 2)}
            for pair in pairs
        ],
    }


def _contribution_decomposition(b: pd.DataFrame, n: pd.DataFrame) -> dict:
    base_total = float(b["total"].sum())
    latest_total = float(n["total"].sum())
    base_share = _share_pct(b["female"].sum(), base_total)
    latest_share = _share_pct(n["female"].sum(), latest_total)
    rows = []
    for country in sorted(set(b.index) | set(n.index)):
        nb = b.loc[country] if country in b.index else None
        nn = n.loc[country] if country in n.index else None
        b_total = float(nb["total"]) if nb is not None else 0.0
        n_total = float(nn["total"]) if nn is not None else 0.0
        b_share = _share_pct(nb["female"], b_total) if nb is not None else 0.0
        n_share = _share_pct(nn["female"], n_total) if nn is not None else 0.0
        b_share = b_share if b_share is not None else 0.0
        n_share = n_share if n_share is not None else 0.0
        w0 = b_total / base_total if base_total else 0.0
        w1 = n_total / latest_total if latest_total else 0.0
        within = w0 * (n_share - b_share)
        composition = b_share * (w1 - w0)
        interaction = (w1 - w0) * (n_share - b_share)
        rows.append({
            "country": str(country),
            "base_total": _int(b_total),
            "latest_total": _int(n_total),
            "base_female_share_pct": _r(b_share, 2),
            "latest_female_share_pct": _r(n_share, 2),
            "within_pp": _r(within, 6),
            "composition_pp": _r(composition, 6),
            "interaction_pp": _r(interaction, 6),
            "total_contribution_pp": _r(within + composition + interaction, 6),
        })
    within_total = sum(row["within_pp"] for row in rows)
    composition_total = sum(row["composition_pp"] for row in rows)
    interaction_total = sum(row["interaction_pp"] for row in rows)
    aggregate_change = latest_share - base_share
    ranked = sorted(rows, key=lambda row: row["within_pp"], reverse=True)
    positive = [row for row in ranked if row["within_pp"] > 0]
    negative = [row for row in ranked if row["within_pp"] < 0]
    top_positive = positive[:TOP_CONTRIBUTORS]
    top_sum = sum(row["within_pp"] for row in top_positive)
    gross_positive = sum(row["within_pp"] for row in positive)
    gross_negative = sum(row["within_pp"] for row in negative)
    return {
        "base_fiscal_year": BASE_FY,
        "latest_fiscal_year": LATEST_FY,
        "base_female_share_pct": _r(base_share, 4),
        "latest_female_share_pct": _r(latest_share, 4),
        "aggregate_change_pp": _r(aggregate_change, 6),
        "within_country_pp": _r(within_total, 6),
        "country_composition_pp": _r(composition_total, 6),
        "interaction_pp": _r(interaction_total, 6),
        "components_sum_pp": _r(
            within_total + composition_total + interaction_total, 6),
        "within_share_of_change_pct": _r(
            100.0 * within_total / aggregate_change, 2)
        if aggregate_change else None,
        "within_positive_pp": _r(gross_positive, 6),
        "within_negative_pp": _r(gross_negative, 6),
        "top_positive_within_pp": _r(top_sum, 6),
        "top_positive_share_of_positive_within_pct": _r(
            100.0 * top_sum / gross_positive, 2) if gross_positive else None,
        "top_positive_share_of_aggregate_change_pct": _r(
            100.0 * top_sum / aggregate_change, 2) if aggregate_change else None,
        "top_contributor_count": len(top_positive),
        "largest_within_increases": positive[:TOP_ROWS],
        "largest_within_decreases": negative[::-1][:TOP_ROWS],
        "ranking": ranked,
        "formula": (
            "delta female share = sum_i w_i0*delta s_i (within) + "
            "sum_i s_i0*delta w_i (composition) + "
            "sum_i delta w_i*delta s_i (interaction), with w as each "
            "destination's share of approvals and s as its female share."
        ),
    }


def _growth_divergence(b: pd.DataFrame, n: pd.DataFrame,
                       threshold: int) -> dict:
    base_female = float(b["female"].sum())
    base_male = float(b["male"].sum())
    latest_female = float(n["female"].sum())
    latest_male = float(n["male"].sum())
    female_growth = _growth_pct(base_female, latest_female)
    male_growth = _growth_pct(base_male, latest_male)
    overall = {
        "base_female": _int(base_female),
        "base_male": _int(base_male),
        "latest_female": _int(latest_female),
        "latest_male": _int(latest_male),
        "female_change": _int(latest_female - base_female),
        "male_change": _int(latest_male - base_male),
        "female_growth_pct": _r(female_growth, 2),
        "male_growth_pct": _r(male_growth, 2),
        "female_minus_male_growth_pp": _r(
            female_growth - male_growth, 2)
        if female_growth is not None and male_growth is not None else None,
        "female_share_change_pp": _r(
            _share_pct(latest_female, latest_female + latest_male)
            - _share_pct(base_female, base_female + base_male), 2),
    }
    rows = []
    for country in sorted(set(b.index) | set(n.index)):
        nb = b.loc[country] if country in b.index else None
        nn = n.loc[country] if country in n.index else None
        latest_total = float(nn["total"]) if nn is not None else 0.0
        if latest_total < threshold or nb is None:
            continue
        b_female = float(nb["female"])
        b_male = float(nb["male"])
        n_female = float(nn["female"])
        n_male = float(nn["male"])
        fg = _growth_pct(b_female, n_female)
        mg = _growth_pct(b_male, n_male)
        if fg is None or mg is None:
            continue
        rows.append({
            "country": str(country),
            "latest_total": _int(latest_total),
            "female_change": _int(n_female - b_female),
            "male_change": _int(n_male - b_male),
            "female_growth_pct": _r(fg, 2),
            "male_growth_pct": _r(mg, 2),
            "female_minus_male_growth_pp": _r(fg - mg, 2),
        })
    female_up_male_down = sorted(
        [row for row in rows
         if row["female_growth_pct"] > 0 and row["male_growth_pct"] < 0],
        key=lambda row: row["latest_total"], reverse=True)
    female_down_male_up = sorted(
        [row for row in rows
         if row["female_growth_pct"] < 0 and row["male_growth_pct"] > 0],
        key=lambda row: row["latest_total"], reverse=True)
    return {
        "threshold": threshold,
        "overall": overall,
        "n_countries_compared": len(rows),
        "female_up_male_down": female_up_male_down,
        "female_down_male_up": female_down_male_up,
        "n_female_up_male_down": len(female_up_male_down),
        "n_female_down_male_up": len(female_down_male_up),
        "large_volume_divergences": (female_up_male_down
                                     + female_down_male_up)[:TOP_ROWS],
        "note": (
            "Divergence is measured between two approval years, not as an "
            "individual woman's or man's migration history."
        ),
    }


def _share_size_growth(deep: list[dict]) -> dict:
    valid = [row for row in deep
             if row["latest_female_share_pct"] is not None
             and row["latest_total"] > 0]
    shares = [row["latest_female_share_pct"] for row in valid]
    totals = [row["latest_total"] for row in valid]
    logs = [math.log(row["latest_total"]) for row in valid]
    changes = [row["female_share_change_pp"] for row in valid
               if row["female_share_change_pp"] is not None]
    change_totals = [row["latest_total"] for row in valid
                     if row["female_share_change_pp"] is not None]
    growth_changes = [row["total_growth_pct"] for row in valid
                      if row["total_growth_pct"] is not None
                      and row["female_share_change_pp"] is not None]
    growth_totals = [row["latest_total"] for row in valid
                     if row["total_growth_pct"] is not None
                     and row["female_share_change_pp"] is not None]
    large = [row for row in valid if row["latest_total"] >= LARGE_VOLUME]
    large.sort(key=lambda row: row["latest_female_share_pct"], reverse=True)
    additions = sorted(valid, key=lambda row: row["female_change"],
                       reverse=True)
    return {
        "pearson_share_vs_total": _safe_corr(shares, totals),
        "spearman_share_vs_total": _safe_corr(shares, totals, "spearman"),
        "pearson_share_vs_log_total": _safe_corr(shares, logs),
        "pearson_share_change_vs_total": _safe_corr(changes, change_totals),
        "pearson_share_change_vs_total_growth": _safe_corr(
            growth_changes, growth_totals),
        "large_volume_threshold": LARGE_VOLUME,
        "high_female_share_large_destinations": [
            {
                "country": row["country"],
                "latest_total": row["latest_total"],
                "latest_female_share_pct": row["latest_female_share_pct"],
                "female_share_change_pp": row["female_share_change_pp"],
            }
            for row in large[:TOP_ROWS]
        ],
        "largest_female_additions": [
            {
                "country": row["country"],
                "latest_total": row["latest_total"],
                "female_change": row["female_change"],
                "male_change": row["male_change"],
                "female_growth_pct": row["female_growth_pct"],
                "latest_female_share_pct": row["latest_female_share_pct"],
            }
            for row in additions[:TOP_ROWS]
        ],
        "note": (
            "Correlations and rankings are descriptive. Destination size is an "
            "approval volume, not a labour-market size measure."
        ),
    }


def _threshold_summary(b: pd.DataFrame, n: pd.DataFrame,
                       threshold: int, latest_total: float) -> dict:
    deep = _country_deep(b, n, threshold)
    shares = [row["latest_female_share_pct"] for row in deep
              if row["latest_female_share_pct"] is not None]
    convergence = _convergence(b, n, threshold)
    included_total = sum(row["latest_total"] for row in deep)
    return {
        "threshold": threshold,
        "n_countries": len(deep),
        "latest_total_in_scope": _int(included_total),
        "latest_share_of_national_total_pct": _r(
            _share_pct(included_total, latest_total), 2),
        "unweighted_mean_latest_female_share_pct": _r(
            sum(shares) / len(shares), 2) if shares else None,
        "median_latest_female_share_pct": _r(
            pd.Series(shares).median(), 2) if shares else None,
        "weighted_latest_female_share_pct": _r(
            _share_pct(sum(row["latest_female"] for row in deep),
                       included_total), 2) if included_total else None,
        "convergence_slope_pp_per_initial_pp": convergence[
            "slope_pp_per_initial_pp"],
        "convergence_correlation": convergence["correlation"],
        "convergence_n": convergence["n_countries"],
    }


def _robustness(b: pd.DataFrame, n: pd.DataFrame, cg: pd.DataFrame,
                years: list[str]) -> dict:
    latest_total = float(n["total"].sum())
    variants = [
        _threshold_summary(b, n, threshold, latest_total)
        for threshold in THRESHOLD_VARIANTS
    ]
    default = next(row for row in variants if row["threshold"] == MIN_VOLUME)

    def window(start: str, end: str) -> dict:
        wb = _gender_frame(cg, start)
        wn = _gender_frame(cg, end)
        start_total = float(wb["total"].sum())
        end_total = float(wn["total"].sum())
        start_share = _share_pct(wb["female"].sum(), start_total)
        end_share = _share_pct(wn["female"].sum(), end_total)
        convergence = _convergence(wb, wn, MIN_VOLUME)
        female_growth = _growth_pct(wb["female"].sum(), wn["female"].sum())
        male_growth = _growth_pct(wb["male"].sum(), wn["male"].sum())
        return {
            "start_fiscal_year": start,
            "end_fiscal_year": end,
            "start_female_share_pct": _r(start_share, 4),
            "end_female_share_pct": _r(end_share, 4),
            "female_share_change_pp": _r(end_share - start_share, 4),
            "female_growth_pct": _r(female_growth, 2),
            "male_growth_pct": _r(male_growth, 2),
            "female_minus_male_growth_pp": _r(
                female_growth - male_growth, 2)
            if female_growth is not None and male_growth is not None else None,
            "convergence_slope_pp_per_initial_pp": convergence[
                "slope_pp_per_initial_pp"],
            "convergence_correlation": convergence["correlation"],
        }

    small = [row for row in _country_deep(b, n, 0)
             if row["latest_total"] < MIN_VOLUME]
    small_total = sum(row["latest_total"] for row in small)
    small_base = sum(row["base_total"] for row in small)
    all_change = (_share_pct(n["female"].sum(), n["total"].sum())
                  - _share_pct(b["female"].sum(), b["total"].sum()))
    return {
        "threshold_variants": variants,
        "default_threshold": MIN_VOLUME,
        "thresholds": list(THRESHOLD_VARIANTS),
        "windows": [
            window(BASE_FY, LATEST_FY),
            window("2080/81", LATEST_FY),
            window("2078/79", LATEST_FY),
        ],
        "small_destinations": {
            "threshold": MIN_VOLUME,
            "n_countries": len(small),
            "latest_total": _int(small_total),
            "latest_share_of_national_total_pct": _r(
                _share_pct(small_total, latest_total), 2),
            "base_total": _int(small_base),
            "total_change": _int(small_total - small_base),
        },
        "default_variant": default,
        "conclusion_stable_across_thresholds": all(
            row["convergence_slope_pp_per_initial_pp"] is not None
            and row["convergence_slope_pp_per_initial_pp"] < 0
            for row in variants),
        "note": (
            "Threshold variants change which destinations enter cross-country "
            "averages and convergence regressions. National weighted shares "
            "are invariant to the threshold because they use all approvals."
        ),
    }


def build() -> dict:
    panel = load_panel(safe=True)
    cg = country_gender_year(panel)
    cy = country_year(panel)
    years = _complete_years(cg)
    base = _gender_frame(cg, BASE_FY)
    latest = _gender_frame(cg, LATEST_FY)
    deep = _country_deep(base, latest, MIN_VOLUME)
    latest_total = float(latest["total"].sum())

    report = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": "migration_parser.research.datasets.country_gender_year",
            "safe_rows": int(len(panel)),
            "safe_documents": int(panel["doc_id"].nunique()),
            "complete_fiscal_years": years,
            "base_fy": BASE_FY,
            "latest_fy": LATEST_FY,
            "partial_fy": PARTIAL_FY,
            "partial_fy_excluded": True,
            "min_volume": MIN_VOLUME,
            "threshold_variants": list(THRESHOLD_VARIANTS),
            "large_volume": LARGE_VOLUME,
            "top_destinations": TOP_DESTINATIONS,
            "top_contributors": TOP_CONTRIBUTORS,
            "latest_total": _int(latest_total),
            "definitions": {
                "female_share_pct": (
                    "female approvals / (female + male approvals) * 100."
                ),
                "female_share_change_pp": (
                    "latest female share minus base female share, in percentage "
                    "points."
                ),
                "female_growth_pct": (
                    "female latest / female base - 1, as a percentage; None "
                    "when the base is zero or the country is absent."
                ),
                "female_minus_male_growth_pp": (
                    "female growth percentage minus male growth percentage, in "
                    "percentage points."
                ),
                "within_country_pp": (
                    "base destination weight times the change in that "
                    "destination's female share."
                ),
                "convergence_slope": (
                    "OLS slope of female-share change on initial female share, "
                    "descriptive only."
                ),
            },
            "caveats": [
                SEX_CAVEAT,
                "2083/84 is partial and is excluded from every trend, "
                "distribution, convergence, and comparison output.",
                "Approvals are permit events, not unique people; repeat and "
                "re-entry migration can appear as additional approvals.",
                "Base-to-latest comparisons span a change in the safe panel's "
                "reporting mix; levels can move for reporting reasons.",
                "Countries absent in the base year receive no base share or "
                "growth rate even if they appear later.",
                "Cross-country distributions and convergence use volume "
                "thresholds; small destinations are reported separately.",
                "No district analysis is included in this module.",
            ],
        },
        "annual": _annual(cg, cy, years),
        "country_deep": {
            "base_fiscal_year": BASE_FY,
            "latest_fiscal_year": LATEST_FY,
            "min_volume": MIN_VOLUME,
            "destinations": deep,
        },
        "country_trajectories": _country_trajectories(cg, years),
        "country_ranks": _country_ranks(deep),
        "distribution": {
            "threshold": MIN_VOLUME,
            "by_year": _distribution(cg, years, MIN_VOLUME),
            "volatility_persistence": _volatility_persistence(
                cg, years, MIN_VOLUME),
        },
        "convergence": {
            "base_fiscal_year": BASE_FY,
            "latest_fiscal_year": LATEST_FY,
            "default": _convergence(base, latest, MIN_VOLUME),
            "threshold_variants": [
                _convergence(base, latest, threshold)
                for threshold in THRESHOLD_VARIANTS
            ],
            "note": (
                "A negative slope means countries with lower initial female "
                "shares tended to add female share. This is descriptive and "
                "does not identify a mechanism."
            ),
        },
        "contribution_decomposition": _contribution_decomposition(base, latest),
        "growth_divergence": _growth_divergence(base, latest, MIN_VOLUME),
        "share_size_growth": _share_size_growth(deep),
        "robustness": _robustness(base, latest, cg, years),
    }
    return report
