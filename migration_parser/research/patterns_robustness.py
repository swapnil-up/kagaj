"""Robustness and sensitivity checks for the Phase 1 migration patterns.

The module deliberately re-reads the tracked panel and archive instead of
trusting the headline builders. It compares the safe and permissive row sets,
the annual and monthly bases, archive scopes, document influence, and historical
series de-duplication. Nothing here is causal: the aim is to show which
headline pattern survives a reasonable alternative data decision.
"""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

from . import audit
from .datasets import (
    archive_panel,
    country_gender_year,
    country_year,
    load_panel,
    series,
)

LATEST_FY = "2082/83"
PARTIAL_FY = "2083/84"
MIN_COMPLETE_MONTHS = 12
SCOPE_GAP_TOLERANCE_PCT = 0.5
TOP_N = 5


def _fy_key(label):
    return audit._fy_key(str(label))


def _as_int(value) -> int:
    return int(round(float(value)))


def _as_float(value, digits: int = 4) -> float:
    return round(float(value), digits)


def _hhi(values) -> float:
    vals = [float(v) for v in values if pd.notna(v)]
    total = float(sum(vals))
    if not total:
        return 0.0
    return round(sum((v / total) ** 2 for v in vals), 6)


def _counts(frame: pd.DataFrame, entity: str = "name_canonical") -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="float64")
    return frame.groupby(entity, dropna=False)["count"].sum().sort_values(
        ascending=False).astype("float64")


def _destination_metrics(frame: pd.DataFrame, entity: str = "name_canonical") -> dict:
    values = _counts(frame, entity)
    total = float(values.sum())
    positive = values[values > 0]
    return {
        "total": _as_int(total),
        "n_entities": int(len(positive)),
        "hhi": _hhi(positive),
        "top_destination": str(positive.index[0]) if len(positive) else "",
        "top_destination_count": _as_int(positive.iloc[0]) if len(positive) else 0,
        "top_destination_share_pct": _as_float(
            positive.iloc[0] / total * 100, 3) if total and len(positive) else 0.0,
        "top5_share_pct": _as_float(positive.head(TOP_N).sum() / total * 100, 3)
        if total else 0.0,
        "top5": [{"entity": str(name), "count": _as_int(value),
                  "share_pct": _as_float(value / total * 100, 3)}
                 for name, value in positive.head(TOP_N).items()],
    }


def _rank_map(frame: pd.DataFrame, entity: str = "name_canonical") -> dict:
    values = _counts(frame, entity)
    if values.empty:
        return {}
    ranks = values.rank(ascending=False, method="min")
    return {str(name): int(rank) for name, rank in ranks.items()}


def _female_share_by_fy(cg: pd.DataFrame) -> dict:
    if cg.empty:
        return {}
    pivot = cg.pivot_table(index="fiscal_year", columns="gender",
                           values="count", aggfunc="sum", fill_value=0)
    out = {}
    for fy, row in pivot.iterrows():
        total = float(row.get("male", 0) + row.get("female", 0))
        if not total:
            continue
        out[str(fy)] = {
            "female": _as_int(row.get("female", 0)),
            "male": _as_int(row.get("male", 0)),
            "female_share_pct": _as_float(
                float(row.get("female", 0)) / total * 100, 3),
        }
    return out


def _annual_metrics(cy: pd.DataFrame) -> list[dict]:
    rows = []
    for fy, block in cy.groupby("fiscal_year"):
        metrics = _destination_metrics(block, "country")
        metrics.update({
            "fiscal_year": str(fy),
            "partial": str(fy) == PARTIAL_FY,
        })
        rows.append(metrics)
    return sorted(rows, key=lambda r: _fy_key(r["fiscal_year"]))


def _variant_summary(df: pd.DataFrame) -> dict:
    country = country_year(df, prefer="annual")
    gender = country_gender_year(df, prefer="annual")
    annual = _annual_metrics(country)
    latest = next((r for r in annual if r["fiscal_year"] == LATEST_FY),
                  annual[-1] if annual else None)
    female = _female_share_by_fy(gender)
    return {
        "rows": int(len(df)),
        "documents": int(df["doc_id"].nunique()),
        "rows_by_fiscal_year": {str(k): int(v) for k, v in
                                df.groupby("reconciled_fiscal_year").size().items()},
        "documents_by_fiscal_year": {
            str(k): int(v) for k, v in
            df.groupby("reconciled_fiscal_year")["doc_id"].nunique().items()},
        "annual": annual,
        "latest": latest or {},
        "female_by_fiscal_year": female,
        "latest_female": female.get(LATEST_FY, {}),
    }


