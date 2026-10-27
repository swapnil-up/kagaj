"""Render the Phase 1 migration pattern book.

Outputs are deliberately self-contained so they can be opened, screenshotted,
or committed without a running notebook.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import figures
from .audit import OUTPUT_DIR, _esc, _table


def _img(image: str, alt: str) -> str:
    if not image:
        return ""
    return f'<img src="data:image/png;base64,{image}" alt="{_esc(alt)}">'


def _fy_label(row: dict) -> str:
    suffix = " (partial)" if row.get("partial") else ""
    return f"{row['fiscal_year']}{suffix}"


def _md_table(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(v) for v in row) + " |" for row in rows]
    return out + [""]


def _write_markdown(report: dict, path: Path) -> None:
    annual = report["annual"]
    latest = annual[-1] if annual else {}
    rec = report["destinations"]["recovery"]
    malaysia = next((r for r in rec if r["country"] == "Malaysia"), None)
    lines = [
        "# Migration pattern book — Phase 1 findings", "",
        f"Generated: {report['generated_at']}", "",
        "## Basis", "",
        f"- Safe panel: {report['basis']['rows']:,} rows from "
        f"{report['basis']['documents']} documents.",
        f"- Fiscal years: {', '.join(report['basis']['fiscal_years'])}.",
        f"- Base year for indices: {report['basis']['base_fy']}; "
        f"latest complete year: {report['basis']['latest_fy']}.",
        "- All results use one granularity per year.",
        "- Full caveats: `docs/migration-data-issues.md`.", "",
        "## Denominators and coverage", "",
    ]
    outcomes = report["outcomes"]
    lines += _md_table(
        ["FY", "total verified", "deployment", "reviewed", "legalization",
         "new_entry", "reviewed share", "docs"],
        [[r["fiscal_year"] + (" (partial)" if r["partial"] else ""),
          f"{r['total_verified']:,}", f"{r['deployment_verified']:,}",
          f"{r['reviewed_channels']:,}", f"{r['legalization']:,}",
          f"{r['new_entry']:,}", f"{r['reviewed_share_of_total_pct']:.1f}%",
          r["documents"]]
         for r in outcomes["coverage"]["rows"]])
    lines += [
        "The reviewed-channel series is **not** a total-approval trend: its",
        "coverage changes from ~86% in FY2080/81 to ~100% in FY2081/82.",
        "Use `deployment_verified` for long-run volume and",
        "`modern_consistent` for channel comparisons.", "",
    ]
    gap = outcomes.get("gap_fill")
    if gap:
        lines += [
            "**FY2075/76 gap-fill.** Only `report2020_annex_X` covers this year,",
            "so it is not in the verified coverage table. It has 2 known Qatar",
            "arithmetic errors; use it as a flagged sensitivity only.", "",
            "| measure | value |",
            "|---|---:|",
            f"| total unverified | {gap['total_unverified']:,} |",
            f"| deployment (excl. legalization) | {gap['deployment_unverified']:,} |",
            f"| legalization | {gap['legalization']:,} |",
            f"| male + female component total | {gap['total_from_male_female']:,} |",
            f"| gender-sum minus printed total | {gap['gender_total_difference']:+,} |",
            "",
        ]
        lines += ["## Country growth under alternative denominators", ""]
    else:
        lines += ["## Country growth under alternative denominators", ""]
    lines += _md_table(
        ["country", "base deployment", "latest deployment", "deployment growth",
         "reviewed growth", "gap", "base reviewed share"],
        [[r["country"], f"{r['base_deployment_verified']:,}",
          f"{r['latest_deployment_verified']:,}",
          f"{r['deployment_growth_pct']:+.1f}%"
          if r["deployment_growth_pct"] is not None else "–",
          f"{r['reviewed_growth_pct']:+.1f}%"
          if r["reviewed_growth_pct"] is not None else "–",
          f"{r['reviewed_minus_deployment_growth_pp']:+.1f} pp"
          if r["reviewed_minus_deployment_growth_pp"] is not None else "–",
          f"{r['base_reviewed_share_pct']:.1f}%"
          if r["base_reviewed_share_pct"] is not None else "–"]
         for r in outcomes["country_growth"]])
    lines += ["Flagged denominator-sensitive series:", ""]
    lines += _md_table(
        ["country", "base deployment", "latest deployment", "deployment growth",
         "reviewed growth", "gap", "small base", "sign flip"],
        [[r["country"], f"{r['base_deployment_verified']:,}",
          f"{r['latest_deployment_verified']:,}",
          f"{r['deployment_growth_pct']:+.1f}%"
          if r["deployment_growth_pct"] is not None else "–",
          f"{r['reviewed_growth_pct']:+.1f}%"
          if r["reviewed_growth_pct"] is not None else "–",
          f"{r['reviewed_minus_deployment_growth_pp']:+.1f} pp"
          if r["reviewed_minus_deployment_growth_pp"] is not None else "–",
          "yes" if r["small_base"] else "",
          "yes" if r["sign_flip"] else ""]
         for r in outcomes["suspect_series"]["rows"][:20]])
    recon = outcomes["annual_monthly_reconciliation"]
    lines += [
        "## Annual vs monthly reconciliation", "",
        f"FY{recon['fiscal_year']}: {recon['exact_pairs']}/{recon['pairs']} "
        f"country × channel pairs match exactly; total absolute difference is "
        f"{recon['total_abs_difference']} approvals.", "",
        "## Ranked patterns", "",
    ]
    for item in report["hypotheses"]:
        lines += [
            f"### {item['rank']}. {item['label']}", "",
            f"**Pattern.** {item['pattern']}", "",
            f"**Question.** {item['question']}", "",
            f"**Data needed.** {item['data_needed']}", "",
            f"**Risk.** {item['risk']}", "",
        ]
    lines += ["## Reviewed-channel annual totals", "",
              "| FY | approvals | destinations | top 5 | top 10 | HHI | largest |",
              "|---|---:|---:|---:|---:|---:|---|"]
    lines += [f"| {_fy_label(r)} | {r['count']:,} | {r['n_entities']} | "
              f"{r['top5_share_pct']:.1f}% | {r['top10_share_pct']:.1f}% | "
              f"{r['hhi']:.3f} | {r['top_entity']} |" for r in annual]
    lines += ["", "## Destination turnover and decomposition", ""]
    dd = report["deep_destinations"]
    turnover = dd["turnover"]["base_to_latest"]
    lines += [f"Active destinations: {turnover['active_pre']} in "
              f"{turnover['from']} → {turnover['active_post']} in "
              f"{turnover['to']}. Top-10 Jaccard = {turnover['jaccard']:.3f}.", ""]
    lines += _md_table(
        ["from", "to", "Spearman", "top-10 overlap", "top-10 churn"],
        [[r["from"], r["to"],
          f"{r['spearman']:.3f}" if r["spearman"] is not None else "–",
          r["top10_overlap"], r["top10_churn"]]
         for r in dd["rank_stability"][-6:]])
    lines += ["New destinations, base → latest:", ""]
    lines += _md_table(["country", "latest approvals"],
                       [[r["country"], f"{r['count']:,}"]
                        for r in turnover["new"][:10]])
    lines += ["Recovery contributions:", ""]
    lines += _md_table(
        ["country", "status", "pre", "latest", "contribution"],
        [[r["country"], r["status"], f"{r['pre']:,}", f"{r['latest']:,}",
          f"{r['contribution']:+,}"]
         for r in (dd["recovery"]["top_positive"][:6]
                   + dd["recovery"]["top_negative"][:4])])
    lines += ["Most volatile destinations:", ""]
    lines += _md_table(
        ["country", "total", "CV", "max drawdown"],
        [[r["country"], f"{r['total']:,}", f"{r['cv']:.2f}",
          f"{r['max_drawdown_pct']:.0f}%"]
         for r in dd["volatility"]["destinations"][:8]])

    lines += ["## What explains the female shift?", ""]
    gc = report["gender_channel"]
    fs = gc["female_shift_share"]
    lines += _md_table(
        ["component", "contribution"],
        [["within-destination", f"{fs['within_destination_pp']:+.2f} pp"],
         ["destination composition", f"{fs['destination_composition_pp']:+.2f} pp"],
         ["interaction residual", f"{fs['interaction_residual_pp']:+.2f} pp"]])
    lines += ["Destination-mix contributors:", ""]
    lines += _md_table(
        ["country", "contribution", "base female share", "latest female share"],
        [[r["country"], f"{r['contribution_pp']:+.2f} pp",
          f"{r['base_female_share_pct']:.1f}%",
          f"{r['latest_female_share_pct']:.1f}%"]
         for r in fs["composition_contributors"][:8]])
    lines += ["Female share by channel:", ""]
    lines += _md_table(
        ["channel", "latest female share", "change", "latest total"],
        [[r["channel"],
          f"{r['latest_female_share_pct']:.1f}%" if r["latest_female_share_pct"] is not None else "–",
          f"{r['change_pp']:+.1f} pp" if r["change_pp"] is not None else "–",
          f"{r['latest_total']:,}"]
         for r in gc["female_by_channel"]["channels"]])

    lines += ["## Country-level gender deep dive", ""]
    gcountry = report["gender_country"]
    lines += _md_table(
        ["FY", "female", "male", "female share", "reconciles"],
        [[r["fiscal_year"], f"{r['female']:,}", f"{r['male']:,}",
          f"{r['female_share_pct']:.2f}%",
          "yes" if r["reconciles_with_country_year"] else "no"]
         for r in gcountry["annual"] if r["complete_year"]])
    lines += ["Highest female shares (latest):", ""]
    lines += _md_table(
        ["country", "latest total", "female share"],
        [[r["country"], f"{r['latest_total']:,}",
          f"{r['latest_female_share_pct']:.1f}%"]
         for r in gcountry["country_ranks"]["by_latest_female_share"][:10]])
    lines += ["Largest female-share increases:", ""]
    lines += _md_table(
        ["country", "latest total", "change"],
        [[r["country"], f"{r['latest_total']:,}",
          f"{r['female_share_change_pp']:+.1f} pp"]
         for r in gcountry["country_ranks"]["by_female_share_change"][:10]])
    conv = gcountry["convergence"]["default"]
    lines += _md_table(
        ["diagnostic", "value"],
        [["convergence slope", f"{conv['slope_pp_per_initial_pp']:.3f} pp per pp"],
         ["correlation / R²", f"{conv['correlation']:.3f} / {conv['r_squared']:.3f}"],
         ["low-initial half", f"{conv['low_initial_half_mean_change_pp']:+.2f} pp"],
         ["high-initial half", f"{conv['high_initial_half_mean_change_pp']:+.2f} pp"]])
    lines += ["Large-volume female/male divergence:", ""]
    lines += _md_table(
        ["country", "latest total", "female growth", "male growth", "gap"],
        [[r["country"], f"{r['latest_total']:,}",
          f"{r['female_growth_pct']:+.1f}%", f"{r['male_growth_pct']:+.1f}%",
          f"{r['female_minus_male_growth_pp']:+.1f} pp"]
         for r in gcountry["growth_divergence"]["large_volume_divergences"]])

    lines += ["## New vs re-entry line", ""]
    rent = report["reentry"]
    lines += _md_table(
        ["FY", "total", "new", "re-entry", "new share", "re-entry share"],
        [[r["fiscal_year"], f"{r['total']:,}",
          f"{r['individual_new']:,}" if r["new_reported"] else "–",
          f"{r['individual_reentry']:,}" if r["reentry_reported"] else "–",
          f"{r['new_share_pct']:.1f}%" if r["new_share_pct"] is not None else "–",
          f"{r['reentry_share_pct']:.1f}%" if r["reentry_share_pct"] is not None else "–"]
         for r in rent["annual"] if r["fiscal_year"] != "2083/84"])
    lines += ["Comparable window 2081/82 → 2082/83:", ""]
    lines += _md_table(
        ["channel", "base", "latest", "change", "growth"],
        [[r["channel"], f"{r['base_count']:,}", f"{r['latest_count']:,}",
          f"{r['change']:+,}",
          f"{r['growth_pct']:+.1f}%" if r["growth_pct"] is not None else "–"]
         for r in rent["comparable_window"]["channels"]])
    lines += ["Highest re-entry orientation (≥1,000 latest approvals):", ""]
    lines += _md_table(
        ["country", "latest total", "re-entry share of all", "of individual"],
        [[r["country"], f"{r['latest_total']:,}", f"{r['reentry_share_pct']:.1f}%",
          f"{r['reentry_share_of_individual_pct']:.1f}%"]
         for r in rent["reentry_orientation"]["highest_reentry_share"][:8]])
    assoc = rent["association"]
    lines += _md_table(
        ["association", "n", "Pearson", "Spearman"],
        [["total growth vs latest reentry share",
          assoc["total_growth_vs_latest_reentry_share"]["n"],
          f"{assoc['total_growth_vs_latest_reentry_share']['pearson']:.3f}",
          f"{assoc['total_growth_vs_latest_reentry_share']['spearman']:.3f}"],
         ["new growth vs comparable reentry share",
          assoc["new_growth_vs_comparable_reentry_share"]["n"],
          f"{assoc['new_growth_vs_comparable_reentry_share']['pearson']:.3f}",
          f"{assoc['new_growth_vs_comparable_reentry_share']['spearman']:.3f}"]])

    lines += ["## Re-entry × gender", ""]
    rg = report["reentry_gender"]
    latest_summary = rg["latest_summary"]
    lines += [f"Latest female share: new {latest_summary['new_female_share_pct']:.2f}% "
              f"vs re-entry {latest_summary['reentry_female_share_pct']:.2f}%; "
              f"gap {latest_summary['new_to_reentry_female_gap_pp']:+.2f} pp.", ""]
    lines += _md_table(
        ["FY", "new female share", "re-entry female share", "gap"],
        [[r["fiscal_year"],
          f"{r['channels']['individual_new']['female_share_pct']:.1f}%"
          if r["channels"]["individual_new"]["reported"] else "–",
          f"{r['channels']['individual_reentry']['female_share_pct']:.1f}%"
          if r["channels"]["individual_reentry"]["reported"] else "–",
          f"{r['new_to_reentry_female_gap_pp']:+.1f} pp"
          if r["new_to_reentry_female_gap_pp"] is not None else "–"]
         for r in rg["annual"] if r["fiscal_year"] != "2083/84"])
    lines += ["Largest new-minus-re-entry female gaps:", ""]
    lines += _md_table(
        ["country", "latest total", "new female", "re-entry female", "gap"],
        [[r["country"], f"{r['latest_total']:,}",
          f"{r['new_female_share_pct']:.1f}%", f"{r['reentry_female_share_pct']:.1f}%",
          f"{r['new_to_reentry_female_gap_pp']:+.1f} pp"]
         for r in sorted(rg["country_table"]["destinations"],
                         key=lambda r: abs(r["new_to_reentry_female_gap_pp"]),
                         reverse=True)[:10]])
    decomp = rg["decomposition"]["comparable_window"]
    lines += ["Female-share decomposition, comparable window:", ""]
    rows = []
    for label, key in (("new + re-entry", "new_reentry"),
                       ("all four channels", "four_channel")):
        d = decomp[key]
        rows.append([label, f"{d['aggregate_change_pp']:+.3f}",
                     f"{d['within_channel_pp']:+.3f}",
                     f"{d['channel_composition_pp']:+.3f}",
                     f"{d['interaction_residual_pp']:+.3f}"])
    lines += _md_table(["window", "aggregate", "within", "composition",
                        "interaction"], rows)

    lines += ["## Destination × channel", ""]
    lines += _md_table(
        ["country", "dominant", "G2G", "new", "re-entry", "agency"],
        [[r["country"], r["dominant_channel"],
          f"{r['channels']['g2g']['share_pct']:.1f}%",
          f"{r['channels']['individual_new']['share_pct']:.1f}%",
          f"{r['channels']['individual_reentry']['share_pct']:.1f}%",
          f"{r['channels']['recruiting_agency']['share_pct']:.1f}%"]
         for r in gc["channel_composition_by_destination"]["top_destinations"]])
    lines += ["Largest re-entry volumes:", ""]
    lines += _md_table(
        ["country", "latest re-entry", "share of destination", "change"],
        [[r["country"], f"{r['latest_reentry']:,}",
          f"{r['latest_reentry_share_pct']:.1f}%", f"{r['change_pp']:+.1f} pp"]
         for r in gc["reentry_by_destination"]["top_volume"][:10]])

    lines += ["## District mobility and provincial shift", ""]
    dist = report["deep_districts"]
    beta = dist["convergence"]["beta"]
    mob = dist["convergence"]["mobility"]
    lines += _md_table(
        ["diagnostic", "value"],
        [["beta slope", f"{beta['slope']:.3f}"],
         ["beta p-value", f"{beta['p_value']:.4f}"],
         ["sigma CV first→latest",
          f"{dist['convergence']['sigma'][0]['cv_pct']:.1f}% → "
          f"{dist['convergence']['sigma'][-1]['cv_pct']:.1f}%"],
         ["rank mobility", f"{mob['mobility']:.3f}"]])
    lines += ["Largest district contributions to the national change:", ""]
    lines += _md_table(
        ["district", "initial", "latest", "change", "contribution"],
        [[r["district"], f"{r['initial_count']:,}", f"{r['latest_count']:,}",
          f"{r['change']:+,}", f"{r['contribution_pct']:+.2f}%"]
         for r in (dist["contributions"]["top_positive"][:8]
                   + dist["contributions"]["top_negative"][:4])])
    lines += ["Provincial share change:", ""]
    lines += _md_table(
        ["province", "initial share", "latest share", "change", "growth"],
        [[r["province"].title(), f"{r['initial_share_pct']:.1f}%",
          f"{r['latest_share_pct']:.1f}%",
          f"{r['share_change_pp']:+.1f} pp", f"{r['growth_pct']:+.1f}%"]
         for r in sorted(dist["provinces"]["change"],
                         key=lambda r: r["share_change_pp"], reverse=True)])

    lines += ["## Seasonality and structural breaks", ""]
    ts = report["time_series"]
    lines += ["Modern monthly coverage:", ""]
    lines += _md_table(
        ["FY", "docs", "months", "monthly sum", "annual", "gap", "complete"],
        [[r["fiscal_year"], r["n_docs"], r["distinct_months"],
          f"{r['monthly_sum']:,}",
          f"{r['annual_total']:,}" if r["annual_total"] is not None else "–",
          f"{r['gap_pct']:.3f}%" if r["gap_pct"] is not None else "–",
          "yes" if r["complete_monthly"] else "no"]
         for r in ts["modern_monthly_coverage"]["fiscal_years"]])
    lines += ["Modern seasonal index (100 = average month):", ""]
    lines += _md_table(
        ["BS month", "approvals", "index"],
        [[r["bs_month"], f"{r['count']:,}", f"{r['index']:.1f}"]
         for r in ts["modern_seasonality"]["monthly"]])
    lines += ["Best single break per series:", ""]
    break_rows = []
    for key, label in (("annual_approvals", "Annual approvals"),
                       ("destination_hhi", "Destination HHI")):
        best = ts["structural_breaks"][key]["best"]
        break_rows.append([label, best["split_after"],
                           f"{best['difference_pct']:+.1f}%",
                           f"{best['sse_reduction']:.3f}"])
    lines += _md_table(["series", "split after", "difference", "SSE reduction"],
                       break_rows)

    lines += ["## Robustness", ""]
    rb = report["robustness"]
    safe_annual = {r["fiscal_year"]: r for r in rb["safe_vs_permissive"]["safe"]["annual"]}
    perm_annual = {r["fiscal_year"]: r for r in rb["safe_vs_permissive"]["permissive"]["annual"]}
    delta = rb["safe_vs_permissive"]["delta_permissive_minus_safe"]
    lines += ["Safe vs permissive totals:", ""]
    lines += _md_table(
        ["FY", "safe", "permissive", "delta", "delta % of safe"],
        [[fy, f"{safe_annual[fy]['total']:,}", f"{perm_annual[fy]['total']:,}",
          f"{delta['annual_total_by_fiscal_year'].get(fy, 0):+,}",
          f"{delta['annual_total_share_of_safe_pct'].get(fy, 0):.2f}%"]
         for fy in safe_annual if fy in perm_annual])
    latest_lodo = next((r for r in rb["leave_one_doc_out"]["by_fiscal_year"]
                        if r["fiscal_year"] == report["basis"]["latest_fy"]), None)
    if latest_lodo:
        lines += [f"Most influential documents in {report['basis']['latest_fy']}:", ""]
        lines += _md_table(
            ["doc", "total without doc", "delta total", "delta %"],
            [[r["doc_id"], f"{r['total_without_doc']:,}",
              f"{r['delta_total']:+,}", f"{r['delta_total_pct']:+.2f}%"]
             for r in latest_lodo["most_influential_by_total"][:6]])

    lines += ["", "## Watchlist", ""]
    if malaysia:
        lines.append(f"- Malaysia: {malaysia['growth_pct']:+.1f}% vs "
                     f"{report['basis']['base_fy']}.")
    lines.append(f"- Latest annual total: {latest.get('count', 0):,} "
                 "(2083/84 is partial, not a level comparison).")
    lines += ["- See the HTML pattern book for all figures and full tables.", ""]
    path.write_text("\n".join(lines) + "\n")


def write_outputs(report: dict, outdir: str | Path | None = None) -> dict:
    out = Path(outdir) if outdir else OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "patterns.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    _write_markdown(report, out / "findings.md")

    annual = report["annual"]
    latest = annual[-1] if annual else {}
    problems = report["problems"]
    critical = sum(1 for i in problems if i["severity"] == "critical")
    warning = sum(1 for i in problems if i["severity"] == "warning")

    fig_annual = figures.annual_volume(annual)
    fig_conc = figures.concentration(annual)
    fig_index = figures.destination_index(report["destinations"]["index"])
    fig_recovery = figures.recovery_scatter(report["destinations"]["recovery"])
    fig_female = figures.female_trend(report["female"])
    fig_female_dest = figures.female_destinations(report["female"]["latest"])
    fig_channels = figures.channel_mix(report["channels"])
    fig_district = figures.district_concentration(
        report["districts"]["concentration"])
    fig_converge = figures.district_convergence(
        report["districts"]["convergence"]["points"],
        report["districts"]["convergence"].get("spearman"))
    fig_month = figures.monthly_line(
        report["monthly"]["modern"], "Modern monthly approvals")
    fig_archive = figures.archive_line(report["monthly"]["archive"])
    fig_deaths = figures.deaths_line(report["series"]["deaths"])

    deep_dest = report["deep_destinations"]
    gender_channel = report["gender_channel"]
    deep_dist = report["deep_districts"]
    time_series = report["time_series"]
    robustness = report["robustness"]

    fig_rank_heat = figures.destination_rank_heatmap(deep_dest["rank_panel"])
    fig_recovery_water = figures.recovery_waterfall(deep_dest["recovery"])
    fig_female_shift = figures.female_shift_waterfall(
        gender_channel["female_shift_share"])
    fig_female_dumbbell = figures.destination_female_dumbbell(
        gender_channel["female_share_by_destination"])
    fig_channel_dest = figures.channel_destination_stack(
        gender_channel["channel_composition_by_destination"])
    fig_transition = figures.district_transition(deep_dist["transitions"])
    fig_province = figures.province_change(deep_dist["provinces"]["change"])
    fig_modern_season = figures.modern_seasonality(
        time_series["modern_seasonality"])
    fig_archive_heat = figures.archive_coverage_heatmap(
        time_series["archive_monthly_coverage"])
    fig_breaks = figures.break_scan(time_series["structural_breaks"])
    fig_deaths_rate = figures.deaths_rate(time_series["deaths"]["matched"])
    fig_permissive = figures.safe_permissive_delta(
        robustness["safe_vs_permissive"]["delta_permissive_minus_safe"])

    reentry = report["reentry"]
    gender_country = report["gender_country"]
    reentry_gender = report["reentry_gender"]
    outcomes = report["outcomes"]

    fig_outcome_volume = figures.outcome_volume(outcomes["coverage"]["rows"])
    fig_reviewed_share = figures.reviewed_share(outcomes["coverage"]["rows"])
    fig_growth_denom = figures.growth_denominator_scatter(
        outcomes["country_growth"])
    fig_deployment_recovery = figures.deployment_recovery_scatter(
        outcomes["country_growth"])

    fig_new_reentry = figures.new_reentry_trend(reentry["annual"])
    fig_new_reentry_scatter = figures.new_reentry_country_scatter(
        reentry["country_base_latest"]["destinations"])
    fig_new_reentry_top = figures.new_reentry_top_trajectories(
        reentry["top_destinations"])
    fig_gender_country_dumbbell = figures.gender_country_dumbbell(
        gender_country["country_deep"])
    fig_gender_country_conv = figures.gender_country_convergence(
        gender_country["convergence"]["default"])
    fig_gender_channel_gap = figures.gender_channel_gap_trend(
        reentry_gender["annual"])
    fig_reentry_gender_gap = figures.reentry_gender_gap_country(
        reentry_gender["country_table"])
    fig_reentry_gender_decomp = figures.reentry_gender_decomposition(
        reentry_gender["decomposition"]["comparable_window"])

    problem_rows = [[i["severity"], i["code"], i["message"]] for i in problems]
    annual_rows = [[_fy_label(r), f"{r['count']:,}", r["n_entities"],
                    f"{r['top5_share_pct']:.1f}%", f"{r['top10_share_pct']:.1f}%",
                    f"{r['hhi']:.3f}", r["top_entity"]] for r in annual]
    recovery_rows = [[r["country"], f"{r['pre']:,}", f"{r['latest']:,}",
                      f"{r['pre_share_pct']:.1f}%", f"{r['growth_pct']:+.1f}%",
                      "yes" if r["recovered"] else "no"]
                     for r in report["destinations"]["recovery"]]
    entry_rows = [[r["entity"], f"{r['first_count']:,}",
                   f"{r['last_count']:,}"] for r in report["destinations"]["entries"]]
    exit_rows = [[r["entity"], f"{r['first_count']:,}",
                  f"{r['last_count']:,}"] for r in report["destinations"]["exits"]]
    female_rows = [[r["entity"], f"{r['female_share_pct']:.1f}%",
                    f"{r['total']:,}"] for r in report["female"]["latest"]]
    female_change_rows = [[r["country"], f"{r['pre_share_pct']:.1f}%",
                           f"{r['latest_share_pct']:.1f}%",
                           f"{r['change_pp']:+.1f} pp", f"{r['latest_total']:,}"]
                          for r in report["female"]["change"]]
    channel_rows = [[_fy_label(r), f"{r['count']:,}"] +
                    [f"{r['channels'].get(c, 0):.1f}%" for c in report["channels"]["columns"]]
                    for r in report["channels"]["by_year"]]
    reentry_rows = [[r["fiscal_year"], f"{r['total']:,}",
                     f"{r['reentry']:,}", f"{r['reentry_share_pct']:.1f}%"]
                    for r in report["channels"]["reentry"]]
    district_rows = [[r["district"], f"{r['count']:,}"]
                     for r in report["districts"]["top_latest"]]
    convergence_rows = [[p["district"], f"{p['initial_share_pct']:.2f}%",
                         f"{p['growth_pct']:+.1f}%", f"{p['latest_count']:,}"]
                        for p in sorted(
                            report["districts"]["convergence"]["points"],
                            key=lambda x: x["initial_share_pct"], reverse=True)[:15]]
    monthly_rows = [[r["start"], r["fiscal_year"], f"{r['count']:,}"]
                    for r in report["monthly"]["modern"]]
    archive_rows = [[r["period_bs"], r["scope"], f"{r['count']:,}"]
                    for r in report["monthly"]["archive"]]
    death_rows = [[r["fiscal_year"], f"{r['deaths']:,}"]
                  for r in report["series"]["deaths"]]
    hypothesis_rows = [[h["rank"], h["label"], h["pattern"], h["question"],
                        h["data_needed"], h["risk"]]
                       for h in report["hypotheses"]]

    rank_stability_rows = [[r["from"], r["to"], r["n_common_above_min"],
                            f"{r['spearman']:.3f}" if r["spearman"] is not None else "–",
                            r["top10_overlap"], r["top10_churn"]]
                           for r in deep_dest["rank_stability"]]
    turnover_new_rows = [[r["country"], f"{r['count']:,}"]
                         for r in deep_dest["turnover"]["base_to_latest"]["new"][:20]]
    recovery_contrib_rows = [[r["country"], r["status"], f"{r['pre']:,}",
                              f"{r['latest']:,}", f"{r['contribution']:+,}",
                              f"{r['contribution_share_pct']:+.1f}%"]
                             for r in (deep_dest["recovery"]["top_positive"][:10]
                                       + deep_dest["recovery"]["top_negative"][:5])]
    conc_contrib_rows = [[r["country"], f"{r['pre_share_pct']:.1f}%",
                          f"{r['latest_share_pct']:.1f}%",
                          f"{r['share_change_pp']:+.1f} pp",
                          f"{r['squared_share_contribution']:+.4f}"]
                         for r in (deep_dest["concentration"]["top_positive"][:8]
                                   + deep_dest["concentration"]["top_negative"][:4])]
    destination_vol_rows = [[r["country"], f"{r['total']:,}", f"{r['cv']:.2f}",
                             f"{r['max_drawdown_pct']:.0f}%",
                             f"{r['latest_share_pct']:.2f}%"]
                            for r in deep_dest["volatility"]["destinations"][:12]]
    shift_component_rows = [["within-destination", f"{gender_channel['female_shift_share']['within_destination_pp']:+.2f} pp"],
                            ["destination composition", f"{gender_channel['female_shift_share']['destination_composition_pp']:+.2f} pp"],
                            ["interaction residual", f"{gender_channel['female_shift_share']['interaction_residual_pp']:+.2f} pp"]]
    shift_contrib_rows = [[r["country"], f"{r['contribution_pp']:+.2f} pp",
                           f"{r['base_female_share_pct']:.1f}%",
                           f"{r['latest_female_share_pct']:.1f}%"]
                          for r in gender_channel["female_shift_share"]["composition_contributors"][:10]]
    female_channel_rows = [[r["channel"], f"{r['latest_female_share_pct']:.1f}%"
                            if r["latest_female_share_pct"] is not None else "–",
                            f"{r['change_pp']:+.1f} pp" if r["change_pp"] is not None else "–",
                            f"{r['latest_total']:,}"]
                           for r in gender_channel["female_by_channel"]["channels"]]
    channel_dest_rows = [[r["country"], r["dominant_channel"],
                          f"{r['channels']['g2g']['share_pct']:.1f}%",
                          f"{r['channels']['individual_new']['share_pct']:.1f}%",
                          f"{r['channels']['individual_reentry']['share_pct']:.1f}%",
                          f"{r['channels']['recruiting_agency']['share_pct']:.1f}%",
                          "yes" if r["agency_dependent"] else "",
                          "yes" if r["g2g_dependent"] else ""]
                         for r in gender_channel["channel_composition_by_destination"]["top_destinations"]]
    reentry_dest_rows = [[r["country"], f"{r['latest_reentry']:,}",
                          f"{r['latest_reentry_share_pct']:.1f}%",
                          f"{r['change_pp']:+.1f} pp"]
                         for r in gender_channel["reentry_by_destination"]["top_volume"][:15]]
    channel_growth_rows = [[r["channel"], f"{r['base_count']:,}",
                            f"{r['latest_count']:,}", f"{r['change']:+,}",
                            f"{r['growth_pct']:+.1f}%" if r["growth_pct"] is not None else "–",
                            f"{r['contribution_to_total_growth_pct']:+.1f}%"]
                           for r in gender_channel["channel_growth"]["comparable_window"]["channels"]]
    beta = deep_dist["convergence"]["beta"]
    mobility = deep_dist["convergence"]["mobility"]
    convergence_summary = [["beta slope", f"{beta['slope']:.3f}"],
                           ["beta SE / p", f"{beta['stderr']:.3f} / {beta['p_value']:.4f}"],
                           ["beta R² / n", f"{beta['r_squared']:.2f} / {beta['n']}"],
                           ["sigma CV first→latest", f"{deep_dist['convergence']['sigma'][0]['cv_pct']:.1f}% → {deep_dist['convergence']['sigma'][-1]['cv_pct']:.1f}%"],
                           ["rank mobility", f"{mobility['mobility']:.3f}"],
                           ["mean absolute rank change", f"{mobility['mean_abs_rank_change']:.1f}"],
                           ["share moved decile", f"{mobility['share_moved_decile_pct']:.1f}%"]]
    district_contrib_rows = [[r["district"], f"{r['initial_count']:,}",
                              f"{r['latest_count']:,}", f"{r['change']:+,}",
                              f"{r['contribution_pct']:+.2f}%"]
                             for r in (deep_dist["contributions"]["top_positive"][:10]
                                       + deep_dist["contributions"]["top_negative"][:5])]
    province_rows = [[r["province"].title(), f"{r['initial_share_pct']:.1f}%",
                      f"{r['latest_share_pct']:.1f}%",
                      f"{r['share_change_pp']:+.1f} pp",
                      f"{r['growth_pct']:+.1f}%"]
                     for r in sorted(deep_dist["provinces"]["change"],
                                     key=lambda r: r["share_change_pp"], reverse=True)]
    district_vol_rows = [[r["district"], f"{r['initial_count']:,}",
                          f"{r['latest_count']:,}", f"{r['cv']:.2f}",
                          f"{r['log_growth_sd']:.2f}"]
                         for r in (deep_dist["volatility"]["most_volatile"][:8]
                                   + deep_dist["volatility"]["least_volatile"][:5])]
    district_gender_rows = [[r["district"], f"{r['latest_total']:,}",
                             f"{r['latest_female_share_pct']:.1f}%",
                             f"{r['change_pp']:+.1f} pp"]
                            for r in (deep_dist["gender"]["increases"][:8]
                                      + deep_dist["gender"]["decreases"][:4])]
    modern_cov_rows = [[r["fiscal_year"], r["n_docs"], r["distinct_months"],
                        f"{r['monthly_sum']:,}",
                        f"{r['annual_total']:,}" if r["annual_total"] is not None else "–",
                        f"{r['gap_pct']:.3f}%" if r["gap_pct"] is not None else "–",
                        "yes" if r["complete_monthly"] else "no"]
                       for r in time_series["modern_monthly_coverage"]["fiscal_years"]]
    season_rows = [[r["bs_month"], f"{r['count']:,}", f"{r['index']:.1f}"]
                   for r in time_series["modern_seasonality"]["monthly"]]
    archive_season_rows = [[r["bs_month"], r["n_years"], f"{r['index']:.1f}",
                            f"{r['cv_pct']:.1f}%"]
                           for r in time_series["archive_seasonality"]["monthly"]]
    break_rows = []
    for key, label in (("annual_approvals", "Annual approvals"),
                       ("destination_hhi", "Destination HHI")):
        best = time_series["structural_breaks"][key]["best"]
        break_rows.append([label, best["split_after"], f"{best['pre_mean']:.2f}",
                           f"{best['post_mean']:.2f}", f"{best['difference_pct']:+.1f}%",
                           f"{best['sse_reduction']:.3f}"])
    death_rate_rows = [[r["approx_bs_fiscal_year"], f"{r['deaths']:,}",
                        f"{r['safe_approvals']:,}", f"{r['deaths_per_100k']:.1f}"]
                       for r in time_series["deaths"]["matched"]]
    safe_annual = {r["fiscal_year"]: r for r in robustness["safe_vs_permissive"]["safe"]["annual"]}
    permissive_annual = {r["fiscal_year"]: r for r in robustness["safe_vs_permissive"]["permissive"]["annual"]}
    permissive_rows = [[fy, f"{safe_annual[fy]['total']:,}",
                        f"{permissive_annual[fy]['total']:,}",
                        f"{robustness['safe_vs_permissive']['delta_permissive_minus_safe']['annual_total_by_fiscal_year'].get(fy, 0):+,}",
                        f"{robustness['safe_vs_permissive']['delta_permissive_minus_safe']['annual_total_share_of_safe_pct'].get(fy, 0):.2f}%"]
                       for fy in safe_annual if fy in permissive_annual]
    annual_monthly_rows = [[r["fiscal_year"], f"{r['annual']:,}",
                            f"{r['monthly_sum']:,}", r["month_docs"],
                            f"{r['gap_pct']:.3f}%", r["validation"]]
                           for r in robustness["annual_monthly"]["rows"]]
    lodo = next((r for r in robustness["leave_one_doc_out"]["by_fiscal_year"]
                 if r["fiscal_year"] == report["basis"]["latest_fy"]), None)
    lodo_total_rows = ([[r["doc_id"], f"{r['total_without_doc']:,}",
                         f"{r['delta_total']:+,}", f"{r['delta_total_pct']:+.2f}%"]
                        for r in lodo["most_influential_by_total"][:8]]
                       if lodo else [])
    lodo_hhi_rows = ([[r["doc_id"], f"{r['hhi_without_doc']:.4f}",
                       f"{r['delta_hhi']:+.6f}"]
                      for r in lodo["most_influential_by_hhi"][:8]]
                     if lodo else [])
    archive_scope = robustness["archive_scope"]
    archive_scope_rows = [["periods", archive_scope["periods"]],
                          ["unique scope sets", "; ".join(f"{k} ({v})" for k, v in archive_scope["unique_scope_sets"].items())],
                          ["chosen sum", f"{archive_scope['chosen_sum']:,}"],
                          ["naive all-scope sum", f"{archive_scope['naive_all_scope_sum']:,}"],
                          ["naive overcount", f"{archive_scope['naive_scope_sum_overcount_pct']:.1f}%"]]
    dedupe_rows = [[g["compatible_key"][:90], g["rows"], g["entity_years"],
                    g["duplicate_entity_years"],
                    f"{g['difference_naive_minus_deduped']:,}"]
                   for g in robustness["series_dedupe"]["labour_approval"]["groups"]
                   if g["difference_naive_minus_deduped"] > 0]

    reentry_annual_rows = [[r["fiscal_year"], f"{r['total']:,}",
                            f"{r['individual_new']:,}" if r["new_reported"] else "–",
                            f"{r['individual_reentry']:,}" if r["reentry_reported"] else "–",
                            f"{r['new_share_pct']:.1f}%" if r["new_share_pct"] is not None else "–",
                            f"{r['reentry_share_pct']:.1f}%" if r["reentry_share_pct"] is not None else "–",
                            f"{r['new_to_reentry_ratio']:.2f}" if r["new_to_reentry_ratio"] is not None else "–"]
                           for r in reentry["annual"] if r["fiscal_year"] != "2083/84"]
    reentry_country_rows = [[r["country"], f"{r['latest_total']:,}",
                             f"{r['latest_individual_new']:,}",
                             f"{r['latest_individual_reentry']:,}",
                             f"{r['new_share_latest_pct']:.1f}%",
                             f"{r['reentry_share_latest_pct']:.1f}%",
                             f"{r['reentry_share_change_pp']:+.1f} pp"
                             if r.get("reentry_share_change_pp") is not None else "–"]
                            for r in sorted(reentry["country_base_latest"]["destinations"],
                                            key=lambda r: r["latest_total"], reverse=True)[:20]]
    reentry_high_rows = [[r["country"], f"{r['latest_total']:,}",
                          f"{r['reentry_share_pct']:.1f}%",
                          f"{r['reentry_share_of_individual_pct']:.1f}%"]
                         for r in reentry["reentry_orientation"]["highest_reentry_share"][:10]]
    reentry_low_rows = [[r["country"], f"{r['latest_total']:,}",
                         f"{r['reentry_share_pct']:.1f}%",
                         f"{r['reentry_share_of_individual_pct']:.1f}%"]
                        for r in reentry["reentry_orientation"]["lowest_reentry_share"][:10]]
    reentry_stability_rows = [[r["from"], r["to"], r["n_common_above_min"],
                               f"{r['pearson']:.3f}",
                               f"{r['spearman']:.3f}"]
                              for r in reentry["reentry_orientation"]["stability"]]
    assoc = reentry["association"]
    reentry_assoc_keys = (
        ("total growth vs latest reentry share", "total_growth_vs_latest_reentry_share"),
        ("new growth vs latest reentry share", "new_growth_vs_latest_reentry_share"),
        ("new growth vs comparable reentry share", "new_growth_vs_comparable_reentry_share"),
        ("reentry growth vs comparable reentry share", "reentry_growth_vs_comparable_reentry_share"),
    )
    reentry_assoc_rows = [[label, assoc[key]["n"] if assoc[key] else "–",
                           f"{assoc[key]['pearson']:.3f}" if assoc[key] and assoc[key].get("pearson") is not None else "–",
                           f"{assoc[key]['spearman']:.3f}" if assoc[key] and assoc[key].get("spearman") is not None else "–"]
                          for label, key in reentry_assoc_keys]
    reentry_split = reentry["decomposition"]["comparable_window_split"]
    reentry_split_rows = [["individual_new", f"{reentry_split['individual_new_change']:+,}"],
                          ["individual_reentry", f"{reentry_split['individual_reentry_change']:+,}"],
                          ["other channels", f"{reentry_split['other_channels_change']:+,}"],
                          ["total", f"{reentry_split['total_change']:+,}"]]
    reentry_comp_channels = reentry["comparable_window"]["channels"]
    reentry_comp_rows = [[r["channel"], f"{r['base_count']:,}",
                          f"{r['latest_count']:,}", f"{r['change']:+,}",
                          f"{r['growth_pct']:+.1f}%" if r["growth_pct"] is not None else "–"]
                         for r in reentry_comp_channels]
    contribs = reentry["decomposition"]["country_contributors"]
    new_growth_rows = [[r["country"], f"{r['start_count']:,}",
                        f"{r['end_count']:,}", f"{r['change']:+,}"]
                       for r in contribs["new_growth_comparable"]["top_positive"][:8]]
    new_decline_rows = [[r["country"], f"{r['start_count']:,}",
                         f"{r['end_count']:,}", f"{r['change']:+,}"]
                        for r in contribs["new_growth_comparable"]["top_negative"][:5]]
    reentry_growth_rows = [[r["country"], f"{r['start_count']:,}",
                            f"{r['end_count']:,}", f"{r['change']:+,}"]
                           for r in contribs["reentry_growth_comparable"]["top_positive"][:10]]

    gc_annual_rows = [[r["fiscal_year"], f"{r['female']:,}", f"{r['male']:,}",
                       f"{r['female_share_pct']:.2f}%",
                       f"{r['female_change_prior']:+,}" if r.get("female_change_prior") is not None else "–",
                       "yes" if r["reconciles_with_country_year"] else "no"]
                      for r in gender_country["annual"] if r["complete_year"]]
    gc_country_rows = [[r["country"], f"{r['latest_total']:,}",
                        f"{r['base_female_share_pct']:.1f}%"
                        if r.get("base_female_share_pct") is not None else "–",
                        f"{r['latest_female_share_pct']:.1f}%",
                        f"{r['female_share_change_pp']:+.1f} pp" if r.get("female_share_change_pp") is not None else "–",
                        f"{r['female_growth_pct']:+.1f}%" if r.get("female_growth_pct") is not None else "–",
                        f"{r['male_growth_pct']:+.1f}%" if r.get("male_growth_pct") is not None else "–"]
                       for r in sorted(gender_country["country_deep"]["destinations"],
                                       key=lambda r: r["latest_total"], reverse=True)[:20]]
    gc_high_rows = [[r["rank"], r["country"], f"{r['latest_total']:,}",
                     f"{r['latest_female_share_pct']:.1f}%"]
                    for r in gender_country["country_ranks"]["by_latest_female_share"][:12]]
    gc_change_rows = [[r["rank"], r["country"], f"{r['latest_total']:,}",
                       f"{r['female_share_change_pp']:+.1f} pp"]
                      for r in gender_country["country_ranks"]["by_female_share_change"][:12]]
    gc_conv = gender_country["convergence"]["default"]
    gc_conv_rows = [["slope", f"{gc_conv['slope_pp_per_initial_pp']:.3f} pp per pp"],
                    ["correlation / R²", f"{gc_conv['correlation']:.3f} / {gc_conv['r_squared']:.3f}"],
                    ["n", gc_conv["n_countries"]],
                    ["low-initial half", f"{gc_conv['low_initial_half_mean_change_pp']:+.2f} pp"],
                    ["high-initial half", f"{gc_conv['high_initial_half_mean_change_pp']:+.2f} pp"]]
    gcv = gender_country["distribution"]["volatility_persistence"]
    gc_vol_rows = [[r["country"], r["n_years"], f"{r['mean_female_share_pct']:.1f}%",
                    f"{r['sd_female_share_pp']:.1f} pp",
                    f"{r['range_pp']:.1f} pp"]
                   for r in gcv["destinations"][:10]]
    gc_divergence_rows = [[r["country"], f"{r['latest_total']:,}",
                           f"{r['female_growth_pct']:+.1f}%",
                           f"{r['male_growth_pct']:+.1f}%",
                           f"{r['female_minus_male_growth_pp']:+.1f} pp"]
                          for r in gender_country["growth_divergence"]["large_volume_divergences"]]
    gc_robust_rows = [[r["threshold"], r["n_countries"],
                       f"{r['latest_total_in_scope']:,}",
                       f"{r['unweighted_mean_latest_female_share_pct']:.2f}%",
                       f"{r['weighted_latest_female_share_pct']:.2f}%",
                       f"{r['convergence_slope_pp_per_initial_pp']:.3f}"]
                      for r in gender_country["robustness"]["threshold_variants"]]

    rg_annual_rows = [[r["fiscal_year"],
                       f"{r['channels']['individual_new']['female_share_pct']:.1f}%"
                       if r["channels"]["individual_new"]["reported"] else "–",
                       f"{r['channels']['individual_reentry']['female_share_pct']:.1f}%"
                       if r["channels"]["individual_reentry"]["reported"] else "–",
                       f"{r['new_to_reentry_female_gap_pp']:+.1f} pp"
                       if r["new_to_reentry_female_gap_pp"] is not None else "–",
                       f"{r['female_share_pct']:.2f}%"]
                      for r in reentry_gender["annual"] if r["fiscal_year"] != "2083/84"]
    rg_country_rows = [[r["country"], f"{r['latest_total']:,}",
                        f"{r['new_female_share_pct']:.1f}%",
                        f"{r['reentry_female_share_pct']:.1f}%",
                        f"{r['new_to_reentry_female_gap_pp']:+.1f} pp",
                        f"{r['reentry_share_of_focus_pct']:.1f}%"]
                       for r in sorted(reentry_gender["country_table"]["destinations"],
                                       key=lambda r: abs(r["new_to_reentry_female_gap_pp"]),
                                       reverse=True)[:20]]
    rg_decomp_rows = []
    for label, key in (("new + re-entry", "new_reentry"),
                       ("all four channels", "four_channel")):
        d = reentry_gender["decomposition"]["comparable_window"][key]
        rg_decomp_rows.append([label, f"{d['aggregate_change_pp']:+.3f}",
                               f"{d['within_channel_pp']:+.3f}",
                               f"{d['channel_composition_pp']:+.3f}",
                               f"{d['interaction_residual_pp']:+.3f}"])
    rg_growth = reentry_gender["growth_decomposition"]["comparable_window"]
    rg_growth_rows = [[r["channel"], f"{r['female_start']:,}",
                       f"{r['female_end']:,}", f"{r['female_change']:+,}",
                       f"{r['female_growth_pct']:+.1f}%",
                       f"{r['male_growth_pct']:+.1f}%"]
                      for r in rg_growth["channels_detail"]]
    rg_orientation = reentry_gender["orientation"]
    rg_reentry_female_rows = [[r["country"], f"{r['latest_total']:,}",
                               f"{r['reentry_share_of_focus_pct']:.1f}%",
                               f"{r['latest_female_share_pct']:.1f}%"]
                              for r in rg_orientation["reentry_heavy_and_female_heavy"][:10]]
    rg_new_more_rows = [[r["country"], f"{r['latest_total']:,}",
                         f"{r['gap_pp']:+.1f} pp"]
                        for r in rg_orientation["new_more_female"][:10]]
    rg_reentry_more_rows = [[r["country"], f"{r['latest_total']:,}",
                             f"{r['gap_pp']:+.1f} pp"]
                            for r in rg_orientation["reentry_more_female"][:10]]
    rg_threshold_rows = [[r["min_volume"], r["n_countries"],
                          f"{r['mean_gap_pp']:.2f} pp",
                          f"{r['median_gap_pp']:.2f} pp",
                          r["new_more_female_count"],
                          r["reentry_more_female_count"]]
                         for r in reentry_gender["robustness"]["thresholds"]]

    coverage_rows = [[r["fiscal_year"] + (" (partial)" if r["partial"] else ""),
                      f"{r['total_verified']:,}", f"{r['deployment_verified']:,}",
                      f"{r['reviewed_channels']:,}", f"{r['legalization']:,}",
                      f"{r['new_entry']:,}",
                      f"{r['reviewed_share_of_total_pct']:.1f}%",
                      r["documents"], f"{r['annual_documents']}/{r['monthly_documents']}"]
                     for r in outcomes["coverage"]["rows"]]
    growth_denom_rows = [[r["country"], f"{r['base_deployment_verified']:,}",
                          f"{r['latest_deployment_verified']:,}",
                          f"{r['deployment_growth_pct']:+.1f}%" if r["deployment_growth_pct"] is not None else "–",
                          f"{r['reviewed_growth_pct']:+.1f}%" if r["reviewed_growth_pct"] is not None else "–",
                          f"{r['reviewed_minus_deployment_growth_pp']:+.1f} pp" if r["reviewed_minus_deployment_growth_pp"] is not None else "–",
                          f"{r['base_reviewed_share_pct']:.1f}%" if r["base_reviewed_share_pct"] is not None else "–",
                          "yes" if r["small_base"] else "",
                          "yes" if r["sign_flip"] else ""]
                         for r in outcomes["country_growth"]]
    suspect_rows = [[r["country"], f"{r['base_deployment_verified']:,}",
                     f"{r['latest_deployment_verified']:,}",
                     f"{r['deployment_growth_pct']:+.1f}%" if r["deployment_growth_pct"] is not None else "–",
                     f"{r['reviewed_growth_pct']:+.1f}%" if r["reviewed_growth_pct"] is not None else "–",
                     f"{r['reviewed_minus_deployment_growth_pp']:+.1f} pp" if r["reviewed_minus_deployment_growth_pp"] is not None else "–",
                     "yes" if r["small_base"] else "",
                     "yes" if r["sign_flip"] else ""]
                    for r in outcomes["suspect_series"]["rows"][:20]]
    gap = outcomes.get("gap_fill") or {}
    gap_rows = []
    if gap:
        gap_rows = [
            ["total unverified", f"{gap['total_unverified']:,}"],
            ["deployment (excl. legalization)",
             f"{gap['deployment_unverified']:,}"],
            ["legalization", f"{gap['legalization']:,}"],
            ["male + female component total",
             f"{gap['total_from_male_female']:,}"],
            ["gender-sum minus printed total", f"{gap['gender_total_difference']:+,}"],
            ["known arithmetic errors", gap["known_arithmetic_errors"]],
        ]
    recon = outcomes["annual_monthly_reconciliation"]
    recon_summary_rows = [["country × channel pairs", recon["pairs"]],
                          ["exact pairs", recon["exact_pairs"]],
                          ["mismatched pairs", recon["mismatched_pairs"]],
                          ["total absolute difference", recon["total_abs_difference"]],
                          ["difference as % of annual total", f"{100.0 * recon['total_abs_difference'] / 791489:.4f}%"]]
    recon_mismatch_rows = [[r["country"], r["channel"], f"{r['annual']:,}",
                            f"{r['monthly']:,}", f"{r['difference']:+,}"]
                           for r in recon["mismatches"]]
    base_outcome = next((r for r in outcomes["coverage"]["rows"]
                         if r["fiscal_year"] == report["basis"]["base_fy"]), {})
    latest_outcome = next((r for r in outcomes["coverage"]["rows"]
                           if r["fiscal_year"] == report["basis"]["latest_fy"]), {})

    cards = [
        ("safe rows", f"{report['basis']['rows']:,}"),
        ("safe documents", f"{report['basis']['documents']:,}"),
        ("latest complete year", f"{report['basis']['latest_fy']}"),
        ("critical / warnings", f"{critical} / {warning}"),
    ]
    card_html = "".join(
        f'<div class="card"><div class="v">{_esc(v)}</div>'
        f'<div class="l">{_esc(k)}</div></div>' for k, v in cards)

    html_text = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Migration pattern book — Phase 1</title>
<style>
  :root {{ --ink:#1f2933; --muted:#7b8794; --line:#e4e7eb; --accent:#c0392b; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#f5f6f8; color:var(--ink);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         line-height:1.55; }}
  header {{ background:linear-gradient(135deg,#1f2933,#313f4d); color:#fff;
            padding:40px 28px 32px; }}
  header h1 {{ margin:0 0 6px; font-size:26px; }}
  header p {{ margin:0; color:#cbd2d9; max-width:900px; }}
  main {{ max-width:1100px; margin:0 auto; padding:24px; }}
  section {{ background:#fff; border:1px solid var(--line); border-radius:10px;
            padding:22px 24px; margin:18px 0; }}
  h2 {{ font-size:18px; margin:0 0 6px; }}
  h3 {{ font-size:14px; margin:18px 0 4px; }}
  .sub {{ color:var(--muted); font-size:13px; margin:0 0 12px; }}
  img {{ width:100%; height:auto; display:block; margin:10px 0 4px; }}
  .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }}
  .card {{ background:#f5f6f8; border:1px solid var(--line); border-radius:8px;
          padding:12px 14px; }}
  .card .v {{ font-size:22px; font-weight:700; }}
  .card .l {{ font-size:12px; color:var(--muted); }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; margin-top:8px; }}
  th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line);
          vertical-align:top; }}
  th {{ color:var(--muted); font-weight:600; }}
  .critical {{ color:#c0392b; font-weight:700; }}
  .warning {{ color:#b7791f; font-weight:700; }}
  .info {{ color:#2b6cb0; font-weight:700; }}
  .callout {{ background:#fff7ed; border-left:4px solid #dd6b20;
             padding:10px 14px; font-size:13px; }}
  code {{ background:#eef1f4; padding:1px 5px; border-radius:4px; font-size:12px; }}
  footer {{ color:var(--muted); font-size:12px; text-align:center; padding:24px; }}
  @media(max-width:720px) {{ .cards {{ grid-template-columns:repeat(2,1fr); }} }}
</style></head><body>
<header><h1>Migration pattern book — Phase 1</h1>
<p>Generated {_esc(report['generated_at'])}. Descriptive scan of the safe
labour-migration panel. Every pattern is a lead for an econometrician, not a
causal claim.</p></header>
<main>
<section><h2>At a glance</h2><div class="cards">{card_html}</div>
<p class="sub">The cards count reviewed-channel rows. That is not the same as
total approvals; see the denominator section below. 2083/84 is partial.</p></section>
<section><h2>0. Denominators and coverage</h2>
<p class="sub">Four explicit outcomes: <code>total_verified</code> (all verified
components), <code>deployment_verified</code> (excluding legalization),
<code>reviewed_channels</code> (current <code>analysis_safe</code>), and
<code>modern_consistent</code> (four modern channels, complete only from
2081/82). The reviewed-channel series is a subset, not a total-approval trend.</p>
{_img(fig_outcome_volume, "explicit denominators")}
{_img(fig_reviewed_share, "reviewed-channel coverage")}
{_table(["FY", "total verified", "deployment", "reviewed", "legalization",
         "new_entry", "reviewed share", "docs", "annual/monthly"], coverage_rows)}
<p class="sub"><strong>FY2075/76 gap-fill.</strong> The only source is
<code>report2020_annex_X</code>, so it is kept out of the verified coverage table.
Its Qatar recruiting-agency row has a known one-worker print error. Use these
figures only as a flagged sensitivity, never pooled with verified years.</p>
{_table(["measure", "value"], gap_rows) if gap_rows else ""}
<div class="callout"><strong>Critical.</strong> Reviewed-channel coverage falls
to {base_outcome.get("reviewed_share_of_total_pct", 0):.1f}% in
{_esc(report["basis"]["base_fy"])} but is
{latest_outcome.get("reviewed_share_of_total_pct", 0):.1f}% in
{_esc(report["basis"]["latest_fy"])}. Old-template <code>new_entry</code> and
<code>legalization</code> are not in the reviewed subset. Do not interpret
reviewed-channel growth as total approval growth.</div>
</section>
<section><h2>0b. Country growth under alternative denominators</h2>
<p class="sub">Deployment-verified growth is the preferred long-run volume
comparison. Reviewed-channel growth is shown only to expose the filter artifact.
Red points in the figure have a small base, a sign flip, or a growth gap of at
least {outcomes["suspect_series"]["threshold_growth_pp"]:.0f} pp.</p>
{_img(fig_growth_denom, "growth denominator comparison")}
{_img(fig_deployment_recovery, "deployment recovery")}
{_table(["country", "base deployment", "latest deployment",
         "deployment growth", "reviewed growth", "gap", "base reviewed share",
         "small base", "sign flip"], growth_denom_rows)}
<h3>Series to flag in the report</h3>
<p class="sub">Countries whose growth conclusion depends materially on the
denominator. Portugal is correct in the source and in the monthly files, but its
reviewed-channel base is only two approvals.</p>
{_table(["country", "base deployment", "latest deployment",
         "deployment growth", "reviewed growth", "gap", "small base",
         "sign flip"], suspect_rows)}
</section>
<section><h2>0c. Annual vs monthly reconciliation, FY2082/83</h2>
<p class="sub">The only year with all 12 monthly country documents. Compare
annual and monthly totals within country × channel; never add them together.</p>
{_table(["check", "value"], recon_summary_rows)}
{_table(["country", "channel", "annual", "monthly", "difference"], recon_mismatch_rows)}
</section>
<section><h2>Data problems to carry into the paper</h2>
<p class="sub">Full note: <code>docs/migration-data-issues.md</code>. Critical
checks block analysis; warnings need a documented decision; info explains
expected exclusions.</p>
{_table(["severity", "code", "message"], problem_rows) if problem_rows else "<p>No issues flagged.</p>"}
<div class="callout"><strong>Non-negotiables.</strong> Use 2075/76
<code>report2020_annex_X</code> only as the flagged unverified gap-fill above,
never in pooled verified totals. Do not pool archive
<code>approval_type</code> with modern <code>channel_canonical</code>, and do not
sum <code>series.csv</code> across reports without deduplicating entity-years.</div>
</section>
<section><h2>1. Reviewed-channel annual volume</h2>
<p class="sub">Reviewed-channel country × FY totals, not total approvals. See
section 0 for total-verified and deployment-verified denominators. The red bar
is the partial fiscal year.</p>
{_img(fig_annual, "annual approvals")}
{_table(["FY", "approvals", "destinations", "top 5", "top 10", "HHI", "largest"], annual_rows)}
</section>
<section><h2>2. Reviewed-channel destination concentration</h2>
<p class="sub">HHI is computed on reviewed-channel destination shares; section 0
shows the denominator caveat. Top-10 share falls when
smaller corridors grow faster than the largest ones.</p>
{_img(fig_conc, "destination concentration")}
</section>
<section><h2>3. Reviewed-channel destination trajectories</h2>
<p class="sub">Reviewed-channel index, not total approvals. Indexed to {_esc(report['destinations']['index']['base'])} = 100.
Lines are the eight largest destinations in {_esc(report['basis']['latest_fy'])}.</p>
{_img(fig_index, "destination index")}
{_img(fig_recovery, "recovery scatter")}
<h3>Recovery by destination</h3>
<p class="sub">Countries with at least 1,000 approvals in the base year, ranked by
growth to {_esc(report['basis']['latest_fy'])}.</p>
{_table(["country", "pre", "latest", "pre share", "growth", "recovered"], recovery_rows)}
</section>
<section><h2>3b. Destination turnover and decomposition</h2>
<p class="sub">Rank heatmap tracks the top 12 destinations. Overlap and churn
compare successive top-10 sets; the base-to-latest new list is the turnover
behind the recovery result.</p>
{_img(fig_rank_heat, "destination rank heatmap")}
{_table(["from", "to", "n common", "Spearman", "top-10 overlap", "top-10 churn"], rank_stability_rows)}
<h3>New destinations since {_esc(deep_dest["turnover"]["base_to_latest"]["from"])}</h3>
<p class="sub">Active destinations rose from
{deep_dest["turnover"]["base_to_latest"]["active_pre"]} to
{deep_dest["turnover"]["base_to_latest"]["active_post"]};
top-10 Jaccard = {deep_dest["turnover"]["base_to_latest"]["jaccard"]:.3f}.</p>
{_table(["country", "latest approvals"], turnover_new_rows)}
<h3>Recovery decomposition</h3>
{_img(fig_recovery_water, "recovery waterfall")}
{_table(["country", "status", "pre", "latest", "contribution", "share of change"], recovery_contrib_rows)}
<h3>Concentration contributions</h3>
<p class="sub">Change in HHI decomposed into destination share shifts.
Positive contributions increase concentration; negative contributions reduce it.</p>
{_table(["country", "pre share", "latest share", "share change", "HHI contribution"], conc_contrib_rows)}
<h3>Volatile destinations</h3>
<p class="sub">Highest coefficient of variation across safe years; max drawdown
is the largest fall from a prior peak.</p>
{_table(["country", "total", "CV", "max drawdown", "latest share"], destination_vol_rows)}
</section>
<section><h2>4. Reviewed-channel entries and exits</h2>
<p class="sub">Entry: &lt;50 approvals in the first safe year and ≥1,000 in the
latest. Exit: the reverse. Small bases make these leads, not causal findings.</p>
<h3>Entries</h3>{_table(["country", "first", "latest"], entry_rows) if entry_rows else "<p>None.</p>"}
<h3>Exits</h3>{_table(["country", "first", "latest"], exit_rows) if exit_rows else "<p>None.</p>"}
</section>
<section><h2>5. Gender</h2>
<p class="sub">Female share of safe male+female approvals. The destination panel
requires at least 2,000 approvals in the latest year.</p>
{_img(fig_female, "female share trend")}
{_img(fig_female_dest, "female share by destination")}
{_table(["country", "female share", "total"], female_rows)}
<h3>Largest changes since {_esc(report['basis']['base_fy'])}</h3>
{_table(["country", "pre", "latest", "change", "latest total"], female_change_rows)}
</section>
<section><h2>5b. What explains the female shift?</h2>
<p class="sub">Shift-share splits the change in the aggregate female share into
within-destination change, destination-mix change, and a residual interaction.
Composition contributors are the destinations that move the aggregate share most.</p>
{_img(fig_female_shift, "female shift waterfall")}
{_table(["component", "contribution"], shift_component_rows)}
<h3>Destination-mix contributors</h3>
{_table(["country", "contribution", "base female share", "latest female share"], shift_contrib_rows)}
<h3>Female share by channel</h3>
<p class="sub">Shares are computed only where the channel reports sex components.
A dash means the channel was not separately reported in that year.</p>
{_table(["channel", "latest female share", "change", "latest total"], female_channel_rows)}
</section>
<section><h2>5c. Country-level gender deep dive</h2>
<p class="sub">Country trajectories and changes in female share. The top-20
largest destinations are shown; the rank tables use the volume threshold in
the metadata. Sex is reported at approval, not at arrival or return.</p>
{_img(fig_gender_country_dumbbell, "country female share change")}
{_table(["FY", "female", "male", "female share", "female change", "reconciles"], gc_annual_rows)}
{_table(["country", "latest total", "base female share", "latest female share", "change", "female growth", "male growth"], gc_country_rows)}
<h3>Highest female shares and largest changes</h3>
{_table(["rank", "country", "latest total", "female share"], gc_high_rows)}
{_table(["rank", "country", "latest total", "change"], gc_change_rows)}
<h3>Convergence and volatility</h3>
{_img(fig_gender_country_conv, "female share convergence")}
{_table(["diagnostic", "value"], gc_conv_rows)}
{_table(["country", "years", "mean share", "within SD", "range"], gc_vol_rows)}
<h3>Female vs male growth divergence</h3>
{_table(["country", "latest total", "female growth", "male growth", "gap"], gc_divergence_rows)}
<h3>Threshold sensitivity</h3>
{_table(["min volume", "countries", "latest volume", "mean share", "weighted share", "convergence slope"], gc_robust_rows)}
</section>
<section><h2>6. Channels and repeat migration</h2>
<p class="sub">Channel shares use canonical channels. Re-entry is a channel label,
not an individual migration history.</p>
{_img(fig_channels, "channel mix")}
{_table(["FY", "approvals"] + report["channels"]["columns"], channel_rows)}
<h3>Recorded re-entry channel</h3>
<p class="sub">Share of the safe annual approvals whose canonical channel is
<code>individual_reentry</code>. This is a label, not an individual history.</p>
{_table(["FY", "safe approvals", "re-entry channel", "share"], reentry_rows)}
</section>
<section><h2>6b. Destination × channel and re-entry</h2>
<p class="sub">Channel composition of the largest latest-year destinations. A
destination is agency- or G2G-dependent when that channel exceeds the stated
threshold.</p>
{_img(fig_channel_dest, "destination channel stack")}
{_table(["country", "dominant", "G2G", "new", "re-entry", "agency", "agency-dependent", "G2G-dependent"], channel_dest_rows)}
<h3>Channel growth over the comparable window</h3>
{_table(["channel", "base", "latest", "change", "growth", "share of total growth"], channel_growth_rows)}
<h3>Re-entry by destination</h3>
<p class="sub">Largest latest-year re-entry volumes. Re-entry is a recorded
channel label, not an individual migration history.</p>
{_table(["country", "latest re-entry", "share of destination", "change"], reentry_dest_rows)}
</section>
<section><h2>6c. New vs re-entry line deep dive</h2>
<p class="sub"><code>individual_new</code> and <code>individual_reentry</code>
are separately reported only from 2081/82, so the comparable window is
2081/82 → 2082/83. The base-year new-line figure is not a level comparison.
Re-entry is a channel label, not a unique-person history.</p>
{_img(fig_new_reentry, "new vs reentry trend")}
{_table(["FY", "total", "new", "re-entry", "new share", "re-entry share", "new/re-entry"], reentry_annual_rows)}
{_table(["channel", "base", "latest", "change", "growth"], reentry_comp_rows)}
<h3>Country-level orientation</h3>
{_img(fig_new_reentry_scatter, "reentry orientation scatter")}
{_table(["country", "latest total", "new", "re-entry", "new share", "re-entry share", "change"], reentry_country_rows)}
<h3>Highest and lowest re-entry orientation</h3>
{_table(["country", "latest total", "re-entry share of all", "re-entry share of individual"], reentry_high_rows)}
{_table(["country", "latest total", "re-entry share of all", "re-entry share of individual"], reentry_low_rows)}
<h3>Rank stability and association</h3>
{_table(["from", "to", "n common", "Pearson", "Spearman"], reentry_stability_rows)}
{_table(["association", "n", "Pearson", "Spearman"], reentry_assoc_rows)}
<h3>Growth contribution</h3>
{_table(["component", "change, comparable window"], reentry_split_rows)}
{_table(["country", "base new", "latest new", "change"], new_growth_rows)}
{_table(["country", "base new", "latest new", "change"], new_decline_rows)}
{_table(["country", "base re-entry", "latest re-entry", "change"], reentry_growth_rows)}
{_img(fig_new_reentry_top, "reentry share top destinations")}
</section>
<section><h2>6d. Re-entry × gender</h2>
<p class="sub">Female share within each line, and the new-minus-re-entry gap.
Positive gaps mean the new line is more female than re-entry in that destination.</p>
{_img(fig_gender_channel_gap, "female share new vs reentry")}
{_table(["FY", "new female share", "re-entry female share", "gap", "all female share"], rg_annual_rows)}
{_img(fig_reentry_gender_gap, "new minus reentry female gap")}
{_table(["country", "latest total", "new female", "re-entry female", "gap", "re-entry share of focus"], rg_country_rows)}
<h3>Channel decomposition of female-share change</h3>
{_img(fig_reentry_gender_decomp, "female share channel decomposition")}
{_table(["window", "aggregate", "within", "composition", "interaction"], rg_decomp_rows)}
{_table(["channel", "female start", "female latest", "female change", "female growth", "male growth"], rg_growth_rows)}
<h3>Orientation</h3>
{_table(["country", "latest total", "re-entry share", "female share"], rg_reentry_female_rows)}
{_table(["country", "latest total", "new minus re-entry gap"], rg_new_more_rows)}
{_table(["country", "latest total", "new minus re-entry gap"], rg_reentry_more_rows)}
{_table(["min volume", "countries", "mean gap", "median gap", "new-more-female", "reentry-more-female"], rg_threshold_rows)}
</section>
<section><h2>7. Origin districts</h2>
<p class="sub">District totals are additive; district × destination flows are not
in the panel.</p>
{_img(fig_district, "district concentration")}
<h3>Top districts, {_esc(report['districts']['latest_fiscal_year'])}</h3>
{_table(["district", "approvals"], district_rows)}
{_img(fig_converge, "district convergence")}
<h3>Districts with the largest initial shares</h3>
{_table(["district", "initial share", "growth", "latest"], convergence_rows)}
</section>
<section><h2>7b. District mobility and provincial shift</h2>
<p class="sub">Convergence tests whether initially smaller districts grew faster.
The transition heatmap shows movement across initial-share quintiles.</p>
{_table(["diagnostic", "value"], convergence_summary)}
{_img(fig_transition, "district transition heatmap")}
<h3>District contributions to the national change</h3>
{_table(["district", "initial", "latest", "change", "contribution"], district_contrib_rows)}
<h3>Provincial shares</h3>
{_img(fig_province, "province share change")}
{_table(["province", "initial share", "latest share", "change", "growth"], province_rows)}
<h3>District volatility and gender shifts</h3>
{_table(["district", "initial", "latest", "CV", "log-growth SD"], district_vol_rows)}
{_table(["district", "latest total", "female share", "change"], district_gender_rows)}
</section>
<section><h2>8. Time and seasonality</h2>
<p class="sub">Modern monthly data are sparse before 2081/82 and complete only
from 2082/83. The archive panel is a separate monthly series and should not be
pooled with modern months.</p>
{_img(fig_month, "modern monthly approvals")}
{_table(["start", "FY", "approvals"], monthly_rows) if monthly_rows else "<p>No modern monthly rows.</p>"}
{_img(fig_archive, "archive monthly approvals")}
{_table(["period (BS)", "scope used", "approvals"], archive_rows) if archive_rows else "<p>No archive rows.</p>"}
</section>
<section><h2>8b. Coverage, seasonality and structural breaks</h2>
<p class="sub">Modern monthly coverage is checked against annual totals. Gaps
below are in percent of the annual total; small gaps can be rounding or
unclassified-month artifacts, large gaps mean incomplete monthly capture.</p>
{_table(["FY", "docs", "months", "monthly sum", "annual total", "gap", "complete"], modern_cov_rows)}
{_img(fig_modern_season, "modern seasonality")}
{_table(["BS month", "approvals", "index"], season_rows)}
<h3>Archive seasonality</h3>
<p class="sub">Archive is a separate monthly series (BS 2067–2075); its seasonal
shape is not pooled with modern months.</p>
{_img(fig_archive_heat, "archive coverage heatmap")}
{_table(["BS month", "years", "index", "CV"], archive_season_rows)}
<h3>Structural breaks</h3>
{_img(fig_breaks, "structural break scan")}
{_table(["series", "best split after", "pre mean", "post mean", "difference", "SSE reduction"], break_rows)}
</section>
<section><h2>9. Welfare series</h2>
<p class="sub">Deaths come from a separate historical series. The denominator and
reporting completeness differ from the approval panel.</p>
{_img(fig_deaths, "reported deaths")}
{_table(["FY", "deaths"], death_rows) if death_rows else "<p>No deaths series found.</p>"}
</section>
<section><h2>9b. Deaths relative to approvals</h2>
<p class="sub">Deaths per 100,000 safe approvals. Numerator and denominator come
from different reporting systems, so this is a descriptive ratio, not a
mortality rate.</p>
{_img(fig_deaths_rate, "deaths per approvals")}
{_table(["FY", "deaths", "safe approvals", "per 100k"], death_rate_rows)}
</section>
<section><h2>10. Robustness and sensitivity</h2>
<p class="sub">These checks show how much the descriptive conclusions depend on
the `analysis_safe` filter, monthly consistency, single documents, archive scope,
and series deduplication.</p>
<h3>Safe vs permissive</h3>
{_img(fig_permissive, "safe vs permissive delta")}
{_table(["FY", "safe", "permissive", "delta", "delta % of safe"], permissive_rows)}
<h3>Annual vs monthly consistency</h3>
{_table(["FY", "annual", "monthly sum", "month docs", "gap", "validation"], annual_monthly_rows)}
<h3>Leave-one-document-out, {_esc(report["basis"]["latest_fy"])}</h3>
<p class="sub">Most influential documents by total approvals and by destination
HHI when omitted.</p>
{_table(["doc", "total without doc", "delta total", "delta %"], lodo_total_rows)}
{_table(["doc", "HHI without doc", "delta HHI"], lodo_hhi_rows)}
<h3>Archive scope sensitivity</h3>
{_table(["check", "value"], archive_scope_rows)}
<h3>Series deduplication</h3>
<p class="sub">Groups where naive cross-report summation overstates entity-year
approvals. The analysis uses deduplicated entity-years.</p>
{_table(["compatible key", "rows", "entity-years", "duplicate entity-years", "naive minus deduped"], dedupe_rows)}
</section>
<section><h2>11. Watchlist and candidate hypotheses</h2>
<p class="sub">Ranked leads. Treat each as a question and a design problem, not a
result.</p>
{_table(["rank", "label", "pattern", "question", "data needed", "risk"], hypothesis_rows)}
</section>
<section><h2>Reproduce</h2>
<p class="sub"><code>python -m migration_parser.cli audit</code> then
<code>python -m migration_parser.cli patterns</code>. Outputs land in
<code>output/migration/research/</code>.</p>
</section>
</main>
<footer>Phase 1 pattern book · safe panel · descriptive, not causal</footer>
</body></html>
"""
    (out / "pattern_book.html").write_text(html_text)
    return {"html": out / "pattern_book.html", "json": out / "patterns.json",
            "markdown": out / "findings.md"}
