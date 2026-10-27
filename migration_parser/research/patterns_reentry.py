"""Re-entry versus new-line patterns in the Nepali labour-migration panel.

This is a descriptive, single-basis module. It starts from the safe panel and
the shared ``country_channel_year`` builder, then contrasts the two individual
approval labels: ``individual_new`` and ``individual_reentry``. The partial
2083/84 fiscal year is excluded from every level, trend and decomposition.

``individual_reentry`` is a recorded approval-channel label. It is not a
unique-person return history and it cannot identify repeat migrants.
"""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from ..analysis import fiscal_year_panel
from .audit import _fy_key
from .datasets import country_channel_year, load_panel
from .patterns_gender_channel import (
    BASE_FY,
    CHANNELS,
    LATEST_FY,
    PARTIAL_FY,
    _gender_channel_year,
)

COMPARABLE_FY = "2081/82"
MIN_LATEST = 1000
MIN_BASE = 1000
TOP_DESTINATIONS = 12
GROWTH_MIN_NEW = 100
THRESHOLD_OPTIONS = (500, 1000, 2000, 5000)

NEW = "individual_new"
REENTRY = "individual_reentry"
OTHER_CHANNELS = ("g2g", "recruiting_agency")

CAVEAT = (
    "individual_reentry is a recorded approval-channel label, not a "
    "unique-person return history; it cannot identify repeat migrants."
)


def _r(value, digits: int = 2):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _pct(value, digits: int = 2):
    return _r(100.0 * float(value), digits) if value is not None else None


def _growth_pct(before, after):
    if before is None or after is None:
        return None
    try:
        before = float(before)
        after = float(after)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(before) or not math.isfinite(after) or before <= 0:
        return None
    return (after / before - 1.0) * 100.0


def _share(numerator, denominator):
    if denominator is None or numerator is None:
        return None
    try:
        numerator = float(numerator)
        denominator = float(denominator)
    except (TypeError, ValueError):
        return None
    if denominator <= 0 or not math.isfinite(denominator):
        return None
    return _r(100.0 * numerator / denominator)


def _corr(xs, ys) -> dict:
    pairs = []
    for x, y in zip(xs, ys):
        if x is None or y is None:
            continue
        try:
            xf = float(x)
            yf = float(y)
        except (TypeError, ValueError):
            continue
        if math.isfinite(xf) and math.isfinite(yf):
            pairs.append((xf, yf))
    if len(pairs) < 3:
        return {"n": len(pairs), "pearson": None, "spearman": None}
    left = pd.Series([p[0] for p in pairs])
    right = pd.Series([p[1] for p in pairs])
    return {
        "n": len(pairs),
        "pearson": _r(left.corr(right)),
        "spearman": _r(left.corr(right, method="spearman")),
    }