def _top5_rank_changes(safe: dict, permissive: dict) -> dict:
    safe_docs = {r["fiscal_year"]: r for r in safe["annual"]}
    perm_docs = {r["fiscal_year"]: r for r in permissive["annual"]}
    by_fy = []
    for fy in sorted(set(safe_docs) & set(perm_docs), key=_fy_key):
        safe_top = {r["entity"]: i + 1 for i, r in enumerate(
            safe_docs[fy].get("top5", []))}
        perm_top = {r["entity"]: i + 1 for i, r in enumerate(
            perm_docs[fy].get("top5", []))}
        entities = sorted(set(safe_top) | set(perm_top))
        changes = []
        for name in entities:
            a = safe_top.get(name)
            b = perm_top.get(name)
            if a != b:
                changes.append({"entity": name, "safe_rank": a,
                                "permissive_rank": b})
        if changes or set(safe_top) != set(perm_top):
            by_fy.append({"fiscal_year": fy, "changes": changes,
                          "safe_top5": list(safe_top),
                          "permissive_top5": list(perm_top)})
    latest_safe = safe.get("latest", {}).get("top5", [])
    latest_perm = permissive.get("latest", {}).get("top5", [])
    return {
        "latest_fy": LATEST_FY,
        "safe_latest_top5": latest_safe,
        "permissive_latest_top5": latest_perm,
        "latest_top5_changed": [r["entity"] for r in latest_safe]
        != [r["entity"] for r in latest_perm],
        "by_fiscal_year": by_fy,
    }


def _safe_vs_permissive(full: pd.DataFrame, safe: pd.DataFrame,
                        permissive: pd.DataFrame) -> dict:
    safe_summary = _variant_summary(safe)
    perm_summary = _variant_summary(permissive)
    safe_annual = {r["fiscal_year"]: r for r in safe_summary["annual"]}
    perm_annual = {r["fiscal_year"]: r for r in perm_summary["annual"]}
    annual_delta = {}
    for fy in sorted(set(safe_annual) | set(perm_annual), key=_fy_key):
        a = safe_annual.get(fy, {})
        b = perm_annual.get(fy, {})
        annual_delta[fy] = {
            "total": b.get("total", 0) - a.get("total", 0),
            "hhi": _as_float(b.get("hhi", 0) - a.get("hhi", 0), 6),
            "top_destination_share_pct": _as_float(
                b.get("top_destination_share_pct", 0)
                - a.get("top_destination_share_pct", 0), 3),
        }
    latest_safe = safe_annual.get(LATEST_FY, {})
    latest_perm = perm_annual.get(LATEST_FY, {})
    female_safe = safe_summary["latest_female"].get("female_share_pct")
    female_perm = perm_summary["latest_female"].get("female_share_pct")
    extra = full[(~full["analysis_safe"]) & full["analysis_safe_permissive"]]
    extra_by_channel = {}
    for channel, block in extra.groupby("channel_canonical", dropna=False):
        key = str(channel) if pd.notna(channel) else "(missing)"
        extra_by_channel[key] = {
            "rows": int(len(block)),
            "count": _as_int(block["count"].sum()),
        }
    extra_safe_ids = set(extra["doc_id"]) - set(safe["doc_id"])
    delta_share = {}
    for fy, value in annual_delta.items():
        base = safe_annual.get(fy, {}).get("total", 0)
        delta_share[fy] = _as_float(value["total"] / base * 100, 3) if base else None
    return {
        "definition": {
            "safe": "analysis_safe == true",
            "permissive": "analysis_safe_permissive == true",
            "rows_outside_safe_but_inside_permissive": int(
                ((~full["analysis_safe"]) & full["analysis_safe_permissive"]).sum()),
        },
        "permissive_is_superset": bool(safe["analysis_safe_permissive"].all()),
        "reconciliation": {
            "safe_rows_plus_extra_rows_equals_permissive_rows": bool(
                len(safe) + len(extra) == len(permissive)),
            "safe_rows": int(len(safe)),
            "extra_rows": int(len(extra)),
            "permissive_rows": int(len(permissive)),
            "extra_documents_not_in_safe": int(len(extra_safe_ids)),
            "extra_rows_by_channel": extra_by_channel,
            "interpretation": ("permissive is a row superset, but the extra rows "
                               "are largely an alternative channel basis, not an "
                               "additional migration count; compare as a basis, "
                               "never as safe + permissive"),
        },
        "full_rows": int(len(full)),
        "safe": safe_summary,
        "permissive": perm_summary,
        "delta_permissive_minus_safe": {
            "rows": perm_summary["rows"] - safe_summary["rows"],
            "documents": perm_summary["documents"] - safe_summary["documents"],
            "annual_total_by_fiscal_year": {
                fy: v["total"] for fy, v in annual_delta.items()},
            "annual_total_share_of_safe_pct": delta_share,
            "annual_metrics_by_fiscal_year": annual_delta,
            "latest_hhi": _as_float(latest_perm.get("hhi", 0)
                                    - latest_safe.get("hhi", 0), 6),
            "latest_top_destination_share_pct": _as_float(
                latest_perm.get("top_destination_share_pct", 0)
                - latest_safe.get("top_destination_share_pct", 0), 3),
            "latest_female_share_pct": _as_float(
                (female_perm or 0) - (female_safe or 0), 3)
            if female_safe is not None and female_perm is not None else None,
        },
        "top5_rank_changes": _top5_rank_changes(safe_summary, perm_summary),
    }


