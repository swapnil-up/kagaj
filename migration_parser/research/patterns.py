"""Pattern metrics for the Phase 1 migration pattern book.

All functions read the safe, single-basis builders. They are deliberately
descriptive: they surface anomalies and candidate hypotheses, not causal
estimates.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from . import (
    audit,
    patterns_destinations,
    patterns_districts,
    patterns_gender_channel,
    patterns_gender_country,
    patterns_outcomes,
    patterns_reentry,
    patterns_reentry_gender,
    patterns_robustness,
    patterns_time,
)
from .datasets import (
    archive_panel,
    country_channel_year,
    country_gender_year,
    country_year,
    district_gender_year,
    district_year,
    load_panel,
    series,
)

BASE_FY = "2079/80"
LATEST_FY = "2082/83"
PARTIAL_FY = "2083/84"
MIN_DESTINATION = 1000


def _top_by_latest(cy: pd.DataFrame, base: str, latest: str, n: int = 10):
    pivot = cy.pivot_table(index="fiscal_year", columns="country",
                           values="count", aggfunc="sum", fill_value=0)
    latest_counts = pivot.loc[latest] if latest in pivot.index else pivot.iloc[-1]
    return pivot, latest_counts.sort_values(ascending=False).head(n).index.tolist()


def destination_index(cy: pd.DataFrame, base: str = BASE_FY,
                      latest: str = LATEST_FY, n: int = 8) -> dict:
    pivot, names = _top_by_latest(cy, base, latest, n)
    years = [fy for fy in sorted(pivot.index, key=audit._fy_key)
             if audit._fy_key(fy) <= audit._fy_key(latest)]
    series = {}
    for name in names:
        values = []
        base_value = float(pivot.loc[base, name]) if base in pivot.index else 0.0
        for fy in years:
            value = float(pivot.loc[fy, name])
            values.append(round(value / base_value * 100, 1)
                          if base_value else None)
        series[name] = values
    return {"base": base, "years": years, "series": series}


def recovery(cy: pd.DataFrame, pre: str = BASE_FY,
             post: str = LATEST_FY) -> list[dict]:
    pivot = cy.pivot_table(index="fiscal_year", columns="country",
                           values="count", aggfunc="sum", fill_value=0)
    if pre not in pivot.index or post not in pivot.index:
        return []
    pre_tot = float(pivot.loc[pre].sum())
    rows = []
    for name in pivot.columns:
        a = float(pivot.loc[pre, name])
        b = float(pivot.loc[post, name])
        if a < MIN_DESTINATION:
            continue
        rows.append({
            "country": str(name),
            "pre": int(a),
            "latest": int(b),
            "pre_share_pct": round(a / pre_tot * 100, 2) if pre_tot else 0,
            "growth_pct": round((b / a - 1) * 100, 1),
            "recovered": bool(b >= a),
        })
    return sorted(rows, key=lambda r: r["growth_pct"], reverse=True)


def female_summary(cg: pd.DataFrame) -> dict:
    pivot = cg.pivot_table(index="fiscal_year", columns="gender",
                           values="count", aggfunc="sum", fill_value=0)
    pivot["total"] = pivot.get("male", 0) + pivot.get("female", 0)
    pivot["female_share_pct"] = pivot["female"] / pivot["total"].replace(0, pd.NA) * 100
    annual = [{"fiscal_year": str(fy),
               "female": int(row.get("female", 0)),
               "male": int(row.get("male", 0)),
               "female_share_pct": round(float(row["female_share_pct"]), 2),
               "partial": str(fy) == PARTIAL_FY}
              for fy, row in pivot.iterrows() if pd.notna(row["female_share_pct"])]
    latest = audit._female_shares(cg, LATEST_FY, min_count=2000)
    change = []
    if BASE_FY in pivot.index and LATEST_FY in pivot.index:
        base = cg[cg["fiscal_year"] == BASE_FY].pivot_table(
            index="country", columns="gender", values="count",
            aggfunc="sum", fill_value=0)
        now = cg[cg["fiscal_year"] == LATEST_FY].pivot_table(
            index="country", columns="gender", values="count",
            aggfunc="sum", fill_value=0)
        for name in set(base.index) & set(now.index):
            b = float(base.loc[name].get("male", 0) + base.loc[name].get("female", 0))
            n = float(now.loc[name].get("male", 0) + now.loc[name].get("female", 0))
            if b < MIN_DESTINATION or n < MIN_DESTINATION:
                continue
            bf = float(base.loc[name].get("female", 0))
            nf = float(now.loc[name].get("female", 0))
            change.append({"country": str(name),
                           "pre_share_pct": round(bf / b * 100, 1),
                           "latest_share_pct": round(nf / n * 100, 1),
                           "change_pp": round((nf / n - bf / b) * 100, 1),
                           "latest_total": int(n)})
        change.sort(key=lambda r: r["change_pp"], reverse=True)
    return {"annual": annual, "latest": latest, "change": change[:12] + change[-8:]}


def channel_summary(cc: pd.DataFrame) -> dict:
    pivot = cc.pivot_table(index="fiscal_year", columns="channel_canonical",
                           values="count", aggfunc="sum", fill_value=0)
    share = pivot.div(pivot.sum(axis=1).replace(0, pd.NA), axis=0) * 100
    rows = []
    for fy in sorted(pivot.index, key=audit._fy_key):
        rows.append({"fiscal_year": fy,
                     "count": int(pivot.loc[fy].sum()),
                     "partial": str(fy) == PARTIAL_FY,
                     "channels": {str(c): round(float(share.loc[fy, c]), 2)
                                  for c in pivot.columns
                                  if pd.notna(share.loc[fy, c])}})
    return {"by_year": rows, "columns": [str(c) for c in pivot.columns]}


def reentry_summary(cc: pd.DataFrame) -> list[dict]:
    pivot = cc.pivot_table(index="fiscal_year", columns="channel_canonical",
                           values="count", aggfunc="sum", fill_value=0)
    rows = []
    for fy in sorted(pivot.index, key=audit._fy_key):
        total = float(pivot.loc[fy].sum())
        reentry = float(pivot.loc[fy].get("individual_reentry", 0))
        rows.append({"fiscal_year": str(fy), "total": int(total),
                     "reentry": int(reentry),
                     "reentry_share_pct": round(reentry / total * 100, 2)
                     if total else 0})
    return rows


def district_summary(dist: pd.DataFrame, dgen: pd.DataFrame) -> dict:
    renamed = dist.rename(columns={"district": "country"})
    concentration = [r for r in audit._concentration(renamed)
                     if r["fiscal_year"] != PARTIAL_FY]
    latest = LATEST_FY if LATEST_FY in set(dist["fiscal_year"]) else sorted(
        dist["fiscal_year"], key=audit._fy_key)[-1]
    top = (dist[dist["fiscal_year"] == latest].sort_values("count", ascending=False)
           .head(15)[["district", "count"]].to_dict("records"))
    female = audit._female_shares(dgen, latest, min_count=500, entity="district")
    return {"concentration": concentration, "top_latest": top,
            "latest_fiscal_year": latest, "female_latest": female}


def district_convergence(dist: pd.DataFrame, first: str = "2074/75",
                         last: str = LATEST_FY) -> dict:
    pivot = dist.pivot_table(index="fiscal_year", columns="district",
                             values="count", aggfunc="sum", fill_value=0)
    if first not in pivot.index or last not in pivot.index:
        return {"spearman": None, "points": []}
    first_row = pivot.loc[first]
    last_row = pivot.loc[last]
    first_total = float(first_row.sum())
    points = []
    for name in pivot.columns:
        a = float(first_row[name])
        b = float(last_row[name])
        if a <= 0 or b <= 0 or first_total <= 0:
            continue
        points.append({"district": str(name),
                       "initial_share_pct": round(a / first_total * 100, 3),
                       "growth_pct": round((b / a - 1) * 100, 1),
                       "latest_count": int(b)})
    share = pd.Series([p["initial_share_pct"] for p in points])
    growth = pd.Series([p["growth_pct"] for p in points])
    return {"spearman": round(float(share.corr(growth, method="spearman")), 3)
            if len(points) > 2 else None,
            "first": first, "last": last, "points": points}


def modern_monthly(panel: pd.DataFrame) -> list[dict]:
    d = panel[(panel["section"] == "country")
              & (panel["row_type"] == "detail")
              & (panel["gender"] == "total")
              & (panel["granularity"] == "month")].copy()
    d["start"] = pd.to_datetime(d["period_ad_start"], errors="coerce")
    d = d.dropna(subset=["start"])
    grouped = (d.groupby(["doc_id", "start", "reconciled_fiscal_year"],
                         as_index=False)["count"].sum()
               .sort_values("start"))
    return [{"start": row.start.date().isoformat(),
             "fiscal_year": str(row.reconciled_fiscal_year),
             "count": int(row.count), "doc_id": str(row.doc_id)}
            for row in grouped.itertuples()]


def archive_monthly(arc: pd.DataFrame) -> list[dict]:
    d = arc[(arc["section"] == "country") & (arc["row_type"] == "detail")
            & (arc["gender"] == "total")].copy()
    chosen = []
    for period, block in d.groupby("period_bs"):
        if (block["scope"] == "final_approved").any():
            block = block[block["scope"] == "final_approved"]
        elif (block["scope"] == "month").any():
            block = block[block["scope"] == "month"]
        else:
            continue
        chosen.append({"period_bs": str(period), "count": int(block["count"].sum()),
                       "scope": str(block["scope"].iloc[0])})
    from ..scripts.cmd_archive_panel import _period_key
    chosen.sort(key=lambda r: _period_key(r["period_bs"]) or (0, 0))
    return chosen


def deaths_series(ser: pd.DataFrame) -> list[dict]:
    patterns = [
        r"(?i)cause of death, 2008/09",
        r"(?i)cause of death by year",
        r"(?i)reported number of deaths, country wise",
    ]
    for pattern in patterns:
        d = ser[(ser["metric"] == "deaths") & (ser["gender"] == "total")
                & ser["caption"].str.contains(pattern, regex=True, na=False)]
        if len(d):
            grouped = d.groupby("fiscal_year")["count"].sum()
            return [{"fiscal_year": str(fy), "deaths": int(value)}
                    for fy, value in grouped.items()]
    return []


def _hypotheses(annual, recovery_rows, female, channels, dist_conv,
                archive_rows) -> list[dict]:
    by_country = {r["country"]: r for r in recovery_rows}
    my = by_country.get("Malaysia")
    uae = by_country.get("United Arab Emirates")
    latest_annual = next((r for r in annual
                          if r["fiscal_year"] == LATEST_FY),
                         annual[-1] if annual else {})
    latest_hhi = latest_annual.get("hhi")
    first_hhi = annual[0].get("hhi") if annual else None
    reentry = channels.get("reentry", [])
    latest_reentry = next((r for r in reentry
                           if r["fiscal_year"] == LATEST_FY),
                          reentry[-1] if reentry else {})
    female_annual = female["annual"]
    female_first = female_annual[0] if female_annual else {}
    female_last = next((r for r in female_annual
                        if r["fiscal_year"] == LATEST_FY),
                       female_annual[-1] if female_annual else {})
    positive_female = [r for r in female["change"] if r["change_pp"] > 0]
    hypotheses = [
        {
            "rank": 1,
            "label": "Malaysia hysteresis",
            "pattern": (f"Malaysia was {my['pre']:,} approvals in {BASE_FY} and "
                        f"{my['latest']:,} in {LATEST_FY} ({my['growth_pct']:+.1f}%)."
                        if my else "Malaysia's recovery is incomplete."),
            "question": ("Did Malaysia's post-2020 quota/recruitment regime permanently "
                         "reduce Nepali inflows relative to other destinations?"),
            "data_needed": "Malaysia policy dates, quota changes, sectoral demand; monthly or annual country data.",
            "risk": "One country; policy timing may coincide with COVID and other Gulf shocks.",
        },
        {
            "rank": 2,
            "label": "COVID recovery divergence",
            "pattern": (f"UAE growth vs pre-COVID is {uae['growth_pct']:+.1f}%."
                        if uae else "Recovery varies sharply by destination."),
            "question": "Did border openness and migrant-dependent sectors explain recovery speed?",
            "data_needed": "Stringency indices, destination GDP/sector shares, bilateral policy dates.",
            "risk": "Approvals reflect both demand and Nepali supply; annual frequency hides timing.",
        },
        {
            "rank": 3,
            "label": "Destination diversification",
            "pattern": (f"HHI fell from {first_hhi:.3f} to {latest_hhi:.3f}."
                        if first_hhi and latest_hhi else "Concentration has fallen."),
            "question": "Is diversification driven by new recruitment-agency corridors or by individual applicants?",
            "data_needed": "Destination × channel (available), policy/MOU dates, agency-level lists.",
            "risk": "New destinations may reflect reporting changes or small initial bases.",
        },
        {
            "rank": 4,
            "label": "Feminisation by destination",
            "pattern": (f"Female share rose from {female_first.get('female_share_pct', 0):.1f}% "
                        f"to {female_last.get('female_share_pct', 0):.1f}%."
                        if female_first and female_last else "Female share is rising."),
            "question": "Which destination-specific sectors and policies drive female migration?",
            "data_needed": "Destination × sex (available), occupation/skill tables, bilateral care/hospitality demand.",
            "risk": "Sex is reported at approval; composition may reflect selection and reporting.",
        },
        {
            "rank": 5,
            "label": "Repeat migration",
            "pattern": (f"Re-entry was {latest_reentry.get('reentry_share_pct', 0):.1f}% "
                        "of annual approvals." if latest_reentry else "Re-entry is large."),
            "question": "Are repeat migrants responding to destination demand or to failed first spells?",
            "data_needed": "Re-entry counts (available), destination × re-entry, survey/return data.",
            "risk": "Re-entry is a channel label, not an individual history.",
        },
        {
            "rank": 6,
            "label": "Origin convergence",
            "pattern": (f"Spearman(initial district share, growth) = "
                        f"{dist_conv.get('spearman')}."),
            "question": "Are lagging districts catching up or falling further behind?",
            "data_needed": "District population, weather/agriculture shocks, remittance access.",
            "risk": "No district×destination flows; district totals mix destinations.",
        },
        {
            "rank": 7,
            "label": "European/Japan turn",
            "pattern": (f"The latest year has {latest_annual.get('n_entities', 0)} "
                        "active destinations." if latest_annual else "New destinations are emerging."),
            "question": "Are new European and East Asian corridors policy-led or agency-led?",
            "data_needed": "MOU dates, recruitment-agency country lists, destination language/skill requirements.",
            "risk": "Many new destinations start from small bases; composition may be volatile.",
        },
        {
            "rank": 8,
            "label": "Welfare denominator",
            "pattern": "Reported deaths are available from a separate historical series.",
            "question": "Do deaths per approval rise with scale or with destination mix?",
            "data_needed": "Deaths by destination/year (series), approvals denominator, reporting completeness.",
            "risk": "Deaths underreport; the numerator and denominator come from different sources.",
        },
    ]
    if positive_female:
        hypotheses[3]["pattern"] += (f" Largest increases: "
                                     + ", ".join(r["country"] for r in positive_female[:3]) + ".")
    if archive_rows:
        hypotheses.append({
            "rank": 9,
            "label": "Archive-era seasonality",
            "pattern": f"Archive monthly panel has {len(archive_rows)} periods before the modern panel.",
            "question": "Was the seasonal approval cycle stable before 2019?",
            "data_needed": "Complete monthly archive coverage; period-window dates.",
            "risk": "Archive scopes differ across vintages; missing months are non-random.",
        })
    return hypotheses


def build_patterns() -> dict:
    panel = load_panel(safe=True)
    cy = country_year(panel)
    cg = country_gender_year(panel)
    cc = country_channel_year(panel)
    dist = district_year(panel)
    dgen = district_gender_year(panel)
    arc = archive_panel(safe=True)
    ser = series()
    audit_report = audit.build_audit()

    annual = audit._concentration(cy)
    for row in annual:
        row["partial"] = row["fiscal_year"] == PARTIAL_FY
    channels = channel_summary(cc)
    channels["reentry"] = reentry_summary(cc)
    dist_info = district_summary(dist, dgen)
    dist_conv = district_convergence(dist)
    archive_rows = archive_monthly(arc)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "basis": {
            "rows": int(len(panel)),
            "documents": int(panel["doc_id"].nunique()),
            "fiscal_years": sorted(panel["reconciled_fiscal_year"].unique(),
                                   key=audit._fy_key),
            "base_fy": BASE_FY,
            "latest_fy": LATEST_FY,
        },
        "problems": audit_report["issues"],
        "annual": annual,
        "destinations": {
            "index": destination_index(cy),
            "recovery": recovery(cy),
            "entries": audit._entry_exit(cy, "country", BASE_FY, LATEST_FY)[0],
            "exits": audit._entry_exit(cy, "country", BASE_FY, LATEST_FY)[1],
            "outliers": audit._growth_outliers(cy, "country"),
        },
        "female": female_summary(cg),
        "channels": channels,
        "districts": {
            **dist_info,
            "convergence": dist_conv,
        },
        "monthly": {
            "modern": modern_monthly(panel),
            "archive": archive_rows,
        },
        "series": {"deaths": deaths_series(ser)},
    }
    report["hypotheses"] = _hypotheses(
        annual, report["destinations"]["recovery"], report["female"],
        channels, dist_conv, archive_rows)

    report["deep_destinations"] = patterns_destinations.build()
    report["gender_channel"] = patterns_gender_channel.build()
    report["outcomes"] = patterns_outcomes.build()
    report["reentry"] = patterns_reentry.build()
    report["gender_country"] = patterns_gender_country.build()
    report["reentry_gender"] = patterns_reentry_gender.build()
    report["deep_districts"] = patterns_districts.build()
    report["time_series"] = patterns_time.build()
    report["robustness"] = patterns_robustness.build()
    return report