def _channel_year(cc: pd.DataFrame) -> pd.DataFrame:
    pivot = cc.pivot_table(index="fiscal_year", columns="channel_canonical",
                           values="count", aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(columns=list(CHANNELS), fill_value=0)
    pivot["total"] = pivot.sum(axis=1)
    return pivot


def _complete_years(cc: pd.DataFrame) -> list[str]:
    years = {str(fy) for fy in cc["fiscal_year"].unique()}
    years = [fy for fy in years
             if fy != PARTIAL_FY and _fy_key(fy) <= _fy_key(LATEST_FY)]
    return sorted(years, key=_fy_key)


def _reported_channels(cc: pd.DataFrame, fiscal_year: str) -> set[str]:
    block = cc[cc["fiscal_year"] == fiscal_year]
    return set(block["channel_canonical"].unique())


def _annual_series(cc: pd.DataFrame) -> list[dict]:
    pivot = _channel_year(cc)
    years = _complete_years(cc)
    rows = []
    previous = None
    for fy in years:
        if fy not in pivot.index:
            continue
        reported = _reported_channels(cc, fy)
        new_reported = NEW in reported
        reentry_reported = REENTRY in reported
        counts = {channel: int(pivot.loc[fy, channel]) for channel in CHANNELS}
        total = int(pivot.loc[fy, "total"])
        other = sum(counts[channel] for channel in OTHER_CHANNELS)
        new_count = counts[NEW]
        reentry_count = counts[REENTRY]
        individual_total = new_count + reentry_count
        row = {
            "fiscal_year": fy,
            "is_base": fy == BASE_FY,
            "is_latest": fy == LATEST_FY,
            "total": total,
            "channels": counts,
            "reported_channels": [c for c in CHANNELS if c in reported],
            "individual_new": new_count,
            "individual_reentry": reentry_count,
            "other_channels": other,
            "individual_total": individual_total,
            "new_reported": new_reported,
            "reentry_reported": reentry_reported,
            "new_share_pct": _share(new_count, total) if new_reported else None,
            "reentry_share_pct": _share(reentry_count, total),
            "new_share_of_individual_pct": (
                _share(new_count, individual_total) if new_reported else None),
            "reentry_share_of_individual_pct": (
                _share(reentry_count, individual_total) if new_reported else None),
            "new_to_reentry_ratio": (
                _r(new_count / reentry_count)
                if new_reported and reentry_count > 0 else None),
            "growth_pct": {
                "total": _growth_pct(previous["total"], total) if previous else None,
                "individual_new": (
                    _growth_pct(previous["individual_new"], new_count)
                    if previous and previous["new_reported"] and new_reported
                    else None),
                "individual_reentry": (
                    _growth_pct(previous["individual_reentry"], reentry_count)
                    if previous and previous["reentry_reported"]
                    and reentry_reported else None),
            },
            "same_channel_set_as_previous": bool(
                previous and set(previous["reported_channels"]) == reported),
            "notes": [],
        }
        if not new_reported:
            row["notes"].append(
                "individual_new is not separately reported in this fiscal year.")
        rows.append(row)
        previous = row
    return rows


def _components(pivot: pd.DataFrame, cc: pd.DataFrame,
                start: str, end: str) -> dict:
    start_total = float(pivot.loc[start, "total"]) if start in pivot.index else 0.0
    end_total = float(pivot.loc[end, "total"]) if end in pivot.index else 0.0
    delta_total = end_total - start_total
    start_reported = _reported_channels(cc, start)
    end_reported = _reported_channels(cc, end)
    channel_rows = []
    for channel in CHANNELS:
        base = float(pivot.loc[start, channel]) if start in pivot.index else 0.0
        latest = float(pivot.loc[end, channel]) if end in pivot.index else 0.0
        delta = latest - base
        channel_rows.append({
            "channel": channel,
            "base_count": int(base),
            "latest_count": int(latest),
            "change": int(delta),
            "growth_pct": _r(_growth_pct(base, latest)),
            "contribution_to_total_change_pct": _r(
                100.0 * delta / delta_total if delta_total else None),
            "base_reported": channel in start_reported,
            "latest_reported": channel in end_reported,
        })
    return {
        "start_fiscal_year": start,
        "end_fiscal_year": end,
        "start_total": int(start_total),
        "end_total": int(end_total),
        "total_change": int(delta_total),
        "total_growth_pct": _r(_growth_pct(start_total, end_total)),
        "channels": channel_rows,
        "coverage": {
            "start_reported_channels": [c for c in CHANNELS if c in start_reported],
            "end_reported_channels": [c for c in CHANNELS if c in end_reported],
            "same_channel_set": start_reported == end_reported,
            "individual_new_separately_reported_at_start": NEW in start_reported,
        },
    }


def _comparable_window(cc: pd.DataFrame) -> dict:
    pivot = _channel_year(cc)
    if COMPARABLE_FY not in pivot.index or LATEST_FY not in pivot.index:
        return {
            "available": False,
            "note": "Comparable window is unavailable in this panel.",
            "caveat": CAVEAT,
        }
    block = _components(pivot, cc, COMPARABLE_FY, LATEST_FY)
    block["available"] = True
    block["note"] = (
        "2081/82 is the first fiscal year in which all four canonical channels "
        "(including individual_new and g2g) are separately reported. Use this "
        "window for a like-for-like new-versus-reentry comparison; the 2079/80 "
        "base year reports only individual_reentry and recruiting_agency.")
    block["caveat"] = CAVEAT
    return block


def _country_channel_frame(cc: pd.DataFrame, fiscal_year: str) -> pd.DataFrame:
    block = cc[cc["fiscal_year"] == fiscal_year]
    frame = block.pivot_table(index="country", columns="channel_canonical",
                              values="count", aggfunc="sum", fill_value=0)
    return frame.reindex(columns=list(CHANNELS), fill_value=0)


def _country_gender_totals(gc: pd.DataFrame, fiscal_year: str) -> dict:
    block = gc[gc["fiscal_year"] == fiscal_year]
    totals: dict[str, dict] = {}
    if block.empty:
        return totals
    grouped = block.groupby(["country", "gender", "channel_canonical"])["count"].sum()
    for (country, gender, channel), value in grouped.items():
        entry = totals.setdefault(str(country), {})
        entry[(str(gender), str(channel))] = float(value)
        entry[(str(gender), "all")] = entry.get((str(gender), "all"), 0.0) + float(value)
    return totals


def _gender_value(totals: dict, country: str, gender: str, channel: str) -> int:
    entry = totals.get(str(country), {})
    return int(entry.get((gender, channel), 0))


def _country_base_latest(cc: pd.DataFrame, gc: pd.DataFrame) -> dict:
    base = _country_channel_frame(cc, BASE_FY)
    latest = _country_channel_frame(cc, LATEST_FY)
    base_gender = _country_gender_totals(gc, BASE_FY)
    latest_gender = _country_gender_totals(gc, LATEST_FY)
    rows = []
    for country in latest.index:
        total = float(latest.loc[country].sum())
        if total < MIN_LATEST:
            continue
        b = base.loc[country] if country in base.index else None
        b_total = float(b.sum()) if b is not None else 0.0
        b_new = float(b[NEW]) if b is not None else 0.0
        b_reentry = float(b[REENTRY]) if b is not None else 0.0
        b_other = float(b[list(OTHER_CHANNELS)].sum()) if b is not None else 0.0
        n_new = float(latest.loc[country, NEW])
        n_reentry = float(latest.loc[country, REENTRY])
        n_other = float(latest.loc[country, list(OTHER_CHANNELS)].sum())
        base_share = _share(b_reentry, b_total)
        latest_share = _share(n_reentry, total)
        rows.append({
            "country": str(country),
            "latest_total": int(total),
            "base_total": int(b_total),
            "base_above_min": bool(b_total >= MIN_BASE),
            "latest_individual_new": int(n_new),
            "base_individual_new": int(b_new),
            "latest_individual_reentry": int(n_reentry),
            "base_individual_reentry": int(b_reentry),
            "latest_other_channels": int(n_other),
            "base_other_channels": int(b_other),
            "new_share_latest_pct": _share(n_new, total),
            "new_share_base_pct": _share(b_new, b_total),
            "reentry_share_latest_pct": latest_share,
            "reentry_share_base_pct": base_share,
            "reentry_share_change_pp": _r(
                latest_share - base_share
                if latest_share is not None and base_share is not None else None),
            "individual_new_change": int(n_new - b_new),
            "individual_reentry_change": int(n_reentry - b_reentry),
            "total_change": int(total - b_total),
            "total_growth_pct": _r(_growth_pct(b_total, total)),
            "new_growth_pct": _r(_growth_pct(b_new, n_new)),
            "reentry_growth_pct": _r(_growth_pct(b_reentry, n_reentry)),
            "latest_female": _gender_value(latest_gender, country, "female", "all"),
            "latest_male": _gender_value(latest_gender, country, "male", "all"),
            "base_female": _gender_value(base_gender, country, "female", "all"),
            "base_male": _gender_value(base_gender, country, "male", "all"),
            "latest_female_new": _gender_value(
                latest_gender, country, "female", NEW),
            "latest_male_new": _gender_value(latest_gender, country, "male", NEW),
            "latest_female_reentry": _gender_value(
                latest_gender, country, "female", REENTRY),
            "latest_male_reentry": _gender_value(
                latest_gender, country, "male", REENTRY),
        })
    rows.sort(key=lambda row: row["latest_total"], reverse=True)
    return {
        "base_fiscal_year": BASE_FY,
        "latest_fiscal_year": LATEST_FY,
        "min_latest_count": MIN_LATEST,
        "min_base_count": MIN_BASE,
        "destinations": rows,
        "note": (
            "Female and male columns come from the derived country x sex x "
            "channel table. They describe approvals by recorded sex, not "
            "distinct people."),
        "caveat": CAVEAT,
    }


def _top_destinations(cc: pd.DataFrame) -> dict:
    years = _complete_years(cc)
    latest = _country_channel_frame(cc, LATEST_FY)
    latest_totals = latest.sum(axis=1).sort_values(ascending=False)
    top = [str(country) for country in latest_totals.head(TOP_DESTINATIONS).index]
    frames = {fy: _country_channel_frame(cc, fy) for fy in years}
    destinations = []
    for country in top:
        series = []
        for fy in years:
            frame = frames[fy]
            if country in frame.index:
                new = int(frame.loc[country, NEW])
                reentry = int(frame.loc[country, REENTRY])
                total = int(frame.loc[country].sum())
            else:
                new = reentry = total = 0
            reported = _reported_channels(cc, fy)
            series.append({
                "fiscal_year": fy,
                "individual_new": new,
                "individual_reentry": reentry,
                "total": total,
                "new_reported": NEW in reported,
                "new_share_pct": _share(new, total) if NEW in reported else None,
                "reentry_share_pct": _share(reentry, total),
            })
        destinations.append({
            "country": country,
            "latest_total": int(latest_totals.get(country, 0)),
            "series": series,
        })
    return {
        "top_n": TOP_DESTINATIONS,
        "years": years,
        "latest_fiscal_year": LATEST_FY,
        "destinations": destinations,
        "plotting": {
            "x": "years",
            "series": "destinations[].series[]",
            "new_field": "individual_new",
            "reentry_field": "individual_reentry",
            "share_field": "reentry_share_pct",
        },
    }


def _country_changes(cc: pd.DataFrame, start: str, end: str,
                     channel: str, limit: int = 10) -> dict:
    before = _country_channel_frame(cc, start)
    after = _country_channel_frame(cc, end)
    rows = []
    countries = set(before.index) | set(after.index)
    for country in countries:
        a = float(before.loc[country, channel]) if country in before.index else 0.0
        b = float(after.loc[country, channel]) if country in after.index else 0.0
        if a == 0 and b == 0:
            continue
        rows.append({
            "country": str(country),
            "start_count": int(a),
            "end_count": int(b),
            "change": int(b - a),
            "growth_pct": _r(_growth_pct(a, b)),
        })
    rows.sort(key=lambda row: (row["change"], row["country"]), reverse=True)
    positive = [row for row in rows if row["change"] > 0][:limit]
    negative = [row for row in rows if row["change"] < 0][-limit:][::-1]
    return {
        "channel": channel,
        "start_fiscal_year": start,
        "end_fiscal_year": end,
        "top_positive": positive,
        "top_negative": negative,
        "total_change": int(sum(row["change"] for row in rows)),
        "sums_correctly": bool(
            abs(sum(row["change"] for row in rows)
                - (float(after[channel].sum())
                   - float(before[channel].sum()))) < 1e-6),
    }


def _decomposition(cc: pd.DataFrame) -> dict:
    pivot = _channel_year(cc)
    base_to_latest = _components(pivot, cc, BASE_FY, LATEST_FY)
    comparable = _components(pivot, cc, COMPARABLE_FY, LATEST_FY)
    base_to_latest["sums_correctly"] = bool(
        abs(sum(row["change"] for row in base_to_latest["channels"])
            - base_to_latest["total_change"]) < 1e-6)
    comparable["sums_correctly"] = bool(
        abs(sum(row["change"] for row in comparable["channels"])
            - comparable["total_change"]) < 1e-6)

    def split(block):
        by_channel = {row["channel"]: row for row in block["channels"]}
        return {
            "individual_new_change": by_channel[NEW]["change"],
            "individual_reentry_change": by_channel[REENTRY]["change"],
            "other_channels_change": sum(
                by_channel[channel]["change"] for channel in OTHER_CHANNELS),
            "total_change": block["total_change"],
            "sums_correctly": bool(
                abs(by_channel[NEW]["change"]
                    + by_channel[REENTRY]["change"]
                    + sum(by_channel[channel]["change"]
                          for channel in OTHER_CHANNELS)
                    - block["total_change"]) < 1e-6),
        }

    contributors = {
        "new_growth_base_to_latest": _country_changes(
            cc, BASE_FY, LATEST_FY, NEW),
        "new_growth_comparable": _country_changes(
            cc, COMPARABLE_FY, LATEST_FY, NEW),
        "reentry_growth_base_to_latest": _country_changes(
            cc, BASE_FY, LATEST_FY, REENTRY),
        "reentry_growth_comparable": _country_changes(
            cc, COMPARABLE_FY, LATEST_FY, REENTRY),
    }
    contributors["new_growth_base_to_latest"]["note"] = (
        "individual_new is not separately reported in 2079/80, so every latest "
        "new approval is counted as growth in this window. Use the comparable "
        "2081/82 window for a true new-line change.")
    contributors["new_growth_comparable"]["note"] = (
        "Preferred new-line comparison: both endpoints separately report "
        "individual_new.")

    return {
        "base_fiscal_year": BASE_FY,
        "latest_fiscal_year": LATEST_FY,
        "comparable_fiscal_year": COMPARABLE_FY,
        "base_to_latest": base_to_latest,
        "comparable_window": comparable,
        "base_to_latest_split": split(base_to_latest),
        "comparable_window_split": split(comparable),
        "country_contributors": contributors,
        "caveat": CAVEAT,
    }


def _reentry_share_frame(cc: pd.DataFrame, fiscal_year: str) -> pd.DataFrame:
    frame = _country_channel_frame(cc, fiscal_year).copy()
    frame["total"] = frame.sum(axis=1)
    frame["reentry_share_pct"] = frame.apply(
        lambda row: _share(row[REENTRY], row["total"]), axis=1)
    return frame


def _distribution(values: list[float], weights: list[float]) -> dict:
    clean = [(float(v), float(w)) for v, w in zip(values, weights)
             if v is not None and w and math.isfinite(float(v))
             and math.isfinite(float(w))]
    if not clean:
        return {
            "n": 0, "mean_pct": None, "sd_pct": None, "min_pct": None,
            "p25_pct": None, "median_pct": None, "p75_pct": None,
            "max_pct": None, "weighted_mean_pct": None,
        }
    series = pd.Series([v for v, _ in clean])
    weights_series = pd.Series([w for _, w in clean])
    weighted = (series * weights_series).sum() / weights_series.sum()
    return {
        "n": len(clean),
        "mean_pct": _r(series.mean()),
        "sd_pct": _r(series.std(ddof=1)) if len(clean) > 1 else None,
        "min_pct": _r(series.min()),
        "p25_pct": _r(series.quantile(0.25)),
        "median_pct": _r(series.median()),
        "p75_pct": _r(series.quantile(0.75)),
        "max_pct": _r(series.max()),
        "weighted_mean_pct": _r(weighted),
    }


def _reentry_orientation(cc: pd.DataFrame) -> dict:
    latest = _reentry_share_frame(cc, LATEST_FY)
    latest = latest[latest["total"] >= MIN_LATEST].sort_values(
        "total", ascending=False)
    values = [row["reentry_share_pct"] for _, row in latest.iterrows()]
    weights = [row["total"] for _, row in latest.iterrows()]
    distribution = _distribution(values, weights)

    rows = []
    for country, row in latest.iterrows():
        rows.append({
            "country": str(country),
            "latest_total": int(row["total"]),
            "latest_individual_new": int(row[NEW]),
            "latest_individual_reentry": int(row[REENTRY]),
            "reentry_share_pct": _r(row["reentry_share_pct"]),
            "reentry_share_of_individual_pct": _share(
                row[REENTRY], row[NEW] + row[REENTRY]),
        })
    ranked = sorted(rows, key=lambda row: row["reentry_share_pct"],
                    reverse=True)

    years = [fy for fy in _complete_years(cc)
             if _fy_key(fy) >= _fy_key(BASE_FY)]
    stability = []
    frames = {fy: _reentry_share_frame(cc, fy) for fy in years}
    for previous, current in zip(years, years[1:]):
        left = frames[previous]
        right = frames[current]
        common = [country for country in left.index
                  if country in right.index
                  and left.loc[country, "total"] >= MIN_LATEST
                  and right.loc[country, "total"] >= MIN_LATEST]
        result = _corr(
            [left.loc[c, "reentry_share_pct"] for c in common],
            [right.loc[c, "reentry_share_pct"] for c in common])
        stability.append({
            "from": previous,
            "to": current,
            "n_common_above_min": result["n"],
            "pearson": result["pearson"],
            "spearman": result["spearman"],
        })
    if BASE_FY in frames and LATEST_FY in frames:
        left = frames[BASE_FY]
        right = frames[LATEST_FY]
        common = [country for country in left.index
                  if country in right.index
                  and left.loc[country, "total"] >= MIN_LATEST
                  and right.loc[country, "total"] >= MIN_LATEST]
        result = _corr(
            [left.loc[c, "reentry_share_pct"] for c in common],
            [right.loc[c, "reentry_share_pct"] for c in common])
        base_latest = {
            "from": BASE_FY,
            "to": LATEST_FY,
            "n_common_above_min": result["n"],
            "pearson": result["pearson"],
            "spearman": result["spearman"],
        }
    else:
        base_latest = {}

    return {
        "latest_fiscal_year": LATEST_FY,
        "min_latest_count": MIN_LATEST,
        "distribution": distribution,
        "highest_reentry_share": ranked[:8],
        "lowest_reentry_share": ranked[-8:][::-1],
        "destinations": rows,
        "stability": stability,
        "base_to_latest_rank": base_latest,
        "interpretation": (
            "Weighted shares use total approvals as weights; unweighted shares "
            "give every destination above the volume threshold equal weight. "
            "Reentry shares describe approval-channel mix, not repeat persons."),
        "caveat": CAVEAT,
    }


def _association(cc: pd.DataFrame) -> dict:
    base = _reentry_share_frame(cc, BASE_FY)
    comparable = _reentry_share_frame(cc, COMPARABLE_FY)
    latest = _reentry_share_frame(cc, LATEST_FY)

    def collect(start, end, share_frame, min_start, min_end, extra=None):
        xs, ys = [], []
        for country in latest.index:
            if latest.loc[country, "total"] < MIN_LATEST:
                continue
            if country not in start.index or country not in end.index:
                continue
            if share_frame.loc[country, "total"] < MIN_LATEST:
                continue
            if start.loc[country, "total"] < min_start:
                continue
            if end.loc[country, "total"] < min_end:
                continue
            x = share_frame.loc[country, "reentry_share_pct"]
            y = _growth_pct(start.loc[country, "total"],
                            end.loc[country, "total"])
            if extra is not None:
                y = extra(start, end, country)
            if x is None or y is None:
                continue
            xs.append(x)
            ys.append(y)
        return _corr(xs, ys)

    total_growth = collect(base, latest, latest, MIN_BASE, MIN_LATEST)

    def new_growth(start, end, country):
        return _growth_pct(start.loc[country, NEW], end.loc[country, NEW])

    def reentry_growth(start, end, country):
        return _growth_pct(start.loc[country, REENTRY], end.loc[country, REENTRY])

    def gate_new(start, end, country):
        return (start.loc[country, NEW] >= GROWTH_MIN_NEW
                and end.loc[country, NEW] >= GROWTH_MIN_NEW)

    xs_new, ys_new = [], []
    for country in latest.index:
        if latest.loc[country, "total"] < MIN_LATEST:
            continue
        if country not in comparable.index or country not in latest.index:
            continue
        if not gate_new(comparable, latest, country):
            continue
        xs_new.append(latest.loc[country, "reentry_share_pct"])
        ys_new.append(new_growth(comparable, latest, country))
    new_growth_corr = _corr(xs_new, ys_new)

    xs_new_comp, ys_new_comp = [], []
    for country in latest.index:
        if latest.loc[country, "total"] < MIN_LATEST:
            continue
        if country not in comparable.index or country not in latest.index:
            continue
        if not gate_new(comparable, latest, country):
            continue
        xs_new_comp.append(comparable.loc[country, "reentry_share_pct"])
        ys_new_comp.append(new_growth(comparable, latest, country))
    new_growth_comparable_share = _corr(xs_new_comp, ys_new_comp)

    xs_re, ys_re = [], []
    for country in latest.index:
        if latest.loc[country, "total"] < MIN_LATEST:
            continue
        if country not in comparable.index or country not in latest.index:
            continue
        if comparable.loc[country, REENTRY] < GROWTH_MIN_NEW:
            continue
        xs_re.append(comparable.loc[country, "reentry_share_pct"])
        ys_re.append(reentry_growth(comparable, latest, country))
    reentry_growth_corr = _corr(xs_re, ys_re)

    return {
        "base_fiscal_year": BASE_FY,
        "latest_fiscal_year": LATEST_FY,
        "comparable_fiscal_year": COMPARABLE_FY,
        "min_latest_count": MIN_LATEST,
        "new_growth_min_count": GROWTH_MIN_NEW,
        "total_growth_vs_latest_reentry_share": total_growth,
        "new_growth_vs_latest_reentry_share": new_growth_corr,
        "new_growth_vs_comparable_reentry_share": new_growth_comparable_share,
        "reentry_growth_vs_comparable_reentry_share": reentry_growth_corr,
        "label": "descriptive association, not causal",
        "interpretation": (
            "Correlations are cross-sectional associations across destinations "
            "above the volume threshold. A negative correlation means "
            "destinations with a higher re-entry share tended to grow more "
            "slowly, not that re-entry caused slower growth."),
        "caveat": CAVEAT,
    }


def _robustness(cc: pd.DataFrame) -> dict:
    pivot = _channel_year(cc)
    base = _reentry_share_frame(cc, BASE_FY)
    comparable = _reentry_share_frame(cc, COMPARABLE_FY)
    latest = _reentry_share_frame(cc, LATEST_FY)

    thresholds = []
    for threshold in THRESHOLD_OPTIONS:
        frame = latest[latest["total"] >= threshold]
        values = [row["reentry_share_pct"] for _, row in frame.iterrows()]
        weights = [row["total"] for _, row in frame.iterrows()]
        distribution = _distribution(values, weights)
        xs, ys = [], []
        for country in frame.index:
            if country not in base.index:
                continue
            if base.loc[country, "total"] < threshold:
                continue
            xs.append(frame.loc[country, "reentry_share_pct"])
            ys.append(_growth_pct(base.loc[country, "total"],
                                  latest.loc[country, "total"]))
        corr = _corr(xs, ys)
        thresholds.append({
            "threshold": threshold,
            "n_countries": int(len(frame)),
            "weighted_reentry_share_pct": distribution["weighted_mean_pct"],
            "unweighted_reentry_share_pct": distribution["mean_pct"],
            "total_growth_correlation": corr,
        })

    def individual_share(frame):
        denominator = frame[NEW] + frame[REENTRY]
        # Pandas Series to keep missing years out of the denominator calculation.
        return (frame[REENTRY] / denominator.replace(0, pd.NA) * 100.0)

    latest_individual = individual_share(latest)
    base_individual = individual_share(base)
    latest_major = latest[latest["total"] >= MIN_LATEST]
    values = [latest_individual.get(country) for country in latest_major.index]
    weights = [latest_major.loc[country, "total"] for country in latest_major.index]
    individual_distribution = _distribution(values, weights)

    xs, ys = [], []
    for country in latest.index:
        if latest.loc[country, "total"] < MIN_LATEST:
            continue
        if country not in base.index or base.loc[country, "total"] < MIN_BASE:
            continue
        x = latest_individual.get(country)
        y = _growth_pct(base.loc[country, "total"], latest.loc[country, "total"])
        xs.append(x)
        ys.append(y)
    individual_corr = _corr(xs, ys)
    all_channel_corr = _association(cc)["total_growth_vs_latest_reentry_share"]
    sign_all = None if all_channel_corr["pearson"] is None else (
        1 if all_channel_corr["pearson"] > 0 else -1)
    sign_individual = None if individual_corr["pearson"] is None else (
        1 if individual_corr["pearson"] > 0 else -1)

    return {
        "base_vs_comparable": {
            "latest_reentry_share_pct": _share(
                float(pivot.loc[LATEST_FY, REENTRY]),
                float(pivot.loc[LATEST_FY, "total"])),
            "base_reentry_share_pct": _share(
                float(pivot.loc[BASE_FY, REENTRY]),
                float(pivot.loc[BASE_FY, "total"])),
            "comparable_reentry_share_pct": _share(
                float(pivot.loc[COMPARABLE_FY, REENTRY]),
                float(pivot.loc[COMPARABLE_FY, "total"])),
            "base_to_latest_reentry_growth_pct": _r(_growth_pct(
                float(pivot.loc[BASE_FY, REENTRY]),
                float(pivot.loc[LATEST_FY, REENTRY]))),
            "comparable_to_latest_reentry_growth_pct": _r(_growth_pct(
                float(pivot.loc[COMPARABLE_FY, REENTRY]),
                float(pivot.loc[LATEST_FY, REENTRY]))),
            "base_to_latest_new_growth_pct": _r(_growth_pct(
                float(pivot.loc[BASE_FY, NEW]),
                float(pivot.loc[LATEST_FY, NEW]))),
            "comparable_to_latest_new_growth_pct": _r(_growth_pct(
                float(pivot.loc[COMPARABLE_FY, NEW]),
                float(pivot.loc[LATEST_FY, NEW]))),
            "note": (
                "The 2079/80 base does not separately report individual_new, "
                "so new-line growth in the base window is not interpretable. "
                "The comparable 2081/82 window is the like-for-like check."),
        },
        "alternative_thresholds": {
            "thresholds": thresholds,
            "note": (
                "Changing the latest-volume threshold mostly changes the "
                "unweighted destination average; the volume-weighted share is "
                "more stable."),
        },
        "exclude_non_individual_channels": {
            "definition": (
                "Denominator restricted to individual_new + individual_reentry, "
                "removing g2g and recruiting_agency."),
            "base_reentry_share_of_individual_pct": _share(
                float(pivot.loc[BASE_FY, REENTRY]),
                float(pivot.loc[BASE_FY, NEW] + pivot.loc[BASE_FY, REENTRY])),
            "comparable_reentry_share_of_individual_pct": _share(
                float(pivot.loc[COMPARABLE_FY, REENTRY]),
                float(pivot.loc[COMPARABLE_FY, NEW]
                      + pivot.loc[COMPARABLE_FY, REENTRY])),
            "latest_reentry_share_of_individual_pct": _share(
                float(pivot.loc[LATEST_FY, REENTRY]),
                float(pivot.loc[LATEST_FY, NEW] + pivot.loc[LATEST_FY, REENTRY])),
            "destination_distribution_latest": individual_distribution,
            "total_growth_correlation_latest": individual_corr,
            "all_channel_correlation_latest": all_channel_corr,
            "same_correlation_sign": (
                None if sign_all is None or sign_individual is None
                else sign_all == sign_individual),
            "note": (
                "If the sign or magnitude changes when g2g and recruiting_agency "
                "are removed, the headline re-entry orientation is partly a "
                "composition effect of the channel denominator."),
        },
        "caveat": CAVEAT,
    }


def build() -> dict:
    panel = load_panel(safe=True)
    cc = country_channel_year(panel)
    gc = _gender_channel_year(panel)
    years = _complete_years(cc)

    report = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "topic": "individual_new versus individual_reentry",
            "safe_rows": int(len(panel)),
            "safe_documents": int(panel["doc_id"].nunique()),
            "fiscal_years": years,
            "base_fy": BASE_FY,
            "latest_fy": LATEST_FY,
            "partial_fy": PARTIAL_FY,
            "partial_fy_excluded": True,
            "comparable_fy": COMPARABLE_FY,
            "min_latest_count": MIN_LATEST,
            "min_base_count": MIN_BASE,
            "top_destinations": TOP_DESTINATIONS,
            "growth_min_new_count": GROWTH_MIN_NEW,
            "threshold_options": list(THRESHOLD_OPTIONS),
            "channels": list(CHANNELS),
            "definitions": {
                "individual_new": (
                    "Approval recorded in the individual (non-agency, non-g2g) "
                    "new-entry channel."),
                "individual_reentry": (
                    "Approval recorded in the individual re-entry channel; a "
                    "label on an approval, not evidence of a specific prior "
                    "migrant."),
                "reentry_share_pct": (
                    "individual_reentry approvals / all canonical-channel "
                    "approvals * 100, unless a restricted denominator is stated."),
                "reentry_share_of_individual_pct": (
                    "individual_reentry / (individual_new + individual_reentry) "
                    "* 100."),
                "new_to_reentry_ratio": (
                    "individual_new approvals / individual_reentry approvals."),
                "comparable_window": (
                    "2081/82 to 2082/83, the first adjacent pair of years in "
                    "which all four canonical channels are separately reported."),
            },
            "caveat": CAVEAT,
            "caveats": [
                CAVEAT,
                "2083/84 is partial and is excluded from every level, trend and "
                "comparison.",
                "2079/80 reports only individual_reentry and recruiting_agency; "
                "individual_new and g2g are absent. Base-year shares of all "
                "approvals and base-to-latest channel changes therefore reflect "
                "reporting coverage as well as migration.",
                "Use the 2081/82 -> 2082/83 comparable window for like-for-like "
                "new-versus-reentry growth.",
                "All counts are approvals, not unique people, arrivals or "
                "departures. Destination and sex are recorded at approval.",
                "Country-level results are descriptive associations and are not "
                "causal. Small destinations can produce extreme shares.",
            ],
        },
        "annual": _annual_series(cc),
        "comparable_window": _comparable_window(cc),
        "country_base_latest": _country_base_latest(cc, gc),
        "top_destinations": _top_destinations(cc),
        "decomposition": _decomposition(cc),
        "reentry_orientation": _reentry_orientation(cc),
        "association": _association(cc),
        "robustness": _robustness(cc),
    }
    return report