def _annual_monthly(safe: pd.DataFrame) -> dict:
    rows = audit._annual_monthly_gaps(safe)
    out = []
    for row in rows:
        item = dict(row)
        if not row["complete_monthly"]:
            item["validation"] = "not_validated_incomplete_monthly"
        elif row["within_tolerance"]:
            item["validation"] = "validated"
        else:
            item["validation"] = "complete_but_gap_exceeds_tolerance"
        out.append(item)
    return {
        "tolerance_fraction": audit.ANNUAL_GAP_TOLERANCE,
        "complete_months_required": MIN_COMPLETE_MONTHS,
        "complete_fiscal_years": [r["fiscal_year"] for r in out
                                  if r["complete_monthly"]],
        "incomplete_fiscal_years": [r["fiscal_year"] for r in out
                                    if not r["complete_monthly"]],
        "rows": out,
    }


def _country_totals(cy: pd.DataFrame, fy: str) -> pd.Series:
    block = cy[cy["fiscal_year"] == fy]
    if block.empty:
        return pd.Series(dtype="float64")
    return block.set_index("country")["count"].astype("float64")


def _basis_sensitivity(safe: pd.DataFrame) -> dict:
    cy_annual = country_year(safe, prefer="annual")
    cy_month = country_year(safe, prefer="month")
    base = safe[(safe["section"] == "country")
                & (safe["row_type"] == "detail")
                & (safe["gender"] == "total")
                & (safe["entity_resolved"])]
    month_docs = (base[base["granularity"] == "month"]
                  .groupby("reconciled_fiscal_year")["doc_id"].nunique())
    year_docs = (base[base["granularity"] == "year"]
                 .groupby("reconciled_fiscal_year")["doc_id"].nunique())
    rows = []
    for fy in sorted(set(cy_annual["fiscal_year"]) & set(cy_month["fiscal_year"]),
                     key=_fy_key):
        n_month = int(month_docs.get(fy, 0))
        n_year = int(year_docs.get(fy, 0))
        if not n_month or not n_year:
            continue
        a = _country_totals(cy_annual, fy)
        m = _country_totals(cy_month, fy)
        annual_total = float(a.sum())
        month_total = float(m.sum())
        joined = pd.concat([a.rename("annual"), m.rename("month")], axis=1)
        joined["diff"] = joined.get("month", 0).fillna(0) - joined.get(
            "annual", 0).fillna(0)
        overlap = int(joined.dropna(subset=["annual", "month"]).shape[0])
        max_row = joined["diff"].abs().idxmax() if len(joined) else None
        rank_a = a[a > 0].rank(ascending=False, method="min")
        rank_m = m[m > 0].rank(ascending=False, method="min")
        rank_changes = []
        for name in sorted(set(rank_a.index) & set(rank_m.index)):
            if int(rank_a[name]) != int(rank_m[name]):
                rank_changes.append({"country": str(name),
                                     "annual_rank": int(rank_a[name]),
                                     "month_rank": int(rank_m[name])})
        rows.append({
            "fiscal_year": str(fy),
            "annual_documents": n_year,
            "month_documents": n_month,
            "complete_monthly": n_month >= MIN_COMPLETE_MONTHS,
            "partial": n_month < MIN_COMPLETE_MONTHS,
            "annual_total": _as_int(annual_total),
            "monthly_total": _as_int(month_total),
            "gap_pct": _as_float(
                abs(annual_total - month_total) / annual_total * 100, 4)
            if annual_total else 0.0,
            "overlap_countries": overlap,
            "annual_only_countries": sorted(
                str(x) for x in set(a.index) - set(m.index)),
            "monthly_only_countries": sorted(
                str(x) for x in set(m.index) - set(a.index)),
            "total_absolute_country_difference": _as_int(
                joined["diff"].abs().sum()),
            "max_country_difference": {
                "country": str(max_row),
                "difference": _as_int(joined.loc[max_row, "diff"]),
            } if max_row is not None else None,
            "hhi_annual": _hhi(a[a > 0]),
            "hhi_month": _hhi(m[m > 0]),
            "hhi_difference_month_minus_annual": _as_float(
                _hhi(m[m > 0]) - _hhi(a[a > 0]), 6),
            "top_annual": str(a.idxmax()) if len(a[a > 0]) else "",
            "top_month": str(m.idxmax()) if len(m[m > 0]) else "",
            "top_changed": bool(len(a[a > 0]) and len(m[m > 0])
                                and a.idxmax() != m.idxmax()),
            "top5_rank_changes": rank_changes[:10],
        })
    return {
        "definition": ("country detail, gender=total, resolved entities; "
                       "annual rows vs monthly rows on fiscal years with both"),
        "complete_fiscal_years": [r["fiscal_year"] for r in rows
                                  if r["complete_monthly"]],
        "partial_fiscal_years": [r["fiscal_year"] for r in rows
                                 if not r["complete_monthly"]],
        "rows": rows,
    }


