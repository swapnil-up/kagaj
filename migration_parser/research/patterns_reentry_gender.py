"""Re-entry by gender: the intersection of approval channel and sex.

This module is standalone. It reads the safe, single-basis panel, derives
destination x sex x channel totals through
``patterns_gender_channel._gender_channel_year``, and asks how the female share
differs between the ``individual_new`` and ``individual_reentry`` lines and how
that difference varies by destination.

``individual_new`` is only separately reported from 2081/82, so the primary
comparison window is 2081/82 -> 2082/83. The 2079/80 base is still reported for
the channels that were separately labelled then (re-entry and agency); the
partial 2083/84 year is excluded from every level, trend and comparison.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .audit import _fy_key
from .datasets import load_panel
from .patterns_gender_channel import CHANNELS, _gender_channel_year

BASE_FY = "2079/80"
LATEST_FY = "2082/83"
PARTIAL_FY = "2083/84"
COMPARABLE_BASE_FY = "2081/82"

FOCUS_CHANNELS = ("individual_new", "individual_reentry")
BASE_TO_LATEST_CHANNELS = ("individual_reentry", "recruiting_agency")

MIN_VOLUME = 1000
ALT_THRESHOLDS = (500, 1000, 2000, 5000)
TOP_DESTINATIONS = 12
ORIENTATION_GAP_PP = 5.0
REENTRY_HEAVY_PCT = 50.0


def _r(value, digits: int = 2):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return round(value, digits)


def _pct(value, digits: int = 2):
    return _r(100.0 * float(value), digits)


def _share(female: float, total: float):
    if not total:
        return None
    return 100.0 * float(female) / float(total)


def _growth_pct(before: float, after: float):
    if before <= 0:
        return None
    return (after / before - 1.0) * 100.0


def _complete_years(gc: pd.DataFrame) -> list[str]:
    years = {str(fy) for fy in gc["fiscal_year"]}
    return [fy for fy in sorted(years, key=_fy_key) if fy != PARTIAL_FY]


def _frame(gc: pd.DataFrame, fiscal_year: str) -> pd.DataFrame:
    block = gc[gc["fiscal_year"] == fiscal_year]
    frame = block.pivot_table(index=["country", "channel_canonical"],
                              columns="gender", values="count",
                              aggfunc="sum", fill_value=0)
    for column in ("male", "female"):
        if column not in frame:
            frame[column] = 0
    frame["total"] = frame["female"] + frame["male"]
    return frame


def _lookup(frame: pd.DataFrame, country, channel):
    key = (country, channel)
    if key in frame.index:
        row = frame.loc[key]
        return float(row["female"]), float(row["male"]), float(row["total"])
    return 0.0, 0.0, 0.0


def _reported(gc: pd.DataFrame, fiscal_year: str) -> set[str]:
    block = gc[gc["fiscal_year"] == fiscal_year]
    return set(block["channel_canonical"].dropna().unique())


def _annual_table(gc: pd.DataFrame) -> list[dict]:
    by_channel = (gc.groupby(["fiscal_year", "channel_canonical", "gender"])
                  ["count"].sum().unstack("gender", fill_value=0))
    for column in ("male", "female"):
        if column not in by_channel:
            by_channel[column] = 0
    rows = []
    for fy in _complete_years(gc):
        channels = {}
        reported = _reported(gc, fy)
        for channel in CHANNELS:
            key = (fy, channel)
            if key in by_channel.index:
                female = float(by_channel.loc[key, "female"])
                male = float(by_channel.loc[key, "male"])
            else:
                female = male = 0.0
            total = female + male
            channels[channel] = {
                "reported": channel in reported,
                "female": int(female),
                "male": int(male),
                "total": int(total),
                "female_share_pct": _r(_share(female, total)),
            }
        new = channels["individual_new"]
        reentry = channels["individual_reentry"]
        if new["female_share_pct"] is not None and reentry["female_share_pct"] is not None:
            gap = new["female_share_pct"] - reentry["female_share_pct"]
        else:
            gap = None
        used = [c for c in CHANNELS if channels[c]["reported"]]
        total_female = sum(channels[c]["female"] for c in used)
        total_male = sum(channels[c]["male"] for c in used)
        total = total_female + total_male
        rows.append({
            "fiscal_year": fy,
            "channels_reported": used,
            "female": int(total_female),
            "male": int(total_male),
            "total": int(total),
            "female_share_pct": _r(_share(total_female, total)),
            "new_to_reentry_female_gap_pp": _r(gap),
            "channels": channels,
        })
    return rows


def _country_table(gc: pd.DataFrame, latest_aggregate_share: float,
                   min_volume: int = MIN_VOLUME) -> list[dict]:
    latest = _frame(gc, LATEST_FY)
    base = _frame(gc, COMPARABLE_BASE_FY)
    old_base = _frame(gc, BASE_FY)

    totals = {}
    for (country, channel), row in latest.iterrows():
        totals[country] = totals.get(country, 0.0) + float(row["total"])

    rows = []
    for country in totals:
        if totals[country] < min_volume:
            continue
        nf, nm, nt = _lookup(latest, country, "individual_new")
        rf, rm, rt = _lookup(latest, country, "individual_reentry")
        gf, gm, gt = _lookup(latest, country, "g2g")
        af, am, at = _lookup(latest, country, "recruiting_agency")
        new_share = _share(nf, nt)
        reentry_share = _share(rf, rt)
        gap = (new_share - reentry_share
               if new_share is not None and reentry_share is not None else None)
        focus_total = nt + rt
        reentry_share_of_focus = _share(rt, focus_total)
        overall_female = nf + rf + gf + af
        overall_male = nm + rm + gm + am
        overall_share = _share(overall_female, overall_female + overall_male)

        bnf, bnm, bnt = _lookup(base, country, "individual_new")
        brf, brm, brt = _lookup(base, country, "individual_reentry")
        base_new_share = _share(bnf, bnt)
        base_reentry_share = _share(brf, brt)
        base_gap = (base_new_share - base_reentry_share
                    if base_new_share is not None
                    and base_reentry_share is not None else None)

        orf, orm, ort = _lookup(old_base, country, "individual_reentry")
        old_base_reentry_share = _share(orf, ort)

        if gap is None:
            orientation = "insufficient"
        elif gap >= ORIENTATION_GAP_PP:
            orientation = "new_more_female"
        elif gap <= -ORIENTATION_GAP_PP:
            orientation = "reentry_more_female"
        else:
            orientation = "similar"

        female_heavy = (overall_share is not None
                        and overall_share >= latest_aggregate_share)
        reentry_heavy = (reentry_share_of_focus is not None
                         and reentry_share_of_focus >= REENTRY_HEAVY_PCT)

        rows.append({
            "country": str(country),
            "latest_total": int(totals[country]),
            "latest_female": int(overall_female),
            "latest_male": int(overall_male),
            "latest_female_share_pct": _r(overall_share),
            "new_total": int(nt),
            "new_female": int(nf),
            "new_male": int(nm),
            "new_female_share_pct": _r(new_share),
            "reentry_total": int(rt),
            "reentry_female": int(rf),
            "reentry_male": int(rm),
            "reentry_female_share_pct": _r(reentry_share),
            "new_to_reentry_female_gap_pp": _r(gap),
            "reentry_share_of_focus_pct": _r(reentry_share_of_focus),
            "base_fy": COMPARABLE_BASE_FY,
            "base_new_female_share_pct": _r(base_new_share),
            "base_reentry_female_share_pct": _r(base_reentry_share),
            "base_new_to_reentry_female_gap_pp": _r(base_gap),
            "new_female_share_change_pp": _r(
                new_share - base_new_share
                if new_share is not None and base_new_share is not None
                else None),
            "reentry_female_share_change_pp": _r(
                reentry_share - base_reentry_share
                if reentry_share is not None
                and base_reentry_share is not None else None),
            "gap_change_pp": _r(gap - base_gap
                                if gap is not None and base_gap is not None
                                else None),
            "old_base_fy": BASE_FY,
            "old_base_reentry_female_share_pct": _r(old_base_reentry_share),
            "reentry_female_share_change_from_old_base_pp": _r(
                reentry_share - old_base_reentry_share
                if reentry_share is not None
                and old_base_reentry_share is not None else None),
            "focus_total": int(focus_total),
            "reentry_heavy": bool(reentry_heavy),
            "female_heavy": bool(female_heavy),
            "reentry_heavy_and_female_heavy": bool(reentry_heavy
                                                   and female_heavy),
            "orientation": orientation,
        })
    rows.sort(key=lambda row: row["latest_total"], reverse=True)
    return rows


def _decompose(gc: pd.DataFrame, start: str, end: str,
               channels: tuple[str, ...], label: str) -> dict:
    start_frame = _frame(gc, start)
    end_frame = _frame(gc, end)
    start_reported = _reported(gc, start)
    end_reported = _reported(gc, end)

    rows = []
    for channel in channels:
        s_block = start_frame.xs(channel, level="channel_canonical") \
            if channel in start_frame.index.get_level_values("channel_canonical") \
            else None
        e_block = end_frame.xs(channel, level="channel_canonical") \
            if channel in end_frame.index.get_level_values("channel_canonical") \
            else None
        f0 = float(s_block["female"].sum()) if s_block is not None else 0.0
        m0 = float(s_block["male"].sum()) if s_block is not None else 0.0
        f1 = float(e_block["female"].sum()) if e_block is not None else 0.0
        m1 = float(e_block["male"].sum()) if e_block is not None else 0.0
        t0 = f0 + m0
        t1 = f1 + m1
        s0 = _share(f0, t0)
        s1 = _share(f1, t1)
        rows.append({
            "channel": channel,
            "start_reported": channel in start_reported,
            "end_reported": channel in end_reported,
            "start_female": int(f0),
            "start_male": int(m0),
            "start_total": int(t0),
            "start_female_share_pct": _r(s0),
            "end_female": int(f1),
            "end_male": int(m1),
            "end_total": int(t1),
            "end_female_share_pct": _r(s1),
            "female_share_change_pp": _r(s1 - s0
                                         if s0 is not None and s1 is not None
                                         else None),
            "_f0": f0, "_m0": m0, "_f1": f1, "_m1": m1,
        })

    total0 = sum(row["_f0"] + row["_m0"] for row in rows)
    total1 = sum(row["_f1"] + row["_m1"] for row in rows)
    female0 = sum(row["_f0"] for row in rows)
    female1 = sum(row["_f1"] for row in rows)
    aggregate0 = _share(female0, total0)
    aggregate1 = _share(female1, total1)

    within = composition = interaction = 0.0
    for row in rows:
        t0 = row["_f0"] + row["_m0"]
        t1 = row["_f1"] + row["_m1"]
        w0 = t0 / total0 if total0 else 0.0
        w1 = t1 / total1 if total1 else 0.0
        s0 = row["_f0"] / t0 if t0 else 0.0
        s1 = row["_f1"] / t1 if t1 else 0.0
        row["start_weight_pct"] = _r(100.0 * w0)
        row["end_weight_pct"] = _r(100.0 * w1)
        row["_within"] = w0 * (s1 - s0)
        row["_composition"] = s0 * (w1 - w0)
        row["_interaction"] = (w1 - w0) * (s1 - s0)
        within += row["_within"]
        composition += row["_composition"]
        interaction += row["_interaction"]

    for row in rows:
        row["within_pp"] = _r(100.0 * row["_within"], 6)
        row["composition_pp"] = _r(100.0 * row["_composition"], 6)
        row["interaction_pp"] = _r(100.0 * row["_interaction"], 6)
        row["total_contribution_pp"] = _r(
            100.0 * (row["_within"] + row["_composition"]
                     + row["_interaction"]), 6)
        for key in ("_within", "_composition", "_interaction",
                    "_f0", "_m0", "_f1", "_m1"):
            row.pop(key)

    within *= 100.0
    composition *= 100.0
    interaction *= 100.0

    change = (aggregate1 - aggregate0
              if aggregate0 is not None and aggregate1 is not None else None)
    change_out = _r(change, 6)

    def contributors(key: str, n: int = 5):
        ranked = sorted(rows, key=lambda row: abs(row[key] or 0.0),
                        reverse=True)[:n]
        return [{"channel": row["channel"], "contribution_pp": row[key]}
                for row in ranked if abs(row[key] or 0.0) > 1e-9]

    return {
        "label": label,
        "start_fiscal_year": start,
        "end_fiscal_year": end,
        "channels": [row["channel"] for row in rows],
        "start_channels_reported": sorted(start_reported),
        "end_channels_reported": sorted(end_reported),
        "start_total": int(total0),
        "end_total": int(total1),
        "start_female": int(female0),
        "end_female": int(female1),
        "start_female_share_pct": _r(aggregate0, 6),
        "end_female_share_pct": _r(aggregate1, 6),
        "aggregate_change_pp": change_out,
        "within_channel_pp": _r(within, 6),
        "channel_composition_pp": _r(composition, 6),
        "interaction_residual_pp": _r(interaction, 6),
        "components_sum_pp": _r(within + composition + interaction, 6),
        "residual_vs_aggregate_pp": _r(
            change_out - _r(within + composition + interaction, 6)
            if change_out is not None else None, 6),
        "within_contributors": contributors("within_pp"),
        "composition_contributors": contributors("composition_pp"),
        "largest_total_contributors": contributors("total_contribution_pp"),
        "channel_contributions": rows,
        "formula": (
            "S = sum_c w_c * s_c; delta S = sum_c w_c0*delta s_c "
            "(within) + sum_c s_c0*delta w_c (composition) + "
            "sum_c delta w_c*delta s_c (interaction)."
        ),
    }


def _growth_decomposition(gc: pd.DataFrame, start: str, end: str,
                          channels: tuple[str, ...], label: str) -> dict:
    start_frame = _frame(gc, start)
    end_frame = _frame(gc, end)
    start_reported = _reported(gc, start)
    end_reported = _reported(gc, end)

    rows = []
    total_female0 = total_female1 = 0.0
    total_male0 = total_male1 = 0.0
    for channel in channels:
        def sums(frame):
            if channel not in frame.index.get_level_values("channel_canonical"):
                return 0.0, 0.0
            block = frame.xs(channel, level="channel_canonical")
            return float(block["female"].sum()), float(block["male"].sum())

        f0, m0 = sums(start_frame)
        f1, m1 = sums(end_frame)
        total_female0 += f0
        total_female1 += f1
        total_male0 += m0
        total_male1 += m1
        rows.append({
            "channel": channel,
            "start_reported": channel in start_reported,
            "end_reported": channel in end_reported,
            "female_start": int(f0),
            "female_end": int(f1),
            "female_change": int(f1 - f0),
            "male_start": int(m0),
            "male_end": int(m1),
            "male_change": int(m1 - m0),
            "female_growth_pct": _r(_growth_pct(f0, f1)),
            "male_growth_pct": _r(_growth_pct(m0, m1)),
            "female_minus_male_growth_pp": _r(
                _growth_pct(f0, f1) - _growth_pct(m0, m1)
                if _growth_pct(f0, f1) is not None
                and _growth_pct(m0, m1) is not None else None),
            "_female_change": f1 - f0,
            "_male_change": m1 - m0,
        })

    female_change = total_female1 - total_female0
    male_change = total_male1 - total_male0
    positive_female = sum(max(0.0, row["_female_change"]) for row in rows)
    for row in rows:
        row["female_change_contribution_pct"] = _r(
            100.0 * row["_female_change"] / female_change
            if female_change else None)
        row["positive_female_change_contribution_pct"] = _r(
            100.0 * max(0.0, row["_female_change"]) / positive_female
            if positive_female else None)
        row["male_change_contribution_pct"] = _r(
            100.0 * row["_male_change"] / male_change if male_change else None)
        row.pop("_female_change")
        row.pop("_male_change")

    by_channel = {row["channel"]: row for row in rows}
    new_row = by_channel.get("individual_new")
    reentry_row = by_channel.get("individual_reentry")
    return {
        "label": label,
        "start_fiscal_year": start,
        "end_fiscal_year": end,
        "channels": [row["channel"] for row in rows],
        "start_channels_reported": sorted(start_reported),
        "end_channels_reported": sorted(end_reported),
        "aggregate": {
            "female_start": int(total_female0),
            "female_end": int(total_female1),
            "female_change": int(female_change),
            "gross_positive_female_change": int(positive_female),
            "male_start": int(total_male0),
            "male_end": int(total_male1),
            "male_change": int(male_change),
            "female_growth_pct": _r(_growth_pct(total_female0, total_female1)),
            "male_growth_pct": _r(_growth_pct(total_male0, total_male1)),
            "female_minus_male_growth_pp": _r(
                _growth_pct(total_female0, total_female1)
                - _growth_pct(total_male0, total_male1)
                if _growth_pct(total_female0, total_female1) is not None
                and _growth_pct(total_male0, total_male1) is not None
                else None),
        },
        "new_female_change": new_row["female_change"] if new_row else None,
        "reentry_female_change": reentry_row["female_change"] if reentry_row else None,
        "new_female_contribution_pct": (
            new_row["female_change_contribution_pct"] if new_row else None),
        "reentry_female_contribution_pct": (
            reentry_row["female_change_contribution_pct"] if reentry_row else None),
        "new_positive_female_contribution_pct": (
            new_row["positive_female_change_contribution_pct"]
            if new_row else None),
        "reentry_positive_female_contribution_pct": (
            reentry_row["positive_female_change_contribution_pct"]
            if reentry_row else None),
        "channels_detail": rows,
        "caveat": (
            "Contributions are shares of the change in female approvals over "
            "the stated window, not shares of all approvals."
        ),
    }


def _trajectories(gc: pd.DataFrame, country_rows: list[dict]) -> list[dict]:
    years = _complete_years(gc)
    frames = {fy: _frame(gc, fy) for fy in years}
    reported = {fy: _reported(gc, fy) for fy in years}
    out = []
    for country_row in country_rows[:TOP_DESTINATIONS]:
        country = country_row["country"]
        points = []
        for fy in years:
            frame = frames[fy]
            new_f = _lookup(frame, country, "individual_new")[0]
            new_t = _lookup(frame, country, "individual_new")[2]
            re_f = _lookup(frame, country, "individual_reentry")[0]
            re_t = _lookup(frame, country, "individual_reentry")[2]
            new_share = _share(new_f, new_t)
            re_share = _share(re_f, re_t)
            gap = (new_share - re_share
                   if new_share is not None and re_share is not None else None)
            points.append({
                "fiscal_year": fy,
                "new_reported": "individual_new" in reported[fy],
                "reentry_reported": "individual_reentry" in reported[fy],
                "new_total": int(new_t),
                "new_female_share_pct": _r(new_share),
                "reentry_total": int(re_t),
                "reentry_female_share_pct": _r(re_share),
                "new_to_reentry_female_gap_pp": _r(gap),
            })
        out.append({
            "country": country,
            "latest_total": country_row["latest_total"],
            "points": points,
        })
    return out


def _gap_distribution(country_rows: list[dict]) -> dict:
    values = [row["new_to_reentry_female_gap_pp"] for row in country_rows
              if row["new_to_reentry_female_gap_pp"] is not None]
    if not values:
        return {"n_countries": 0, "values": []}
    series = pd.Series(values, dtype="float64")
    bins = [-100, -20, -10, -5, 0, 5, 10, 20, 100]
    labels = ["<=-20", "-20..-10", "-10..-5", "-5..0",
              "0..5", "5..10", "10..20", ">=20"]
    counts = {label: 0 for label in labels}
    for value in values:
        for index in range(len(bins) - 1):
            if bins[index] <= value < bins[index + 1]:
                counts[labels[index]] += 1
                break
        else:
            counts[labels[-1] if value >= bins[-1] else labels[0]] += 1
    return {
        "n_countries": len(values),
        "mean_pp": _r(series.mean()),
        "median_pp": _r(series.median()),
        "sd_pp": _r(series.std(ddof=0)),
        "min_pp": _r(series.min()),
        "p10_pp": _r(series.quantile(0.10)),
        "p25_pp": _r(series.quantile(0.25)),
        "p75_pp": _r(series.quantile(0.75)),
        "p90_pp": _r(series.quantile(0.90)),
        "max_pp": _r(series.max()),
        "new_more_female_count": int(sum(1 for value in values if value > 0)),
        "reentry_more_female_count": int(sum(1 for value in values if value < 0)),
        "within_5pp_count": int(sum(1 for value in values if abs(value) <= 5)),
        "histogram": counts,
    }


def _rank_stability(gc: pd.DataFrame, min_volume: int = MIN_VOLUME) -> list[dict]:
    years = [fy for fy in _complete_years(gc)
             if "individual_new" in _reported(gc, fy)
             and "individual_reentry" in _reported(gc, fy)]
    frames = {fy: _frame(gc, fy) for fy in years}
    out = []
    for previous, current in zip(years, years[1:]):
        gaps_pre = {}
        gaps_post = {}
        volumes_pre = {}
        volumes_post = {}
        for country in set(frames[previous].index.get_level_values("country")):
            for store, frame, gap_store in (
                (volumes_pre, frames[previous], gaps_pre),
                (volumes_post, frames[current], gaps_post),
            ):
                nf, nm, nt = _lookup(frame, country, "individual_new")
                rf, rm, rt = _lookup(frame, country, "individual_reentry")
                volume = nt + rt
                store[country] = volume
                new_share = _share(nf, nt)
                re_share = _share(rf, rt)
                if (new_share is not None and re_share is not None
                        and volume >= min_volume):
                    gap_store[country] = new_share - re_share
        common = sorted(set(gaps_pre) & set(gaps_post))
        if len(common) >= 3:
            pre_series = pd.Series([gaps_pre[c] for c in common])
            post_series = pd.Series([gaps_post[c] for c in common])
            spearman = _r(pre_series.corr(post_series, method="spearman"), 3)
        else:
            spearman = None
        pre_sorted = sorted(gaps_pre, key=gaps_pre.get, reverse=True)
        post_sorted = sorted(gaps_post, key=gaps_post.get, reverse=True)
        out.append({
            "from": previous,
            "to": current,
            "min_volume": min_volume,
            "n_common_countries": len(common),
            "spearman_gap": spearman,
            "top5_overlap": len(set(pre_sorted[:5]) & set(post_sorted[:5])),
            "top5_new_entries": sorted(set(post_sorted[:5]) - set(pre_sorted[:5])),
            "top5_dropped": sorted(set(pre_sorted[:5]) - set(post_sorted[:5])),
        })
    return out


def _orientation(gc: pd.DataFrame, country_rows: list[dict],
                 latest_aggregate_share: float) -> dict:
    both = [row for row in country_rows
            if row["new_to_reentry_female_gap_pp"] is not None]
    reentry_heavy_female = [
        row for row in both
        if row["reentry_heavy_and_female_heavy"]
    ]
    reentry_heavy_female.sort(
        key=lambda row: row["reentry_female_share_pct"], reverse=True)
    new_more = sorted(
        [row for row in both if row["orientation"] == "new_more_female"],
        key=lambda row: row["new_to_reentry_female_gap_pp"], reverse=True)
    reentry_more = sorted(
        [row for row in both if row["orientation"] == "reentry_more_female"],
        key=lambda row: row["new_to_reentry_female_gap_pp"])
    return {
        "latest_aggregate_female_share_pct": _r(latest_aggregate_share),
        "reentry_heavy_threshold_pct": REENTRY_HEAVY_PCT,
        "orientation_gap_threshold_pp": ORIENTATION_GAP_PP,
        "reentry_heavy_and_female_heavy": [
            {
                "country": row["country"],
                "latest_total": row["latest_total"],
                "latest_female_share_pct": row["latest_female_share_pct"],
                "reentry_share_of_focus_pct": row["reentry_share_of_focus_pct"],
                "reentry_female_share_pct": row["reentry_female_share_pct"],
                "new_to_reentry_female_gap_pp":
                    row["new_to_reentry_female_gap_pp"],
            }
            for row in reentry_heavy_female
        ],
        "new_more_female": [
            {
                "country": row["country"],
                "gap_pp": row["new_to_reentry_female_gap_pp"],
                "new_female_share_pct": row["new_female_share_pct"],
                "reentry_female_share_pct": row["reentry_female_share_pct"],
                "latest_total": row["latest_total"],
            }
            for row in new_more
        ],
        "reentry_more_female": [
            {
                "country": row["country"],
                "gap_pp": row["new_to_reentry_female_gap_pp"],
                "new_female_share_pct": row["new_female_share_pct"],
                "reentry_female_share_pct": row["reentry_female_share_pct"],
                "latest_total": row["latest_total"],
            }
            for row in reentry_more
        ],
        "gap_distribution": _gap_distribution(both),
        "rank_stability": _rank_stability(gc),
    }


def _threshold_variants(gc: pd.DataFrame, latest_aggregate_share: float) -> list[dict]:
    out = []
    for threshold in ALT_THRESHOLDS:
        rows = _country_table(gc, latest_aggregate_share, min_volume=threshold)
        gaps = [row["new_to_reentry_female_gap_pp"] for row in rows
                if row["new_to_reentry_female_gap_pp"] is not None]
        ranked_pos = sorted(
            (row for row in rows if row["new_to_reentry_female_gap_pp"] is not None),
            key=lambda row: row["new_to_reentry_female_gap_pp"], reverse=True)
        out.append({
            "min_volume": threshold,
            "n_countries": len(rows),
            "n_with_both_channels": len(gaps),
            "mean_gap_pp": _r(sum(gaps) / len(gaps)) if gaps else None,
            "median_gap_pp": _r(pd.Series(gaps).median()) if gaps else None,
            "new_more_female_count": int(sum(1 for gap in gaps if gap > 0)),
            "reentry_more_female_count": int(sum(1 for gap in gaps if gap < 0)),
            "largest_new_more_female": [
                {"country": row["country"],
                 "gap_pp": row["new_to_reentry_female_gap_pp"]}
                for row in ranked_pos[:3]],
            "largest_reentry_more_female": [
                {"country": row["country"],
                 "gap_pp": row["new_to_reentry_female_gap_pp"]}
                for row in ranked_pos[-3:][::-1]],
        })
    return out


def _focus_only_aggregate(gc: pd.DataFrame, fiscal_year: str) -> dict:
    frame = _frame(gc, fiscal_year)
    female = male = 0.0
    for channel in FOCUS_CHANNELS:
        if channel not in frame.index.get_level_values("channel_canonical"):
            continue
        block = frame.xs(channel, level="channel_canonical")
        female += float(block["female"].sum())
        male += float(block["male"].sum())
    total = female + male
    return {
        "fiscal_year": fiscal_year,
        "female": int(female),
        "male": int(male),
        "total": int(total),
        "female_share_pct": _r(_share(female, total), 6),
    }


def _all_four_all_female(gc: pd.DataFrame, fiscal_year: str) -> dict:
    frame = _frame(gc, fiscal_year)
    female = float(frame["female"].sum())
    male = float(frame["male"].sum())
    total = female + male
    return {
        "fiscal_year": fiscal_year,
        "female": int(female),
        "male": int(male),
        "total": int(total),
        "female_share_pct": _r(_share(female, total), 6),
    }


def _robustness(gc: pd.DataFrame, latest_aggregate_share: float) -> dict:
    comparable_four = _decompose(
        gc, COMPARABLE_BASE_FY, LATEST_FY, CHANNELS, "four_channel_comparable")
    comparable_two = _decompose(
        gc, COMPARABLE_BASE_FY, LATEST_FY, FOCUS_CHANNELS,
        "new_reentry_comparable")
    base_reported = _decompose(
        gc, BASE_FY, LATEST_FY, BASE_TO_LATEST_CHANNELS,
        "channels_reported_both_years")
    base_all_four = _decompose(
        gc, BASE_FY, LATEST_FY, CHANNELS, "all_four_missing_is_zero")

    focus_base = _focus_only_aggregate(gc, COMPARABLE_BASE_FY)
    focus_latest = _focus_only_aggregate(gc, LATEST_FY)
    all_base = _all_four_all_female(gc, COMPARABLE_BASE_FY)
    all_latest = _all_four_all_female(gc, LATEST_FY)

    return {
        "thresholds": _threshold_variants(gc, latest_aggregate_share),
        "comparable_window": {
            "start_fiscal_year": COMPARABLE_BASE_FY,
            "end_fiscal_year": LATEST_FY,
            "reason": (
                "individual_new is not separately reported before 2081/82, so "
                "new-vs-reentry comparisons start there; 2082/83 is the latest "
                "complete year."
            ),
            "four_channel_decomposition": comparable_four,
            "new_reentry_decomposition": comparable_two,
        },
        "exclude_g2g_agency": {
            "note": (
                "Aggregate female share restricted to individual_new and "
                "individual_reentry, excluding g2g and recruiting_agency."
            ),
            "base": focus_base,
            "latest": focus_latest,
            "female_share_change_pp": _r(
                focus_latest["female_share_pct"] - focus_base["female_share_pct"]
                if focus_latest["female_share_pct"] is not None
                and focus_base["female_share_pct"] is not None else None, 6),
            "all_channel_base": all_base,
            "all_channel_latest": all_latest,
            "all_channel_female_share_change_pp": _r(
                all_latest["female_share_pct"] - all_base["female_share_pct"]
                if all_latest["female_share_pct"] is not None
                and all_base["female_share_pct"] is not None else None, 6),
        },
        "only_channels_reported_in_both_years": {
            "channels": list(BASE_TO_LATEST_CHANNELS),
            "start_fiscal_year": BASE_FY,
            "end_fiscal_year": LATEST_FY,
            "decomposition": base_reported,
            "note": (
                "individual_new and g2g are absent at the 2079/80 base; this "
                "variant keeps only re-entry and agency so channel weights are "
                "defined in both years."
            ),
        },
        "all_four_missing_as_zero": {
            "start_fiscal_year": BASE_FY,
            "end_fiscal_year": LATEST_FY,
            "decomposition": base_all_four,
            "note": (
                "Treats unreported individual_new and g2g at the base as zero. "
                "The emergence of those labels loads onto the interaction term, "
                "so this is a sensitivity check, not the headline estimate."
            ),
        },
    }


def _latest_aggregate(gc: pd.DataFrame) -> dict:
    return _all_four_all_female(gc, LATEST_FY)


def build() -> dict:
    panel = load_panel(safe=True)
    gc = _gender_channel_year(panel)
    latest_aggregate = _latest_aggregate(gc)
    latest_share = latest_aggregate["female_share_pct"]
    annual = _annual_table(gc)
    latest_annual = next(row for row in annual
                         if row["fiscal_year"] == LATEST_FY)
    country_rows = _country_table(gc, latest_share)

    new_share = latest_annual["channels"]["individual_new"]["female_share_pct"]
    reentry_share = latest_annual["channels"]["individual_reentry"]["female_share_pct"]
    gap = latest_annual["new_to_reentry_female_gap_pp"]

    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": (
                "migration_parser.research.patterns_gender_channel."
                "_gender_channel_year"
            ),
            "safe_rows": int(len(panel)),
            "safe_documents": int(panel["doc_id"].nunique()),
            "safe_fiscal_years": sorted(
                panel["reconciled_fiscal_year"].unique(), key=_fy_key),
            "complete_fiscal_years": _complete_years(gc),
            "base_fy": BASE_FY,
            "latest_fy": LATEST_FY,
            "comparable_base_fy": COMPARABLE_BASE_FY,
            "partial_fy": PARTIAL_FY,
            "partial_fy_excluded": True,
            "min_volume": MIN_VOLUME,
            "alternative_min_volumes": list(ALT_THRESHOLDS),
            "top_destinations": TOP_DESTINATIONS,
            "focus_channels": list(FOCUS_CHANNELS),
            "channels": list(CHANNELS),
            "orientation_gap_threshold_pp": ORIENTATION_GAP_PP,
            "reentry_heavy_threshold_pct": REENTRY_HEAVY_PCT,
            "latest_new_female_share_pct": new_share,
            "latest_reentry_female_share_pct": reentry_share,
            "latest_new_to_reentry_female_gap_pp": gap,
            "latest_female_share_pct": latest_share,
        },
        "definitions": {
            "female_share_pct": (
                "female approvals / (female + male approvals) * 100 within the "
                "stated channel or country. Sex is reported at approval."
            ),
            "new_to_reentry_female_gap_pp": (
                "female share in individual_new minus female share in "
                "individual_reentry, in percentage points. Positive means new "
                "approvals are more female than re-entry approvals; negative "
                "means re-entry is more female."
            ),
            "reentry_share_of_focus_pct": (
                "individual_reentry approvals / (individual_new + "
                "individual_reentry approvals) * 100."
            ),
            "within_channel_pp": (
                "sum_c w_c0 * (s_c1 - s_c0): the part of the aggregate female-"
                "share change coming from female shares moving inside channels."
            ),
            "channel_composition_pp": (
                "sum_c s_c0 * (w_c1 - w_c0): the part coming from the mix of "
                "approvals shifting between channels."
            ),
            "interaction_residual_pp": (
                "sum_c (w_c1 - w_c0) * (s_c1 - s_c0): the joint movement term."
            ),
            "comparable_window": (
                "2081/82 -> 2082/83, the only window in which all four "
                "canonical channels are separately reported."
            ),
        },
        "caveats": [
            (
                "individual_reentry is an approval-channel label, not a unique-"
                "person migration history; it does not identify returners, "
                "repeat migrants, or the same person across years."
            ),
            (
                "Sex is reported at approval; female shares describe approved "
                "permits, not the resident stock, arrivals, or returners."
            ),
            (
                "2083/84 is partial and is excluded from every level, trend, "
                "decomposition and robustness comparison."
            ),
            (
                "individual_new and g2g are not separately reported at the "
                "2079/80 base, so the primary new-vs-reentry comparison uses "
                "2081/82 -> 2082/83. Base-to-latest channel changes are not "
                "comparable for those labels."
            ),
            (
                "Channel and sex totals can move because reporting templates or "
                "entity resolution change, not only because flows change."
            ),
            (
                "Country-level gaps use only resolved destinations above the "
                "volume threshold; small corridors can have extreme shares with "
                "little volume."
            ),
        ],
        "annual": annual,
        "latest_summary": {
            "fiscal_year": LATEST_FY,
            "female": latest_aggregate["female"],
            "male": latest_aggregate["male"],
            "total": latest_aggregate["total"],
            "female_share_pct": latest_share,
            "new_female_share_pct": new_share,
            "reentry_female_share_pct": reentry_share,
            "new_to_reentry_female_gap_pp": gap,
        },
        "country_table": {
            "latest_fiscal_year": LATEST_FY,
            "comparable_base_fiscal_year": COMPARABLE_BASE_FY,
            "min_volume": MIN_VOLUME,
            "n_countries": len(country_rows),
            "destinations": country_rows,
        },
        "decomposition": {
            "comparable_window": {
                "start_fiscal_year": COMPARABLE_BASE_FY,
                "end_fiscal_year": LATEST_FY,
                "new_reentry": _decompose(
                    gc, COMPARABLE_BASE_FY, LATEST_FY, FOCUS_CHANNELS,
                    "new_reentry_comparable"),
                "four_channel": _decompose(
                    gc, COMPARABLE_BASE_FY, LATEST_FY, CHANNELS,
                    "four_channel_comparable"),
            },
            "base_to_latest": {
                "start_fiscal_year": BASE_FY,
                "end_fiscal_year": LATEST_FY,
                "channels_reported_both_years": _decompose(
                    gc, BASE_FY, LATEST_FY, BASE_TO_LATEST_CHANNELS,
                    "channels_reported_both_years"),
                "all_four_missing_as_zero": _decompose(
                    gc, BASE_FY, LATEST_FY, CHANNELS,
                    "all_four_missing_is_zero"),
            },
        },
        "growth_decomposition": {
            "comparable_window": _growth_decomposition(
                gc, COMPARABLE_BASE_FY, LATEST_FY, CHANNELS,
                "four_channel_comparable"),
            "base_to_latest_reentry_agency": _growth_decomposition(
                gc, BASE_FY, LATEST_FY, BASE_TO_LATEST_CHANNELS,
                "channels_reported_both_years"),
        },
        "trajectories": _trajectories(gc, country_rows),
        "orientation": _orientation(gc, country_rows, latest_share),
        "robustness": _robustness(gc, latest_share),
    }
