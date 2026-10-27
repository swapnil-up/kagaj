"""Explicit outcome denominators for the migration panel.

The ``analysis_safe`` flag is a reviewed-channel subset, not a total-approval
series. This module builds four clearly named denominators, a coverage table
by fiscal year, denominator-aware country growth comparisons, and the
annual-vs-monthly reconciliation used in the pattern book.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .audit import _fy_key
from .datasets import load_panel

BASE_FY = "2079/80"
LATEST_FY = "2082/83"
PARTIAL_FY = "2083/84"

MODERN_CHANNELS = (
    "g2g",
    "individual_new",
    "individual_reentry",
    "recruiting_agency",
)
SMALL_BASE = 1000
GROWTH_FLAG_PP = 100.0

OUTCOME_DEFINITIONS = {
    "total_verified": (
        "All verified, resolved component rows, including legalization and "
        "old-template new_entry. This is the broadest additive total."
    ),
    "deployment_verified": (
        "Verified component rows excluding legalization. Best long-run volume "
        "denominator, but old-template new_entry is not split into individual "
        "new versus g2g."
    ),
    "reviewed_channels": (
        "The current analysis_safe subset: reviewed g2g, individual_new, "
        "individual_reentry and recruiting_agency. Excludes legalization and "
        "old-template new_entry, so its coverage changes across template breaks."
    ),
    "modern_consistent": (
        "Four modern channels only (g2g, individual_new, individual_reentry, "
        "recruiting_agency). Available from FY2081/82 onward; use for "
        "channel-comparable comparisons."
    ),
}




LEGACY_CHANNEL_REVIEW = {
    "new_entry": {
        "decision": "include in deployment_verified",
        "reason": (
            "The old template prints new entries without separating individual "
            "new from g2g. Keep the lumped channel in deployment totals, but "
            "never allocate it to a modern channel."
        ),
        "channel_comparable": False,
    },
    "legalization": {
        "decision": "keep as a separate policy series",
        "reason": (
            "Regularization is not a deployment flow and changes with amnesty "
            "policy. It is excluded from deployment_verified."
        ),
        "channel_comparable": False,
    },
}


def _round(value, digits: int = 4):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return round(float(value), digits)


def _growth_pct(before: float, after: float):
    if before <= 0:
        return None
    return (after / before - 1.0) * 100.0


def _country_detail() -> pd.DataFrame:
    panel = load_panel(safe=False)
    d = panel[
        (panel["section"] == "country")
        & (panel["row_type"] == "detail")
        & (panel["gender"] == "total")
        & (panel["entity_resolved"])
        & (panel["verified"])
    ].copy()
    return d


def _single_basis(d: pd.DataFrame, prefer: str = "annual") -> pd.DataFrame:
    from ..analysis import fiscal_year_panel

    return fiscal_year_panel(d, prefer=prefer)


def _annual_outcomes(d: pd.DataFrame) -> list[dict]:
    single = _single_basis(d)
    single = single.copy()
    single["is_legalization"] = single["channel_canonical"] == "legalization"
    single["is_new_entry"] = single["channel_canonical"] == "new_entry"
    single["is_modern"] = single["channel_canonical"].isin(MODERN_CHANNELS)
    rows = []
    for fy, block in single.groupby("reconciled_fiscal_year"):
        total = int(block["count"].sum())
        legalization = int(block.loc[block["is_legalization"], "count"].sum())
        new_entry = int(block.loc[block["is_new_entry"], "count"].sum())
        reviewed = int(block.loc[block["analysis_safe"], "count"].sum())
        deployment = total - legalization
        modern = int(block.loc[block["is_modern"], "count"].sum())
        modern_reported = set(block.loc[block["is_modern"],
                                   "channel_canonical"])
        rows.append({
            "fiscal_year": str(fy),
            "partial": str(fy) == PARTIAL_FY,
            "total_verified": total,
            "deployment_verified": deployment,
            "reviewed_channels": reviewed,
            "legalization": legalization,
            "new_entry": new_entry,
            "modern_consistent": modern if modern_reported == set(MODERN_CHANNELS)
            else None,
            "modern_complete": bool(modern_reported == set(MODERN_CHANNELS)),
            "reviewed_share_of_total_pct": _round(100.0 * reviewed / total)
            if total else None,
            "reviewed_share_of_deployment_pct": _round(
                100.0 * reviewed / deployment) if deployment else None,
        })
    rows.sort(key=lambda r: _fy_key(r["fiscal_year"]))
    return rows


def _coverage(d: pd.DataFrame, annual: list[dict]) -> dict:
    docs = d.groupby("reconciled_fiscal_year")["doc_id"].nunique()
    annual_docs = (d[d["doc_type"] == "annual"]
                   .groupby("reconciled_fiscal_year")["doc_id"].nunique())
    monthly_docs = (d[d["doc_type"] == "single_month"]
                    .groupby("reconciled_fiscal_year")["doc_id"].nunique())
    rows = []
    for row in annual:
        fy = row["fiscal_year"]
        rows.append({
            **row,
            "documents": int(docs.get(fy, 0)),
            "annual_documents": int(annual_docs.get(fy, 0)),
            "monthly_documents": int(monthly_docs.get(fy, 0)),
        })
    return {
        "base_fiscal_year": BASE_FY,
        "latest_fiscal_year": LATEST_FY,
        "partial_fiscal_year": PARTIAL_FY,
        "rows": rows,
    }


def _pivot(d: pd.DataFrame, column: str) -> pd.DataFrame:
    frame = d.copy()
    if column == "reviewed_channels":
        frame = frame[frame["analysis_safe"]]
    elif column == "deployment_verified":
        frame = frame[frame["channel_canonical"] != "legalization"]
    elif column == "modern_consistent":
        frame = frame[frame["channel_canonical"].isin(MODERN_CHANNELS)]
    return frame.pivot_table(index="reconciled_fiscal_year",
                             columns="name_canonical", values="count",
                             aggfunc="sum", fill_value=0)


def _country_growth(d: pd.DataFrame) -> list[dict]:
    single = _single_basis(d)
    pivots = {key: _pivot(single, key) for key in (
        "total_verified", "deployment_verified", "reviewed_channels",
        "modern_consistent")}
    if BASE_FY not in pivots["total_verified"].index:
        return []
    names = sorted(set().union(*[set(p.columns) for p in pivots.values()]))
    rows = []
    for name in names:
        values = {}
        for key, pivot in pivots.items():
            base = float(pivot.loc[BASE_FY, name]) if (
                BASE_FY in pivot.index and name in pivot.columns) else 0.0
            latest = float(pivot.loc[LATEST_FY, name]) if (
                LATEST_FY in pivot.index and name in pivot.columns) else 0.0
            values[key] = (base, latest)
        base_total, latest_total = values["total_verified"]
        base_deploy, latest_deploy = values["deployment_verified"]
        base_reviewed, latest_reviewed = values["reviewed_channels"]
        if latest_total < SMALL_BASE:
            continue
        deployment_growth = _growth_pct(base_deploy, latest_deploy)
        reviewed_growth = _growth_pct(base_reviewed, latest_reviewed)
        rows.append({
            "country": str(name),
            "base_total_verified": int(base_total),
            "latest_total_verified": int(latest_total),
            "base_deployment_verified": int(base_deploy),
            "latest_deployment_verified": int(latest_deploy),
            "base_reviewed_channels": int(base_reviewed),
            "latest_reviewed_channels": int(latest_reviewed),
            "base_reviewed_share_pct": _round(
                100.0 * base_reviewed / base_total) if base_total else None,
            "total_growth_pct": _round(_growth_pct(base_total, latest_total)),
            "deployment_growth_pct": _round(deployment_growth),
            "reviewed_growth_pct": _round(reviewed_growth),
            "reviewed_minus_deployment_growth_pp": _round(
                reviewed_growth - deployment_growth
                if reviewed_growth is not None and deployment_growth is not None
                else None),
            "deployment_recovered": bool(latest_deploy >= base_deploy)
            if base_deploy > 0 else None,
            "reviewed_recovered": bool(latest_reviewed >= base_reviewed)
            if base_reviewed > 0 else None,
            "small_base": bool(base_deploy < SMALL_BASE or base_reviewed < SMALL_BASE),
            "sign_flip": bool(
                deployment_growth is not None and reviewed_growth is not None
                and (deployment_growth >= 0) != (reviewed_growth >= 0)),
        })
    rows.sort(key=lambda r: r["latest_total_verified"], reverse=True)
    return rows


def _suspect(rows: list[dict]) -> dict:
    flagged = [r for r in rows
               if r["small_base"] or r["sign_flip"]
               or (r["reviewed_minus_deployment_growth_pp"] is not None
                   and abs(r["reviewed_minus_deployment_growth_pp"])
                   >= GROWTH_FLAG_PP)]
    flagged.sort(key=lambda r: abs(
        r["reviewed_minus_deployment_growth_pp"] or 0), reverse=True)
    return {
        "threshold_growth_pp": GROWTH_FLAG_PP,
        "small_base_threshold": SMALL_BASE,
        "n_flagged": len(flagged),
        "rows": flagged,
    }


def _gap_fill() -> dict | None:
    panel = load_panel(safe=False)
    docs = ["report2020_annex_X"]
    g = panel[
        panel["doc_id"].astype(str).isin(docs)
        & (panel["section"] == "country")
        & (panel["row_type"] == "detail")
        & (panel["entity_resolved"])
        & (panel["channel_class"] == "component")
    ].copy()
    if g.empty:
        return None
    single = _single_basis(g)
    total = int(single.loc[single["gender"] == "total", "count"].sum())
    genders = int(single.loc[single["gender"].isin(["male", "female"]),
                            "count"].sum())
    legalization = int(single.loc[
        (single["gender"] == "total")
        & (single["channel_canonical"] == "legalization"), "count"].sum())
    new_entry = int(single.loc[
        (single["gender"] == "total")
        & (single["channel_canonical"] == "new_entry"), "count"].sum())
    return {
        "fiscal_year": "2075/76",
        "documents": docs,
        "status": "unverified_gap_fill",
        "total_unverified": total,
        "deployment_unverified": total - legalization,
        "legalization": legalization,
        "new_entry": new_entry,
        "total_from_male_female": genders,
        "gender_total_difference": genders - total,
        "known_arithmetic_errors": 2,
        "note": (
            "FY2075/76 has only report2020_annex_X, whose Qatar recruiting-agency "
            "row prints Total=68,955 while Male+Female=68,956. Use this as a "
            "flagged gap-fill only; never pool it with verified years."
        ),
    }


def _reconciliation(d: pd.DataFrame) -> dict:
    block = d[d["reconciled_fiscal_year"] == LATEST_FY]
    annual = (block[block["doc_type"] == "annual"]
              .groupby(["name_canonical", "channel_canonical"])["count"]
              .sum())
    monthly = (block[block["doc_type"] == "single_month"]
               .groupby(["name_canonical", "channel_canonical"])["count"]
               .sum())
    pairs = pd.concat([annual.rename("annual"), monthly.rename("monthly")],
                      axis=1).fillna(0)
    pairs["difference"] = pairs["annual"] - pairs["monthly"]
    pairs["abs_difference"] = pairs["difference"].abs()
    mismatches = pairs[pairs["difference"] != 0].reset_index()
    rows = [{
        "country": row["name_canonical"],
        "channel": row["channel_canonical"],
        "annual": int(row["annual"]),
        "monthly": int(row["monthly"]),
        "difference": int(row["difference"]),
    } for _, row in mismatches.sort_values(
        "abs_difference", ascending=False).iterrows()]
    by_country = (pairs.reset_index().groupby("name_canonical")["abs_difference"]
                  .sum().sort_values(ascending=False))
    return {
        "fiscal_year": LATEST_FY,
        "pairs": int(len(pairs)),
        "exact_pairs": int((pairs["difference"] == 0).sum()),
        "mismatched_pairs": int((pairs["difference"] != 0).sum()),
        "total_abs_difference": int(pairs["abs_difference"].sum()),
        "mismatches": rows[:20],
        "by_country": [{"country": str(name), "abs_difference": int(value)}
                       for name, value in by_country.head(10).items()],
        "note": (
            "FY2082/83 is the only year with all 12 modern monthly documents. "
            "Compare annual and monthly totals within country x channel; do not "
            "sum annual and monthly rows together."
        ),
    }


def build() -> dict:
    d = _country_detail()
    annual = _annual_outcomes(d)
    country_growth = _country_growth(d)
    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "safe_rows_all": int(len(load_panel(safe=True))),
            "base_fy": BASE_FY,
            "latest_fy": LATEST_FY,
            "partial_fy": PARTIAL_FY,
            "definitions": OUTCOME_DEFINITIONS,
            "modern_channels": list(MODERN_CHANNELS),
            "caveat": (
                "The reviewed_channels series is a reviewed-subset total, not "
                "all approvals. Use deployment_verified for long-run volume and "
                "modern_consistent for channel comparisons."
            ),
        },
        "coverage": _coverage(d, annual),
        "gap_fill": _gap_fill(),
        "legacy_channel_review": LEGACY_CHANNEL_REVIEW,
        "country_growth": country_growth,
        "suspect_series": _suspect(country_growth),
        "annual_monthly_reconciliation": _reconciliation(d),
    }