_BS_MONTHS = {
    "baishakh": 1, "baisakh": 1, "बैशाख": 1,
    "jestha": 2, "जेठ": 2,
    "asar": 3, "ashadh": 3, "असार": 3, "अषाढ": 3,
    "shrawan": 4, "sawan": 4, "श्रावण": 4, "साउन": 4,
    "bhadra": 5, "भदौ": 5,
    "ashwin": 6, "asoj": 6, "असोज": 6, "आश्विन": 6,
    "kartik": 7, "कात्तिक": 7, "कार्तिक": 7,
    "mangsir": 8, "मंसिर": 8, "मङ्सिर": 8,
    "poush": 9, "पुष": 9, "पौष": 9,
    "magh": 10, "माघ": 10,
    "falgun": 11, "फागुन": 11, "फाल्गुन": 11,
    "chaitra": 12, "चैत": 12, "चैत्र": 12,
    "मार्ग": 8,
}


def _period_key(period) -> tuple:
    text = str(period)
    match = re.search(r"(20\d{2})", text)
    year = int(match.group(1)) if match else 9999
    low = text.lower()
    month = 99
    for name, number in _BS_MONTHS.items():
        if name in text or name in low:
            month = number
            break
    return year, month, text


def _scope_sensitivity(arc: pd.DataFrame) -> dict:
    d = arc[(arc["section"] == "country")
            & (arc["row_type"] == "detail")
            & (arc["gender"] == "total")].copy()
    d["period_bs"] = d["period_bs"].astype(str)
    periods = []
    for period, block in d.groupby("period_bs"):
        counts = {str(scope): _as_int(group["count"].sum())
                  for scope, group in block.groupby("scope")}
        docs = {str(scope): int(group["doc_id"].nunique())
                for scope, group in block.groupby("scope")}
        scopes = sorted(counts)
        if "final_approved" in counts:
            chosen = "final_approved"
        elif "month" in counts:
            chosen = "month"
        else:
            chosen = None
        all_scope_total = int(sum(counts.values()))
        chosen_count = counts.get(chosen, 0) if chosen else 0
        max_scope_gap = 0.0
        if chosen_count and len(counts) > 1:
            max_scope_gap = max(abs(v - chosen_count) / chosen_count * 100
                                for v in counts.values())
        multiple = len(scopes) > 1
        if multiple:
            scope_key = "+".join(scopes)
        else:
            scope_key = scopes[0] if scopes else ""
        periods.append({
            "period_bs": period,
            "scopes": scopes,
            "counts_by_scope": counts,
            "documents_by_scope": docs,
            "chosen_scope": chosen,
            "chosen_count": chosen_count,
            "all_scope_total": all_scope_total,
            "all_scope_overcount_vs_chosen_pct": _as_float(
                (all_scope_total - chosen_count) / chosen_count * 100, 3)
            if chosen_count else None,
            "multiple_scopes": multiple,
            "scope_set": scope_key,
            "max_alternative_gap_pct": _as_float(max_scope_gap, 3),
            "month_final_overlap": ("month" in counts
                                    and "final_approved" in counts),
        })
    periods.sort(key=lambda r: _period_key(r["period_bs"]))
    both = [r for r in periods if r["month_final_overlap"]]
    comparisons = []
    for row in both:
        month = row["counts_by_scope"]["month"]
        final = row["counts_by_scope"]["final_approved"]
        comparisons.append({
            "period_bs": row["period_bs"],
            "month": month,
            "final_approved": final,
            "difference_final_minus_month": final - month,
            "gap_pct": _as_float(abs(final - month) / month * 100, 3)
            if month else None,
            "scope_choice_matters": bool(
                month and abs(final - month) / month * 100 > SCOPE_GAP_TOLERANCE_PCT),
        })
    unique_sets = {}
    for row in periods:
        unique_sets[row["scope_set"]] = unique_sets.get(row["scope_set"], 0) + 1
    chosen_sum = int(sum(r["chosen_count"] for r in periods))
    all_scope_sum = int(sum(r["all_scope_total"] for r in periods))
    return {
        "definition": ("archive safe rows, country detail gender=total; "
                       "one period count per scope"),
        "rows": int(len(d)),
        "documents": int(d["doc_id"].nunique()),
        "periods": len(periods),
        "periods_with_both_month_and_final": len(both),
        "month_final_comparisons": comparisons,
        "scope_choice_matters": [r["period_bs"] for r in comparisons
                                 if r["scope_choice_matters"]],
        "unique_scope_sets": dict(sorted(unique_sets.items())),
        "multi_scope_period_count": int(sum(
            1 for r in periods if r["multiple_scopes"])),
        "deterministic_rule": ("choose final_approved; else month; "
                               "otherwise exclude from the monthly series"),
        "chosen_scope_count": len([r for r in periods if r["chosen_scope"]]),
        "chosen_sum": chosen_sum,
        "naive_all_scope_sum": all_scope_sum,
        "naive_scope_sum_overcount_pct": _as_float(
            (all_scope_sum - chosen_sum) / chosen_sum * 100, 3)
        if chosen_sum else None,
        "by_period": periods,
    }


