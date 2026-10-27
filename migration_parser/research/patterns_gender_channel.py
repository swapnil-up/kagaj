"""Gender and channel patterns for the Nepali labour-migration panel.

The module starts from the safe, single-basis builders and adds two derived
tables that are not pre-built in the tracked dataset: destination x sex x
channel totals, and annual channel totals. All comparisons use the last
complete year (``LATEST_FY``); the partial year is never used as a level.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from ..analysis import fiscal_year_panel
from .audit import _fy_key
from .datasets import (
    country_channel_year,
    country_gender_year,
    load_panel,
)

BASE_FY = "2079/80"
LATEST_FY = "2082/83"
PARTIAL_FY = "2083/84"
MIN_DESTINATION = 1000
MIN_DESTINATION_LATEST = 1000
TOP_DESTINATIONS = 12
DEPENDENCE_PCT = 50.0

CHANNELS = (
    "g2g",
    "individual_new",
    "individual_reentry",
    "recruiting_agency",
)


def _r(value, digits: int = 2):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return round(float(value), digits)


def _pct(value, digits: int = 2):
    return _r(100.0 * float(value), digits)


def _growth_pct(before: float, after: float):
    if before <= 0:
        return None
    return (after / before - 1.0) * 100.0


def _gender_frame(cg: pd.DataFrame, fiscal_year: str) -> pd.DataFrame:
    block = cg[cg["fiscal_year"] == fiscal_year]
    frame = block.pivot_table(index="country", columns="gender",
                              values="count", aggfunc="sum", fill_value=0)
    for column in ("male", "female"):
        if column not in frame:
            frame[column] = 0
    frame["total"] = frame["male"] + frame["female"]
    return frame


def _gender_channel_year(panel: pd.DataFrame) -> pd.DataFrame:
    """Destination x sex x channel totals, one granularity per fiscal year.

    Sex is only reported for component rows, so this table is derived from the
    male/female detail rows rather than by splitting the gender-total channel
    table. Summing over channel reproduces the sex-specific safe totals.
    """
    detail = panel[
        (panel["section"] == "country")
        & (panel["row_type"] == "detail")
        & (panel["entity_resolved"])
        & (panel["gender"].isin(["male", "female"]))
        & (panel["channel_canonical"].isin(CHANNELS))
    ].copy()
    detail = fiscal_year_panel(detail, prefer="annual")
    out = (detail.groupby(
        ["reconciled_fiscal_year", "name_canonical", "gender",
         "channel_canonical"], as_index=False)
        .agg(count=("count", "sum")))
    return out.rename(columns={
        "reconciled_fiscal_year": "fiscal_year",
        "name_canonical": "country",
    })


def _annual_gender_channel(panel: pd.DataFrame) -> list[dict]:
    cg = country_gender_year(panel)
    cc = country_channel_year(panel)
    gender = cg.groupby(["fiscal_year", "gender"])["count"].sum().unstack(fill_value=0)
    channel = cc.groupby(["fiscal_year", "channel_canonical"])["count"].sum().unstack(fill_value=0)
    years = [fy for fy in sorted(set(gender.index) | set(channel.index), key=_fy_key)
             if str(fy) != PARTIAL_FY]
    rows = []
    for fy in years:
        female = int(gender.loc[fy].get("female", 0)) if fy in gender.index else 0
        male = int(gender.loc[fy].get("male", 0)) if fy in gender.index else 0
        total = female + male
        channels = {}
        if fy in channel.index:
            channels = {str(c): int(channel.loc[fy].get(c, 0))
                        for c in CHANNELS}
        rows.append({
            "fiscal_year": str(fy),
            "female": female,
            "male": male,
            "total": total,
            "female_share_pct": _r(100.0 * female / total if total else 0),
            "channels": channels,
            "channel_shares_pct": {
                c: _r(100.0 * v / total if total else 0)
                for c, v in channels.items()
            },
        })
    return rows


def _female_growth_divergence(cg: pd.DataFrame) -> dict:
    base = _gender_frame(cg, BASE_FY)
    latest = _gender_frame(cg, LATEST_FY)
    overall = {}
    for label, frame in (("base", base), ("latest", latest)):
        female = float(frame["female"].sum())
        male = float(frame["male"].sum())
        total = female + male
        overall[label] = {
            "fiscal_year": BASE_FY if label == "base" else LATEST_FY,
            "female": int(female),
            "male": int(male),
            "total": int(total),
            "female_share_pct": _r(100.0 * female / total if total else 0),
        }
    female_growth = _growth_pct(overall["base"]["female"],
                                overall["latest"]["female"])
    male_growth = _growth_pct(overall["base"]["male"],
                              overall["latest"]["male"])
    overall["female_change"] = (overall["latest"]["female"]
                                - overall["base"]["female"])
    overall["male_change"] = (overall["latest"]["male"]
                              - overall["base"]["male"])
    overall["total_change"] = (overall["latest"]["total"]
                               - overall["base"]["total"])
    overall["female_growth_pct"] = _r(female_growth)
    overall["male_growth_pct"] = _r(male_growth)
    overall["female_minus_male_growth_pp"] = _r(
        female_growth - male_growth
        if female_growth is not None and male_growth is not None else None)
    overall["female_share_change_pp"] = _r(
        overall["latest"]["female_share_pct"]
        - overall["base"]["female_share_pct"])

    rows = []
    for country in sorted(set(base.index) | set(latest.index)):
        b = base.loc[country] if country in base.index else None
        n = latest.loc[country] if country in latest.index else None
        b_total = float(b["total"]) if b is not None else 0.0
        n_total = float(n["total"]) if n is not None else 0.0
        if b_total < MIN_DESTINATION or n_total < MIN_DESTINATION:
            continue
        b_female = float(b["female"])
        n_female = float(n["female"])
        b_male = float(b["male"])
        n_male = float(n["male"])
        fg = _growth_pct(b_female, n_female)
        mg = _growth_pct(b_male, n_male)
        rows.append({
            "country": str(country),
            "base_total": int(b_total),
            "latest_total": int(n_total),
            "female_base": int(b_female),
            "female_latest": int(n_female),
            "male_base": int(b_male),
            "male_latest": int(n_male),
            "female_growth_pct": _r(fg),
            "male_growth_pct": _r(mg),
            "female_minus_male_growth_pp": _r(
                fg - mg if fg is not None and mg is not None else None),
            "female_share_base_pct": _r(100.0 * b_female / b_total),
            "female_share_latest_pct": _r(100.0 * n_female / n_total),
            "female_share_change_pp": _r(
                100.0 * (n_female / n_total - b_female / b_total)),
        })
    rows.sort(key=lambda row: row["latest_total"], reverse=True)
    return {
        "base_fiscal_year": BASE_FY,
        "latest_fiscal_year": LATEST_FY,
        "overall": overall,
        "min_destination_count": MIN_DESTINATION,
        "destinations": rows,
    }


def _female_shift_share(cg: pd.DataFrame) -> dict:
    base = _gender_frame(cg, BASE_FY)
    latest = _gender_frame(cg, LATEST_FY)
    base_total = float(base["total"].sum())
    latest_total = float(latest["total"].sum())
    base_share = 100.0 * float(base["female"].sum()) / base_total
    latest_share = 100.0 * float(latest["female"].sum()) / latest_total

    rows = []
    for country in sorted(set(base.index) | set(latest.index)):
        b = base.loc[country] if country in base.index else None
        n = latest.loc[country] if country in latest.index else None
        b_total = float(b["total"]) if b is not None else 0.0
        n_total = float(n["total"]) if n is not None else 0.0
        if b_total == 0 and n_total == 0:
            continue
        b_female = float(b["female"]) if b is not None else 0.0
        n_female = float(n["female"]) if n is not None else 0.0
        s0 = 100.0 * b_female / b_total if b_total else 0.0
        s1 = 100.0 * n_female / n_total if n_total else 0.0
        w0 = b_total / base_total if base_total else 0.0
        w1 = n_total / latest_total if latest_total else 0.0
        within = w0 * (s1 - s0)
        composition = s0 * (w1 - w0)
        interaction = (w1 - w0) * (s1 - s0)
        rows.append({
            "country": str(country),
            "base_total": int(b_total),
            "latest_total": int(n_total),
            "base_female_share_pct": _r(s0),
            "latest_female_share_pct": _r(s1),
            "base_weight_pct": _r(100.0 * w0),
            "latest_weight_pct": _r(100.0 * w1),
            "within_pp": _r(within, 6),
            "composition_pp": _r(composition, 6),
            "interaction_pp": _r(interaction, 6),
            "total_contribution_pp": _r(within + composition + interaction, 6),
            "_within": within,
            "_composition": composition,
            "_interaction": interaction,
            "_total": within + composition + interaction,
        })

    within_total = sum(row["_within"] for row in rows)
    composition_total = sum(row["_composition"] for row in rows)
    interaction_total = sum(row["_interaction"] for row in rows)
    total_change = latest_share - base_share
    within_out = _r(within_total, 6)
    composition_out = _r(composition_total, 6)
    total_out = _r(total_change, 6)
    residual_out = _r(total_out - within_out - composition_out, 6)

    def contributors(key: str, n: int = 10):
        ranked = sorted(rows, key=lambda row: abs(row[key]), reverse=True)[:n]
        return [{
            "country": row["country"],
            "contribution_pp": _r(row[key], 6),
            "base_total": row["base_total"],
            "latest_total": row["latest_total"],
            "base_female_share_pct": row["base_female_share_pct"],
            "latest_female_share_pct": row["latest_female_share_pct"],
        } for row in ranked if abs(row[key]) > 1e-9]

    result = {
        "base_fiscal_year": BASE_FY,
        "latest_fiscal_year": LATEST_FY,
        "base_female_share_pct": _r(base_share, 6),
        "latest_female_share_pct": _r(latest_share, 6),
        "aggregate_change_pp": total_out,
        "within_destination_pp": within_out,
        "destination_composition_pp": composition_out,
        "interaction_residual_pp": residual_out,
        "interaction_check_pp": _r(interaction_total, 6),
        "components_sum_pp": _r(within_out + composition_out + residual_out, 6),
        "formula": (
            "S_t = sum_i w_it * s_it, where s_it is female share in "
            "destination i and w_it is destination i's share of approvals. "
            "delta S = sum_i w_i0*delta s_i (within) + "
            "sum_i s_i0*delta w_i (composition) + "
            "sum_i delta w_i*delta s_i (interaction residual)."
        ),
        "within_contributors": contributors("_within"),
        "composition_contributors": contributors("_composition"),
        "largest_total_contributors": contributors("_total"),
    }

    for row in rows:
        for key in ("_within", "_composition", "_interaction", "_total"):
            row.pop(key)

    return result


def _female_share_by_destination(cg: pd.DataFrame) -> list[dict]:
    base = _gender_frame(cg, BASE_FY)
    latest = _gender_frame(cg, LATEST_FY)
    rows = []
    for country in latest.index:
        n = latest.loc[country]
        n_total = float(n["total"])
        if n_total < MIN_DESTINATION_LATEST:
            continue
        n_female = float(n["female"])
        latest_share = 100.0 * n_female / n_total
        base_share = None
        b_total = 0.0
        b_female = 0.0
        if country in base.index:
            b = base.loc[country]
            b_total = float(b["total"])
            b_female = float(b["female"])
            if b_total > 0:
                base_share = 100.0 * b_female / b_total
        rows.append({
            "country": str(country),
            "latest_total": int(n_total),
            "latest_female": int(n_female),
            "latest_male": int(n["male"]),
            "latest_female_share_pct": _r(latest_share),
            "base_total": int(b_total),
            "base_female": int(b_female),
            "base_female_share_pct": _r(base_share),
            "change_pp": _r(latest_share - base_share
                            if base_share is not None else None),
            "base_above_min": bool(b_total >= MIN_DESTINATION),
        })
    rows.sort(key=lambda row: row["latest_female_share_pct"], reverse=True)
    return rows


def _female_by_channel(gc: pd.DataFrame) -> dict:
    grouped = (gc.groupby(["fiscal_year", "channel_canonical", "gender"])["count"]
               .sum().unstack("gender", fill_value=0))
    for column in ("male", "female"):
        if column not in grouped:
            grouped[column] = 0
    base_channels = set(gc.loc[gc["fiscal_year"] == BASE_FY, "channel_canonical"])
    latest_channels = set(gc.loc[gc["fiscal_year"] == LATEST_FY, "channel_canonical"])
    rows = []
    for channel in CHANNELS:
        def block(fy):
            if (fy, channel) not in grouped.index:
                return None
            row = grouped.loc[(fy, channel)]
            female = float(row["female"])
            male = float(row["male"])
            total = female + male
            return {
                "female": female,
                "male": male,
                "total": total,
                "female_share_pct": 100.0 * female / total if total else None,
            }
        b = block(BASE_FY)
        n = block(LATEST_FY)
        b_share = b["female_share_pct"] if b else None
        n_share = n["female_share_pct"] if n else None
        rows.append({
            "channel": channel,
            "base_reported": channel in base_channels,
            "latest_reported": channel in latest_channels,
            "base_female": int(b["female"]) if b else 0,
            "base_male": int(b["male"]) if b else 0,
            "base_total": int(b["total"]) if b else 0,
            "latest_female": int(n["female"]) if n else 0,
            "latest_male": int(n["male"]) if n else 0,
            "latest_total": int(n["total"]) if n else 0,
            "base_female_share_pct": _r(b_share),
            "latest_female_share_pct": _r(n_share),
            "change_pp": _r(n_share - b_share
                            if n_share is not None and b_share is not None
                            else None),
        })
    return {
        "base_fiscal_year": BASE_FY,
        "latest_fiscal_year": LATEST_FY,
        "channels": rows,
    }


def _channel_composition_by_destination(cc: pd.DataFrame) -> dict:
    latest = cc[cc["fiscal_year"] == LATEST_FY]
    base = cc[cc["fiscal_year"] == BASE_FY]
    pivot = latest.pivot_table(index="country", columns="channel_canonical",
                               values="count", aggfunc="sum", fill_value=0)
    for channel in CHANNELS:
        if channel not in pivot:
            pivot[channel] = 0
    pivot["total"] = pivot[list(CHANNELS)].sum(axis=1)
    pivot = pivot.sort_values("total", ascending=False)

    def channel_row(country, total, values):
        channels = {}
        for channel in CHANNELS:
            count = float(values.get(channel, 0))
            channels[channel] = {
                "count": int(count),
                "share_pct": _r(100.0 * count / total if total else 0),
            }
        return {
            "country": str(country),
            "total": int(total),
            "channels": channels,
            "dominant_channel": max(CHANNELS,
                                    key=lambda c: values.get(c, 0)),
            "agency_dependent": bool(
                total > 0
                and 100.0 * values.get("recruiting_agency", 0) / total
                >= DEPENDENCE_PCT),
            "g2g_dependent": bool(
                total > 0
                and 100.0 * values.get("g2g", 0) / total >= DEPENDENCE_PCT),
        }

    rows = [channel_row(country, float(row["total"]), row)
            for country, row in pivot.head(TOP_DESTINATIONS).iterrows()]

    major = pivot[pivot["total"] >= MIN_DESTINATION_LATEST]
    agency_rank = []
    g2g_rank = []
    for country, row in major.iterrows():
        total = float(row["total"])
        agency_share = 100.0 * float(row["recruiting_agency"]) / total
        g2g_share = 100.0 * float(row["g2g"]) / total
        agency_rank.append({
            "country": str(country),
            "agency_share_pct": _r(agency_share),
            "total": int(total),
        })
        g2g_rank.append({
            "country": str(country),
            "g2g_share_pct": _r(g2g_share),
            "total": int(total),
        })
    agency_rank.sort(key=lambda row: row["agency_share_pct"], reverse=True)
    g2g_rank.sort(key=lambda row: row["g2g_share_pct"], reverse=True)

    base_pivot = base.pivot_table(index="country", columns="channel_canonical",
                                  values="count", aggfunc="sum", fill_value=0)
    base_total = base_pivot.sum(axis=1) if len(base_pivot) else pd.Series(dtype=float)
    agency_base = {}
    for country in major.index:
        if country not in base_pivot.index:
            continue
        total = float(base_total.get(country, 0))
        if total <= 0:
            continue
        agency_base[str(country)] = _r(
            100.0 * float(base_pivot.loc[country].get("recruiting_agency", 0))
            / total)

    return {
        "latest_fiscal_year": LATEST_FY,
        "base_fiscal_year": BASE_FY,
        "top_destinations": rows,
        "agency_dependent": [row for row in agency_rank if row["agency_share_pct"] >= DEPENDENCE_PCT][:8],
        "g2g_dependent": [row for row in g2g_rank if row["g2g_share_pct"] >= DEPENDENCE_PCT][:8],
        "agency_share_base_pct": agency_base,
        "dependence_threshold_pct": DEPENDENCE_PCT,
    }


def _channel_growth(cc: pd.DataFrame) -> dict:
    pivot = cc.pivot_table(index="fiscal_year", columns="channel_canonical",
                           values="count", aggfunc="sum", fill_value=0)
    for channel in CHANNELS:
        if channel not in pivot:
            pivot[channel] = 0
    def components(start: str, end: str):
        start_total = float(pivot.loc[start].sum()) if start in pivot.index else 0.0
        end_total = float(pivot.loc[end].sum()) if end in pivot.index else 0.0
        delta_total = end_total - start_total
        reported = set(cc.loc[cc["fiscal_year"] == start, "channel_canonical"])
        rows = []
        for channel in CHANNELS:
            b = float(pivot.loc[start, channel]) if start in pivot.index else 0.0
            n = float(pivot.loc[end, channel]) if end in pivot.index else 0.0
            delta = n - b
            rows.append({
                "channel": channel,
                "base_count": int(b),
                "latest_count": int(n),
                "change": int(delta),
                "growth_pct": _r(_growth_pct(b, n)),
                "contribution_to_total_growth_pct": _r(
                    100.0 * delta / delta_total if delta_total else None),
                "base_reported": channel in reported,
            })
        return {
            "start_fiscal_year": start,
            "end_fiscal_year": end,
            "start_total": int(start_total),
            "end_total": int(end_total),
            "total_growth": int(delta_total),
            "channels": rows,
        }

    complete_years = [
        str(fy) for fy in pivot.index
        if str(fy) != PARTIAL_FY
        and all(channel in set(cc.loc[cc["fiscal_year"] == fy,
                                     "channel_canonical"])
                for channel in CHANNELS)
    ]
    comparable = None
    if complete_years:
        first_complete = sorted(complete_years, key=_fy_key)[0]
        comparable = components(first_complete, LATEST_FY)
        comparable["note"] = (
            "First fiscal year in which all four canonical channels are "
            "separately reported; use this window for channel-comparable growth."
        )

    return {
        "base_fiscal_year": BASE_FY,
        "latest_fiscal_year": LATEST_FY,
        "base_channels_reported": sorted(
            set(cc.loc[cc["fiscal_year"] == BASE_FY, "channel_canonical"]),
            key=CHANNELS.index),
        "components": components(BASE_FY, LATEST_FY),
        "comparable_window": comparable,
    }


def _reentry_by_destination(cc: pd.DataFrame) -> dict:
    def pivot(fy):
        block = cc[cc["fiscal_year"] == fy]
        frame = block.pivot_table(index="country", columns="channel_canonical",
                                  values="count", aggfunc="sum", fill_value=0)
        if "individual_reentry" not in frame:
            frame["individual_reentry"] = 0
        frame["total"] = frame.sum(axis=1)
        return frame

    base = pivot(BASE_FY)
    latest = pivot(LATEST_FY)
    rows = []
    top_volume = []
    for country in latest.index:
        n = latest.loc[country]
        total = float(n["total"])
        reentry = float(n["individual_reentry"])
        if total < MIN_DESTINATION_LATEST:
            continue
        share = 100.0 * reentry / total if total else 0.0
        base_share = None
        base_reentry = 0.0
        base_total = 0.0
        if country in base.index:
            b = base.loc[country]
            base_total = float(b["total"])
            base_reentry = float(b["individual_reentry"])
            if base_total > 0:
                base_share = 100.0 * base_reentry / base_total
        row = {
            "country": str(country),
            "latest_total": int(total),
            "latest_reentry": int(reentry),
            "latest_reentry_share_pct": _r(share),
            "base_total": int(base_total),
            "base_reentry": int(base_reentry),
            "base_reentry_share_pct": _r(base_share),
            "change_pp": _r(share - base_share
                            if base_share is not None else None),
        }
        rows.append(row)
        top_volume.append(row)
    rows.sort(key=lambda row: row["latest_reentry_share_pct"], reverse=True)
    top_volume.sort(key=lambda row: row["latest_reentry"], reverse=True)
    with_change = [row for row in rows if row["change_pp"] is not None]
    with_change.sort(key=lambda row: row["change_pp"], reverse=True)
    return {
        "base_fiscal_year": BASE_FY,
        "latest_fiscal_year": LATEST_FY,
        "min_destination_count": MIN_DESTINATION_LATEST,
        "destinations": rows,
        "top_volume": top_volume[:TOP_DESTINATIONS],
        "largest_increases": with_change[:8],
        "largest_decreases": with_change[-8:],
        "caveat": (
            "individual_reentry is a channel label reported at approval; it is "
            "not an individual migration history or a count of unique returners."
        ),
    }


def build() -> dict:
    panel = load_panel(safe=True)
    cg = country_gender_year(panel)
    cc = country_channel_year(panel)
    gc = _gender_channel_year(panel)

    report = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "safe_rows": int(len(panel)),
            "safe_documents": int(panel["doc_id"].nunique()),
            "safe_fiscal_years": sorted(panel["reconciled_fiscal_year"].unique(),
                                        key=_fy_key),
            "base_fy": BASE_FY,
            "latest_fy": LATEST_FY,
            "partial_fy": PARTIAL_FY,
            "partial_fy_excluded": True,
            "min_destination_count": MIN_DESTINATION,
            "top_destinations": TOP_DESTINATIONS,
            "dependence_threshold_pct": DEPENDENCE_PCT,
            "channels": list(CHANNELS),
            "definitions": {
                "female_share_pct": (
                    "female approvals / (female + male approvals) * 100; sex is "
                    "reported at approval, not at arrival or return."
                ),
                "channel": (
                    "canonical approval channel: g2g, individual_new, "
                    "individual_reentry, or recruiting_agency."
                ),
                "shift_share": (
                    "delta female share = within-destination + destination-"
                    "composition + interaction residual; contributions are in "
                    "percentage points and sum to the aggregate change."
                ),
                "reentry": (
                    "individual_reentry is a label on an approval, not an "
                    "individual history."
                ),
            },
            "caveats": [
                "2083/84 is partial and is excluded from every level and "
                "growth comparison.",
                "The safe panel already applies analysis_safe=true, detail "
                "rows only, and one granularity per fiscal year.",
                "Sex is reported at approval; female shares describe approved "
                "permits, not the resident stock or arrivals.",
                "g2g and individual_new are not separately reported in "
                "2079/80; channel changes for those labels are not comparable "
                "at the base year. The comparable window starts in 2081/82.",
                "Destination composition and female shares can change because "
                "reporting categories or entity resolution change, not only "
                "because flows change.",
                "Shift-share uses all resolved destinations, including small "
                "and new corridors; small destinations can have large "
                "percentage-point contributions with little volume.",
            ],
        },
        "annual": _annual_gender_channel(panel),
        "female_growth_divergence": _female_growth_divergence(cg),
        "female_shift_share": _female_shift_share(cg),
        "female_share_by_destination": _female_share_by_destination(cg),
        "female_by_channel": _female_by_channel(gc),
        "channel_composition_by_destination": _channel_composition_by_destination(cc),
        "channel_growth": _channel_growth(cc),
        "reentry_by_destination": _reentry_by_destination(cc),
    }
    return report