def _leave_one_doc_out(frame: pd.DataFrame, *, entity_col: str = "name_canonical",
                       doc_col: str = "doc_id",
                       count_col: str = "count") -> dict:
    full = (frame.groupby(entity_col, dropna=False)[count_col].sum()
            .astype("float64"))
    full_total = float(full.sum())
    full_hhi = _hhi(full[full > 0])
    docs = []
    for doc, _ in frame.groupby(doc_col):
        rest = frame[frame[doc_col] != doc]
        values = (rest.groupby(entity_col, dropna=False)[count_col].sum()
                  .astype("float64"))
        total = float(values.sum())
        hhi = _hhi(values[values > 0])
        docs.append({
            "doc_id": str(doc),
            "rows": int(len(frame[frame[doc_col] == doc])),
            "total_without_doc": _as_int(total),
            "delta_total": _as_int(total - full_total),
            "delta_total_pct": _as_float((total - full_total) / full_total * 100, 4)
            if full_total else None,
            "hhi_without_doc": hhi,
            "delta_hhi": _as_float(hhi - full_hhi, 6),
        })
    docs.sort(key=lambda r: r["doc_id"])
    if docs:
        totals = [r["delta_total"] for r in docs]
        hhis = [r["delta_hhi"] for r in docs]
        summary = {
            "max_delta_total": max(totals),
            "min_delta_total": min(totals),
            "range_delta_total": max(totals) - min(totals),
            "max_abs_delta_total": max(abs(v) for v in totals),
            "max_delta_hhi": _as_float(max(hhis), 6),
            "min_delta_hhi": _as_float(min(hhis), 6),
            "range_delta_hhi": _as_float(max(hhis) - min(hhis), 6),
            "max_abs_delta_hhi": _as_float(max(abs(v) for v in hhis), 6),
        }
    else:
        summary = {}
    by_total = sorted(docs, key=lambda r: abs(r["delta_total"]), reverse=True)[:3]
    by_hhi = sorted(docs, key=lambda r: abs(r["delta_hhi"]), reverse=True)[:3]
    return {
        "full_total": _as_int(full_total),
        "full_hhi": full_hhi,
        "documents": len(docs),
        "summary": summary,
        "most_influential_by_total": by_total,
        "most_influential_by_hhi": by_hhi,
        "by_document": docs,
    }


def _leave_one_doc_out_by_fy(safe: pd.DataFrame) -> dict:
    base = safe[(safe["section"] == "country")
                & (safe["row_type"] == "detail")
                & (safe["gender"] == "total")
                & (safe["entity_resolved"])].copy()
    rows = []
    for fy, block in base.groupby("reconciled_fiscal_year"):
        docs = block.groupby("granularity")["doc_id"].nunique()
        month_docs = int(docs.get("month", 0))
        year_docs = int(docs.get("year", 0))
        if month_docs >= MIN_COMPLETE_MONTHS:
            basis, used, complete = "monthly", block[block["granularity"] == "month"], True
        elif year_docs >= 1:
            basis, used, complete = ("annual",
                                     block[block["granularity"] == "year"],
                                     year_docs >= 2)
        elif month_docs:
            basis, used, complete = ("monthly",
                                     block[block["granularity"] == "month"],
                                     False)
        else:
            continue
        result = _leave_one_doc_out(used)
        result.update({
            "fiscal_year": str(fy),
            "basis": basis,
            "annual_documents": year_docs,
            "month_documents": month_docs,
            "complete": bool(complete),
            "single_document": result["documents"] <= 1,
            "partial": str(fy) == PARTIAL_FY,
        })
        rows.append(result)
    rows.sort(key=lambda r: _fy_key(r["fiscal_year"]))
    complete = [r for r in rows if r["complete"]]
    aggregate = {}
    if complete:
        totals = [r["summary"]["max_abs_delta_total"] for r in complete]
        hhis = [r["summary"]["max_abs_delta_hhi"] for r in complete]
        aggregate = {
            "complete_fiscal_years": [r["fiscal_year"] for r in complete],
            "max_abs_delta_total": max(totals),
            "max_abs_delta_hhi": _as_float(max(hhis), 6),
        }
    return {
        "definition": ("country detail gender=total resolved rows; complete FY "
                       "uses 12 monthly documents, otherwise the annual document"),
        "complete": aggregate,
        "not_informative_fiscal_years": [r["fiscal_year"] for r in rows
                                          if not r["complete"]],
        "by_fiscal_year": rows,
    }


def _normalise_caption(text) -> str:
    value = str(text).lower()
    value = re.sub(r"(?:19|20)\d{2}\s*[/–—‑-]\s*\d{2,4}", " ", value)
    value = re.sub(r"\b(?:19|20)\d{2}\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _report_rank(report) -> tuple:
    years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", str(report))]
    return max(years) if years else 0, str(report)


def _caption_agnostic_diagnostic(df: pd.DataFrame, metric: str) -> dict:
    d = df[(df["metric"] == metric) & (df["unit"] == "count")].copy()
    if d.empty:
        return {"entity_years": 0, "duplicate_entity_years": 0}
    d["_gender"] = d["gender"].fillna("na").astype(str)
    d["_name"] = d["name"].fillna("").astype(str)
    d["_fy"] = d["fiscal_year"].fillna("").astype(str)
    keys = ["dimension", "unit", "year_basis", "_gender", "_name", "_fy"]
    grouped = d.groupby(keys, dropna=False).agg(
        rows=("count", "size"),
        reports=("report", "nunique"),
        captions=("caption", "nunique"),
    )
    return {
        "entity_years": int(len(grouped)),
        "duplicate_entity_years": int((grouped["rows"] > 1).sum()),
        "entity_years_with_multiple_reports": int((grouped["reports"] > 1).sum()),
        "entity_years_with_multiple_captions": int((grouped["captions"] > 1).sum()),
        "note": ("diagnostic only, ignoring caption/source table: many apparent "
                 "duplicates are different measures, so this is never summed"),
    }


def _dedupe_metric(df: pd.DataFrame, metric: str) -> dict:
    d = df[(df["metric"] == metric) & (df["unit"] == "count")].copy()
    if d.empty:
        return {"metric": metric, "groups": [], "duplicate_entity_years": 0}
    d["_caption"] = d["caption"].map(_normalise_caption)
    d["_gender"] = d["gender"].fillna("na").astype(str)
    ranks = {report: i for i, report in enumerate(
        sorted(d["report"].dropna().unique(), key=_report_rank))}
    d["_report_order"] = d["report"].map(ranks).fillna(-1).astype(int)
    d["_name"] = d["name"].fillna("").astype(str)
    d["_fy"] = d["fiscal_year"].fillna("").astype(str)
    groups = []
    for key, block in d.groupby(
            ["dimension", "unit", "year_basis", "_gender", "_caption"],
            dropna=False):
        block = block.sort_values(["_name", "_fy", "_report_order"])
        latest_order = (block.groupby(["_name", "_fy"])["_report_order"]
                        .transform("max"))
        chosen = block[block["_report_order"] == latest_order]
        entity_years = block.groupby(["_name", "_fy"]).size()
        reports_per_entity_year = (block.groupby(["_name", "_fy"])["report"]
                                   .nunique())
        dup = reports_per_entity_year[reports_per_entity_year > 1]
        same_report_rows = block.groupby(["_name", "_fy", "report"]).size()
        same_report_dup = same_report_rows[same_report_rows > 1]
        same_report_entity_years = (
            same_report_dup.reset_index().groupby(["_name", "_fy"]).ngroups
            if len(same_report_dup) else 0)
        naive = float(block["count"].sum())
        deduped = float(chosen["count"].sum())
        dimension, unit, year_basis, gender, caption = key
        groups.append({
            "compatible_key": "|".join([str(metric), str(dimension), str(unit),
                                        str(year_basis), str(gender),
                                        str(caption)]),
            "dimension": str(dimension),
            "unit": str(unit),
            "year_basis": str(year_basis),
            "gender": str(gender),
            "caption": str(caption),
            "reports": sorted(str(x) for x in block["report"].dropna().unique()),
            "rows": int(len(block)),
            "entity_years": int(len(entity_years)),
            "duplicate_entity_years": int(len(dup)),
            "same_report_duplicate_entity_years": int(same_report_entity_years),
            "duplicate_rows_dropped": int(len(block) - len(chosen)),
            "naive_sum": _as_int(naive),
            "deduplicated_sum": _as_int(deduped),
            "difference_naive_minus_deduped": _as_int(naive - deduped),
            "counts_non_negative": bool((block["count"].fillna(0) >= 0).all()),
        })
    groups.sort(key=lambda r: r["naive_sum"], reverse=True)
    return {
        "metric": metric,
        "groups": groups,
        "duplicate_entity_years": int(sum(
            r["duplicate_entity_years"] for r in groups)),
        "groups_with_duplicates": int(sum(
            1 for r in groups if r["duplicate_entity_years"])),
        "caption_agnostic_diagnostic": _caption_agnostic_diagnostic(df, metric),
    }


def _series_dedupe(ser: pd.DataFrame) -> dict:
    labour = _dedupe_metric(ser, "labour_approval")
    deaths = _dedupe_metric(ser, "deaths")
    deaths_examples = []
    for group in deaths["groups"]:
        if not group["duplicate_entity_years"]:
            continue
        deaths_examples.append({
            "compatible_key": group["compatible_key"],
            "duplicate_entity_years": group["duplicate_entity_years"],
            "naive_sum": group["naive_sum"],
            "deduplicated_sum": group["deduplicated_sum"],
            "difference_naive_minus_deduped":
                group["difference_naive_minus_deduped"],
        })
    deaths_examples.sort(key=lambda r: r["duplicate_entity_years"], reverse=True)
    return {
        "dedupe_rule": (
            "partition by metric+dimension+unit+year_basis+gender+normalised "
            "caption; entity-year = (name, fiscal_year); keep the row from the "
            "report with the latest four-digit year, preserving only counts"),
        "unit_filter": "count",
        "labour_approval": labour,
        "deaths": {
            **deaths,
            "duplicate_entity_year_examples": deaths_examples[:10],
            "chosen_rule": "latest report per entity-year within a compatible key",
        },
    }


def _meta() -> dict:
    return {
        "generated_for": "Phase 1 pattern-book robustness",
        "latest_fiscal_year": LATEST_FY,
        "partial_fiscal_year": PARTIAL_FY,
        "definitions": {
            "safe_panel": "analysis_safe == true",
            "permissive_panel": "analysis_safe_permissive == true",
            "single_basis": ("for each fiscal year keep annual rows when "
                             "prefer=annual, monthly rows when prefer=month"),
            "annual_total": "sum of country detail, gender=total, resolved entities",
            "hhi": "sum of squared destination shares on a 0-1 scale",
            "top_destination_share": "largest destination count / total",
            "female_share": "female / (male + female) from country gender rows",
            "complete_monthly": f">= {MIN_COMPLETE_MONTHS} monthly documents",
            "archive_scope_rule": ("final_approved, else month, else excluded; "
                                   "scopes are never summed"),
            "series_dedupe": ("latest report per entity-year inside a compatible "
                              "series partition; incompatible dimensions, units, "
                              "genders and captions are never merged"),
        },
        "thresholds": {
            "annual_monthly_tolerance_fraction": audit.ANNUAL_GAP_TOLERANCE,
            "complete_months": MIN_COMPLETE_MONTHS,
            "archive_scope_gap_tolerance_pct": SCOPE_GAP_TOLERANCE_PCT,
            "top_n": TOP_N,
        },
        "limitations": [
            "2083/84 is partial and has only monthly documents.",
            "2081/82 has three monthly documents, so its monthly total is not a validation.",
            "2082/83 is the only fiscal year with complete monthly and annual overlap.",
            "The archive has no period containing both month and final_approved scopes; "
            "only multi-scope periods within the same family are observed.",
            "Archive and canonical panels are separate; their totals are not joined.",
            "Series tables use different units, genders and captions; only compatible "
            "partitions are de-duplicated and no cross-dimension total is produced.",
            "Leave-one-document-out is only informative when a fiscal year has more than "
            "one document on the chosen basis; single annual documents are flagged.",
            "These checks are descriptive and do not identify causal effects.",
        ],
    }


def build() -> dict:
    full = load_panel(safe=False)
    safe = full[full["analysis_safe"]].copy()
    permissive = full[full["analysis_safe_permissive"]].copy()
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meta": _meta(),
        "safe_vs_permissive": _safe_vs_permissive(full, safe, permissive),
        "annual_monthly": _annual_monthly(safe),
        "basis_sensitivity": _basis_sensitivity(safe),
        "archive_scope": _scope_sensitivity(archive_panel(safe=True)),
        "leave_one_doc_out": _leave_one_doc_out_by_fy(safe),
        "series_dedupe": _series_dedupe(series()),
    }
