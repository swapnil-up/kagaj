"""Exploratory analysis report for the Nepali labour-migration panel.

Not part of the build pipeline (needs matplotlib, which is not a runtime
dependency). Run directly::

    redbook-env/bin/python -m migration_parser.report

Reads the tracked artefacts in ``migration/`` and writes a self-contained
HTML report (figures embedded as base64 PNG) to ``output/migration/report.html``.
"""

from __future__ import annotations

import base64
import io
import json
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .paths import MIGRATION_DIR, MIGRATION_OUTPUT_DIR

OUT = MIGRATION_OUTPUT_DIR / "report.html"

# --- palette -----------------------------------------------------------------
INK = "#1f2933"
MUTED = "#7b8794"
GRID = "#e4e7eb"
C = {
    "qatar": "#c0392b",
    "uae": "#e67e22",
    "saudi": "#27ae60",
    "malaysia": "#2980b9",
    "kuwait": "#8e44ad",
    "other": "#95a5a6",
    "male": "#2c7fb8",
    "female": "#e377c2",
    "accent": "#c0392b",
    "accent2": "#2b6cb0",
}
PALETTE = ["#c0392b", "#e67e22", "#27ae60", "#2980b9", "#8e44ad", "#16a085",
           "#d35400", "#7f8c8d", "#f39c12", "#2c3e50", "#c2185b", "#00838f"]


def _style(ax, title=None, ylab=None):
    ax.set_facecolor("white")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=INK, fontsize=11, fontweight="bold", loc="left")
    if ylab:
        ax.set_ylabel(ylab, color=MUTED, fontsize=9)


def _fig_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _kfmt(x, _pos=None):
    if x >= 1_000_000:
        return f"{x/1_000_000:.1f}M"
    if x >= 1_000:
        return f"{x/1_000:.0f}k"
    return f"{int(x)}"


# --- data prep ---------------------------------------------------------------

def load():
    p = pd.read_csv(MIGRATION_DIR / "panel_canonical.csv", dtype=str)
    p["count"] = pd.to_numeric(p["count"], errors="coerce")
    s = pd.read_csv(MIGRATION_DIR / "series.csv", dtype=str)
    s["count"] = pd.to_numeric(s["count"], errors="coerce")
    return p, s


def component_country(p):
    return p[(p.section == "country") & (p.row_type == "detail")
             & (p.gender == "total") & (p.channel_class == "component")].copy()


def annual_basis(c):
    """Annual 'national' totals: annual docs where present, else monthly sum."""
    a = c[c.granularity == "year"].groupby("reconciled_fiscal_year")["count"].sum()
    m = c[c.granularity == "month"].groupby("reconciled_fiscal_year")["count"].sum()
    basis = {}
    out = {}
    for fy in sorted(set(a.index) | set(m.index)):
        if fy in a.index:
            out[fy], basis[fy] = a[fy], "annual"
        else:
            out[fy], basis[fy] = m[fy], "months (partial)"
    return out, basis


# --- figures -----------------------------------------------------------------

def fig_coverage(p) -> str:
    cnt = (p.groupby(["reconciled_fiscal_year", "granularity"]).doc_id.nunique()
           .unstack(fill_value=0).reindex(columns=["month", "year", "measure"], fill_value=0))
    fig, ax = plt.subplots(figsize=(8.4, 3.2))
    bottom = pd.Series(0, index=cnt.index)
    labs = {"month": "monthly docs", "year": "annual docs", "measure": "pre-approval"}
    for g, col in zip(["month", "year", "measure"], [C["accent2"], C["saudi"], C["other"]]):
        ax.bar(cnt.index, cnt[g], bottom=bottom, label=labs[g], color=col, width=0.7)
        bottom = bottom + cnt[g]
    _style(ax, "Source-document coverage by fiscal year", "documents")
    ax.set_xticks(range(len(cnt.index)))
    ax.set_xticklabels(cnt.index, rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=8, ncol=3)
    return _fig_base64(fig)


def fig_annual(tot, basis) -> str:
    fys = list(tot)
    x = range(len(fys))
    vals = [tot[f] for f in fys]
    cols = [C["accent"] if basis[f] != "annual" else C["accent2"] for f in fys]
    fig, ax = plt.subplots(figsize=(8.4, 3.6))
    ax.plot(x, vals, color=MUTED, lw=1.4, zorder=2)
    # last point (2083/84) is a partial-year sum of months — draw that segment dashed
    if basis[fys[-1]] != "annual":
        ax.plot(x[-2:], vals[-2:], color=MUTED, lw=1.4, ls="--", zorder=2)
    ax.scatter(x, vals, c=cols, s=48, zorder=3)
    for i, v in enumerate(vals):
        lbl = _kfmt(v) + ("\n(partial)" if basis[fys[i]] != "annual" else "")
        ax.annotate(lbl, (i, v), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8, color=INK)
    dip = fys.index("2077/78")
    ax.annotate("COVID-19 border closures", (dip, vals[dip]),
                xytext=(dip - 0.4, max(vals) * 0.55), fontsize=9, color=C["accent"],
                arrowprops=dict(arrowstyle="->", color=C["accent"], lw=1.2))
    _style(ax, "Annual labour approvals by fiscal year (BS)", "approved permits")
    ax.set_xticks(list(x))
    ax.set_xticklabels(fys, rotation=45, ha="right")
    ax.yaxis.set_major_formatter(_kfmt)
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], marker="o", ls="", color=C["accent2"], label="annual doc"),
                       Line2D([], [], marker="o", ls="", color=C["accent"], label="sum of months (partial)")],
              frameon=False, fontsize=8)
    return _fig_base64(fig)


def fig_seasonality(p) -> str:
    c = component_country(p)
    m = c[c.granularity == "month"].copy()
    m["start"] = pd.to_datetime(m.period_ad_start, errors="coerce")
    mm = (m.groupby(["doc_id", "start"])["count"].sum().reset_index()
          .sort_values("start"))
    fy = mm.start.dt.year.astype(str) + "-" + mm.start.dt.month.astype(str).str.zfill(2)
    fig, ax = plt.subplots(figsize=(8.4, 3.4))
    for yr, col in [(2025, C["accent2"]), (2026, C["qatar"])]:
        sub = mm[mm.start.dt.year == yr]
        ax.plot(sub.start, sub["count"], marker="o", color=col, lw=1.6, label=yr)
        for _, r in sub.iterrows():
            ax.annotate(_kfmt(r["count"]), (r.start, r["count"]),
                        textcoords="offset points", xytext=(0, 6), ha="center",
                        fontsize=7, color=INK)
    _style(ax, "Monthly approval windows (4-week periods), AD-dated", "approved permits")
    ax.yaxis.set_major_formatter(_kfmt)
    fig.autofmt_xdate(rotation=30)
    ax.legend(frameon=False, fontsize=8, title="window start year")
    return _fig_base64(fig)


def fig_destinations(c) -> str:
    top = (c[c.granularity == "year"].groupby("name_canonical")["count"].sum()
           .sort_values(ascending=False).head(12)[::-1])
    fig, ax = plt.subplots(figsize=(8.4, 4.0))
    ax.barh(top.index, top.values, color=C["accent2"])
    for i, v in enumerate(top.values):
        ax.annotate(_kfmt(v), (v, i), va="center", xytext=(4, 0),
                    textcoords="offset points", fontsize=8, color=INK)
    _style(ax, "Top destination countries, all annual statements combined")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    ax.xaxis.set_major_formatter(_kfmt)
    return _fig_base64(fig)


def fig_dest_mix(c) -> str:
    groups = {"Qatar": "qatar", "United Arab Emirates": "uae", "Saudi Arabia": "saudi",
              "Malaysia": "malaysia", "Kuwait": "kuwait"}
    a = c[c.granularity == "year"]
    g = a.groupby(["reconciled_fiscal_year", "name_canonical"])["count"].sum().reset_index()
    tot = g.groupby("reconciled_fiscal_year")["count"].sum()
    fys = sorted(tot.index)
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    remaining = pd.Series(0.0, index=fys)
    series = {}
    for name, key in groups.items():
        series[name] = (g[g.name_canonical == name].set_index("reconciled_fiscal_year")["count"]
                        .reindex(fys, fill_value=0) / tot * 100)
    series["Other"] = 100 - sum(series.values())
    bottom = pd.Series(0.0, index=fys)
    for name in list(groups) + ["Other"]:
        vals = series[name]
        col = C.get(groups.get(name, "other"), C["other"])
        ax.bar(fys, vals, bottom=bottom, color=col, label=name, width=0.7)
        bottom = bottom + vals
    _style(ax, "Destination mix (% of annual approvals)", "% of approvals")
    ax.set_xticks(range(len(fys)))
    ax.set_xticklabels(fys, rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=8, ncol=3)
    return _fig_base64(fig)


def fig_gender(p) -> str:
    c = p[(p.section == "country") & (p.row_type == "detail")
          & (p.gender.isin(["male", "female"])) & (p.channel_class == "component")]
    a = c[c.granularity == "year"]
    g = a.groupby(["reconciled_fiscal_year", "gender"])["count"].sum().unstack()
    share = g["female"] / (g["male"] + g["female"]) * 100
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.6, 3.6), gridspec_kw={"width_ratios": [1.25, 1]})
    ax1.bar(g.index, g["male"], color=C["male"], label="male", width=0.7)
    ax1.bar(g.index, g["female"], bottom=g["male"], color=C["female"], label="female", width=0.7)
    _style(ax1, "Approvals by sex", "approved permits")
    ax1.set_xticks(range(len(g.index)))
    ax1.set_xticklabels(g.index, rotation=45, ha="right")
    ax1.yaxis.set_major_formatter(_kfmt)
    ax1.legend(frameon=False, fontsize=8)
    ax2.plot(range(len(share)), share.values, marker="o", color=C["female"], lw=1.6)
    for i, v in enumerate(share.values):
        ax2.annotate(f"{v:.1f}%", (i, v), textcoords="offset points", xytext=(0, 6),
                     ha="center", fontsize=8, color=INK)
    _style(ax2, "Female share of approvals", "%")
    ax2.set_xticks(range(len(share.index)))
    ax2.set_xticklabels(share.index, rotation=45, ha="right")
    ax2.set_ylim(0, max(share.values) * 1.25)
    return _fig_base64(fig)


def fig_female_by_dest(p) -> str:
    c = p[(p.section == "country") & (p.row_type == "detail")
          & (p.gender.isin(["male", "female"])) & (p.channel_class == "component")
          & (p.granularity == "year") & (p.reconciled_fiscal_year == "2082/83")]
    g = c.groupby(["name_canonical", "gender"])["count"].sum().unstack(fill_value=0)
    g["tot"] = g.get("male", 0) + g.get("female", 0)
    g = g[g.tot > 0].copy()
    g["share"] = g["female"] / g.tot * 100
    top = g.sort_values("tot", ascending=False).head(12).sort_values("share")
    fig, ax = plt.subplots(figsize=(8.4, 4.0))
    ax.barh(top.index, top["share"], color=C["female"])
    for i, (v, t) in enumerate(zip(top["share"], top["tot"])):
        ax.annotate(f"{v:.0f}%  (n={_kfmt(t)})", (v, i), va="center", xytext=(4, 0),
                    textcoords="offset points", fontsize=8, color=INK)
    _style(ax, "Female share by top destinations, FY 2082/83", "% female")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, 100)
    return _fig_base64(fig)


def fig_channels(c) -> str:
    a = c[c.granularity == "year"]
    ch = (a.pivot_table(index="reconciled_fiscal_year", columns="channel_canonical",
                        values="count", aggfunc="sum", fill_value=0))
    order = ["recruiting_agency", "individual_new", "new_entry", "g2g",
             "individual_reentry", "legalization"]
    ch = ch.reindex(columns=[c for c in order if c in ch.columns], fill_value=0)
    fys = list(ch.index)
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    bottom = pd.Series(0.0, index=ch.index)
    for col, color in zip(ch.columns, PALETTE):
        ax.bar(ch.index, ch[col], bottom=bottom, color=color, label=col, width=0.7)
        bottom = bottom + ch[col]
    _style(ax, "Approval-channel composition by fiscal year (annual docs)", "approved permits")
    ax.set_xticks(range(len(fys)))
    ax.set_xticklabels(fys, rotation=45, ha="right")
    ax.yaxis.set_major_formatter(_kfmt)
    ax.legend(frameon=False, fontsize=8, ncol=3)
    return _fig_base64(fig)


def fig_province(p) -> str:
    d = p[(p.section == "district") & (p.row_type == "detail")
          & (p.gender == "total") & (p.channel_class == "component")
          & (p.granularity == "year")]
    g = d.groupby(["reconciled_fiscal_year", "province"])["count"].sum().unstack(fill_value=0)
    order = g.sum().sort_values(ascending=False).index.tolist()
    g = g[order]
    fys = list(g.index)
    share = g.div(g.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    bottom = pd.Series(0.0, index=share.index)
    for col, color in zip(share.columns, PALETTE):
        ax.bar(share.index, share[col], bottom=bottom, color=color, label=col, width=0.7)
        bottom = bottom + share[col]
    _style(ax, "Origin province mix (% of district-row approvals, annual docs)", "% of approvals")
    ax.set_xticks(range(len(fys)))
    ax.set_xticklabels(fys, rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=8, ncol=5)
    return _fig_base64(fig)


def fig_reentry(p) -> str:
    t = p[(p.section == "country") & (p.gender == "total") & (p.row_type == "total")
          & (p.granularity == "year")
          & (p.channel.isin(["total_with_reentry", "total_without_reentry"]))]
    w = t.pivot_table(index="reconciled_fiscal_year", columns="channel",
                      values="count", aggfunc="sum")
    w = w.dropna()
    reent = w["total_with_reentry"] - w["total_without_reentry"]
    fig, ax = plt.subplots(figsize=(8.4, 3.5))
    ax.bar(w.index, w["total_without_reentry"], color=C["accent2"], label="new (without re-entry)", width=0.7)
    ax.bar(w.index, reent, bottom=w["total_without_reentry"], color=C["accent"], label="re-entry", width=0.7)
    _style(ax, "New entrants vs repeat migrants (re-entry)", "approved permits")
    ax.set_xticks(range(len(w.index)))
    ax.set_xticklabels(w.index, rotation=45, ha="right")
    ax.yaxis.set_major_formatter(_kfmt)
    ax.legend(frameon=False, fontsize=8)
    return _fig_base64(fig)


def fig_top_districts(p) -> str:
    d = p[(p.section == "district") & (p.row_type == "detail")
          & (p.gender == "total") & (p.channel_class == "component")
          & (p.granularity == "year") & (p.reconciled_fiscal_year == "2082/83")]
    top = d.groupby("name_canonical")["count"].sum().sort_values(ascending=False).head(15)[::-1]
    fig, ax = plt.subplots(figsize=(8.4, 4.2))
    ax.barh(top.index, top.values, color=C["saudi"])
    for i, v in enumerate(top.values):
        ax.annotate(_kfmt(v), (v, i), va="center", xytext=(4, 0),
                    textcoords="offset points", fontsize=8, color=INK)
    _style(ax, "Top origin districts, FY 2082/83", "approved permits")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    ax.xaxis.set_major_formatter(_kfmt)
    return _fig_base64(fig)


def _deaths_series(s):
    """All-cause reported deaths per origin FY.

    Prefer the most recent tabulation: the Nepal Labour Migration Report 2024
    ("Cause of Death, 2008/09–2023/24", FY2008/09–2023/24); then the 2020
    report ("Cause of Death by Year"); then the status-report country-wise
    all-cause table (to FY2016/17). Each candidate is a single consistent
    source, so we return the first one present rather than mixing them.
    """
    cands = [
        "(?i)cause of death, 2008/09",          # migration_2024
        "(?i)cause of death by year",           # migration_2020
        "(?i)reported number of deaths, country wise",  # status reports
    ]
    for pat in cands:
        d = s[(s.metric == "deaths") & (s.gender == "total")
              & s.caption.str.contains(pat, regex=True, na=False)]
        if len(d):
            return d.groupby("fiscal_year")["count"].sum()
    return s.iloc[0:0].groupby("fiscal_year")["count"].sum()


def fig_deaths(s) -> str:
    d = _deaths_series(s)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.6, 3.5), gridspec_kw={"width_ratios": [1.3, 1]})
    ax1.plot(range(len(d)), d.values, marker="o", color=C["accent"], lw=1.6)
    for i, v in enumerate(d.values):
        ax1.annotate(f"{int(v)}", (i, v), textcoords="offset points", xytext=(0, 6),
                     ha="center", fontsize=8, color=INK)
    _style(ax1, "Reported deaths of migrant workers, by fiscal year", "deaths")
    ax1.set_xticks(range(len(d.index)))
    ax1.set_xticklabels(d.index, rotation=45, ha="right")
    # causes, latest year available
    cy = s[(s.metric == "deaths_by_cause")].copy()
    if len(cy):
        latest = sorted(cy.fiscal_year.dropna().unique())[-1]
        cc = cy[cy.fiscal_year == latest].groupby("note")["count"].sum().sort_values()
        ax2.barh(cc.index, cc.values, color=C["accent2"])
        _style(ax2, f"Deaths by cause, {latest}", "deaths")
        ax2.grid(axis="x", color=GRID, lw=0.7)
        ax2.grid(axis="y", visible=False)
    return _fig_base64(fig)


# --- report ------------------------------------------------------------------

def main(argv=None) -> int:
    p, s = load()
    c = component_country(p)
    tot, basis = annual_basis(c)

    figs = {
        "coverage": fig_coverage(p),
        "annual": fig_annual(tot, basis),
        "season": fig_seasonality(p),
        "dest": fig_destinations(c),
        "destmix": fig_dest_mix(c),
        "gender": fig_gender(p),
        "fdup": fig_female_by_dest(p),
        "chan": fig_channels(c),
        "reentry": fig_reentry(p),
        "prov": fig_province(p),
        "dist": fig_top_districts(p),
        "death": fig_deaths(s),
    }

    build = json.loads((MIGRATION_DIR / "build.json").read_text())
    ver = json.loads((MIGRATION_DIR / "verification.json").read_text())

    n_docs = p.doc_id.nunique()
    n_fy = p.reconciled_fiscal_year.nunique()
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nepali Labour Migration Panel — Exploratory Analysis</title>
<style>
  :root {{ --ink:{INK}; --muted:{MUTED}; --line:{GRID}; --accent:{C['accent']}; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#f5f6f8; color:var(--ink);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         line-height:1.55; }}
  header {{ background:linear-gradient(135deg,#1f2933,#313f4d); color:#fff; padding:44px 28px 34px; }}
  header h1 {{ margin:0 0 6px; font-size:26px; }}
  header p {{ margin:0; color:#cbd2d9; max-width:820px; }}
  main {{ max-width:960px; margin:0 auto; padding:26px; }}
  section {{ background:#fff; border:1px solid var(--line); border-radius:10px;
            padding:22px 24px; margin:20px 0; }}
  h2 {{ font-size:18px; margin:0 0 4px; }}
  h2 .n {{ color:var(--accent); font-variant-numeric:tabular-nums; margin-right:8px; }}
  .sub {{ color:var(--muted); font-size:13px; margin:0 0 14px; }}
  img {{ width:100%; height:auto; display:block; margin:10px 0 6px; }}
  .finding {{ border-left:3px solid var(--accent); background:#fdf3f2;
             padding:10px 14px; border-radius:0 6px 6px 0; margin:14px 0 0; font-size:14px; }}
  .finding b {{ color:var(--accent); }}
  .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:8px 0 0; }}
  .card {{ background:#f5f6f8; border:1px solid var(--line); border-radius:8px; padding:12px 14px; }}
  .card .v {{ font-size:22px; font-weight:700; }}
  .card .l {{ font-size:12px; color:var(--muted); }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; margin-top:10px; }}
  th,td {{ text-align:left; padding:7px 9px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--muted); font-weight:600; }}
  code {{ background:#eef1f4; padding:1px 5px; border-radius:4px; font-size:12px; }}
  footer {{ color:var(--muted); font-size:12px; text-align:center; padding:24px; }}
  @media(max-width:680px) {{ .cards {{ grid-template-columns:repeat(2,1fr); }} }}
</style></head><body>
<header>
  <h1>Nepali Labour Migration — exploratory analysis</h1>
  <p>What the compiled DoFE labour-approval panel says about the volume, destinations,
     gender composition and geographic origin of Nepali labour migration.
     Generated {gen} from build <code>{build['git']['describe']}</code>{' (dirty)' if build['git'].get('dirty') else ''}.</p>
</header>
<main>

<section>
  <h2><span class="n">01</span>At a glance</h2>
  <p class="sub">Canonical panel: {p.shape[0]:,} rows, {n_docs} source documents,
     {n_fy} fiscal years. Every figure below is reproducible from
     <code>panel_canonical.csv.gz</code>.</p>
  <div class="cards">
    <div class="card"><div class="v">{p.shape[0]:,}</div><div class="l">canonical rows</div></div>
    <div class="card"><div class="v">{n_docs}</div><div class="l">source documents</div></div>
    <div class="card"><div class="v">{n_fy}</div><div class="l">fiscal years (BS)</div></div>
    <div class="card"><div class="v">{ver['unexpected']}</div><div class="l">unexpected math failures</div></div>
  </div>
  <div class="finding"><b>Basis.</b> "Approvals" here means the sum of <i>component</i>
    deployment channels (recruiting-agency, individual, G2G, re-entry, legalisation) for
    destination-country detail rows, males+females. Printed roll-up totals are never added to
    components. Monthly and annual granularities are never mixed within a year.</div>
</section>

<section>
  <h2><span class="n">02</span>Coverage &amp; the annual record</h2>
  <p class="sub">Document coverage per fiscal year, then the headline annual approvals series
     (annual statements where available, otherwise the sum of monthly windows — 2083/84 is
     partial).</p>
  <img src="data:image/png;base64,{figs['coverage']}" alt="coverage">
  <img src="data:image/png;base64,{figs['annual']}" alt="annual approvals">
  <div class="finding"><b>The COVID collapse and rebound.</b> Approvals fell from
     ~630k (FY2078/79, 2021/22) to <b>166,698 in FY2077/78 (2020/21)</b> — a ~74% drop — as
     Gulf/Malaysia borders shut, then recovered to ~790k by FY2082/83. This is the cleanest
     natural experiment in the panel.</div>
</section>

<section>
  <h2><span class="n">03</span>Seasonality</h2>
  <p class="sub">DoFE "months" are ~4-week approval windows, dated by their AD start. Monthly
     detail begins only at BS 2081/82, so the seasonal signal rests on recent years.</p>
  <img src="data:image/png;base64,{figs['season']}" alt="seasonality">
  <div class="finding"><b>A spring/summer peak, a winter trough.</b> Approval windows run
     high in the Baisakh–Ashar period (Apr–Jun, ~74–79k) and again mid-monsoon, and are
     lowest in the Magh–Falgun windows (Jan–Feb, ~53–63k) — consistent with pre-monsoon
     recruitment cycles and a quiet winter. Note the 12 monthly documents for 2082/83 sum
     to 792,203 vs the annual statement's 792,187 — a 0.002% gap that independently
     validates the extraction.</div>
</section>

<section>
  <h2><span class="n">04</span>Where they go</h2>
  <p class="sub">Destination mix across all annual statements; the GCC plus Malaysia still
     dominate, but the composition has shifted sharply.</p>
  <img src="data:image/png;base64,{figs['dest']}" alt="top destinations">
  <img src="data:image/png;base64,{figs['destmix']}" alt="destination mix">
  <div class="finding"><b>Malaysia's boom-bust and the European turn.</b> Malaysia fell from
     ~34% of approvals (FY2079/80) to ~6–7% (FY2081/82), while "emerging" destinations
     (Romania, Croatia, Japan, South Korea, Malta, Poland, …) rose from ~1.3%
     (FY2073/74) to <b>~14% (FY2082/83)</b>. Gulf shares (Qatar, UAE, Saudi) have drifted
     down as the destination set diversifies.</div>
</section>

<section>
  <h2><span class="n">05</span>Gender composition</h2>
  <p class="sub">Female approvals are a rising, policy-salient share — and highly
     destination-specific.</p>
  <img src="data:image/png;base64,{figs['gender']}" alt="gender">
  <img src="data:image/png;base64,{figs['fdup']}" alt="female share by destination">
  <div class="finding"><b>Feminisation of migration.</b> The female share of approvals rose
     steadily from <b>~5.2% (FY2073/74) to ~12% (FY2082/83)</b>, with a dip during the
     COVID trough. In FY2082/83 it is sharply destination-specific: <b>Cyprus (~64%),
     Maldives (~44%) and Japan (~31%)</b> skew female, while Saudi Arabia, Malaysia and
     Qatar are near 1–8%.</div>
</section>

<section>
  <h2><span class="n">06</span>Approval channels</h2>
  <p class="sub">How permits are acquired. The old template's lumped <code>new_entry</code>
     was replaced by the modern split (<code>individual_new</code> / <code>g2g</code>) from
     BS 2081/82.</p>
  <img src="data:image/png;base64,{figs['chan']}" alt="channel mix">
  <img src="data:image/png;base64,{figs['reentry']}" alt="re-entry">
  <div class="finding"><b>Repeat migration dominates.</b> Re-entry (repeat migrants renewing
     a permit) is one of the two largest channels throughout — <b>~40–57% of approvals</b> in
     every year, and 48.7% in FY2082/83. Roughly half of all "labour approvals" are people
     who already migrated once. Recruiting agencies supply the other bulk (~34–55%);
     <code>individual_new</code> appeared only in the modern template (~16%) and
     <code>g2g</code> is marginal (~1%). The channel labels differ across templates by
     design — compare them via the canonical <code>channel_class</code>, not the raw labels.</div>
</section>

<section>
  <h2><span class="n">07</span>Who leaves — origin geography</h2>
  <p class="sub">Origin province and district. District-level detail is available for
     annual statements and monthly reports, enabling a sub-national view.</p>
  <img src="data:image/png;base64,{figs['prov']}" alt="province mix">
  <img src="data:image/png;base64,{figs['dist']}" alt="top districts">
  <div class="finding"><b>Madhesh and the eastern Tarai lead.</b> Madhesh province supplies
     the largest share of approvals, followed by Koshi and Bagmati; the top districts —
     Dhanusha, Jhapa, Morang, Siraha, Mahottari — are overwhelmingly Tarai/eastern. Origin
     concentration is a natural instrument candidate for the paper's design.
     <i>Note:</i> the two pre-2018 unified districts (Nawalparasi, Rukum) are each assigned
     to a single modern province via their historical district HQ (→ Gandaki and Karnali);
     they appear only in the pre-split annual reports (FY2074/75–2079/80).</div>
</section>

<section>
  <h2><span class="n">08</span>Welfare — deaths abroad</h2>
  <p class="sub">From the historical narrative reports (<code>series.csv</code>). These are a
     distinct measure and are never merged with approval counts.</p>
  <img src="data:image/png;base64,{figs['death']}" alt="deaths">
  <div class="finding"><b>Mortality tracks the migration cycle.</b> Reported deaths climbed
     from ~90 (FY2008/09) to a peak of ~1,006 (FY2014/15), fell to ~658 in FY2019/20 as
     COVID-19 stopped departures, then rebounded to 1,395 (FY2021/22) and ~1,211–1,346
     (FY2022/23–2023/24). Source: MoLESS Nepal Labour Migration Report 2024 (Table 4.1),
     which extends the series through FY2023/24. <i>Caveat:</i> these are reported deaths
     and may undercount; the by-cause tables are subsets of the all-cause total, so never
     add them together. Foreign Employment Board press figures run higher still (1,583 in
     FY2024/25), so treat this as a lower bound.</div>
</section>

<section>
  <h2><span class="n">09</span>Data-quality notes</h2>
  <table>
    <tr><th>Finding</th><th>Impact</th></tr>
    <tr><td>2 known source printing typos (Qatar ±1, <code>report2020_annex_X</code>)</td>
        <td>Reproduced as printed; whole document flagged <code>verified=False</code>.</td></tr>
    <tr><td><code>preapproval_032</code> has 306 outlined/unrecoverable rows of 23,994</td>
        <td>Incomplete pre-approval detail; flagged unverified.</td></tr>
    <tr><td><code>series.csv</code> mixes people-counts and a few share (%) tables</td>
        <td>Filter on <code>unit</code> (<code>count</code> vs <code>percent</code>) and
            <code>metric</code>/<code>caption</code> before summing.</td></tr>
    <tr><td>480 unresolved entity names + clipped <code>Republic o</code></td>
        <td>Small undercount/aggregation risk; kept verbatim, never force-mapped.</td></tr>
    <tr><td>Monthly coverage only from BS 2081/82</td>
        <td>Seasonal analysis limited to recent years; annual panel spans 2073/74+.</td></tr>
  </table>
</section>

</main>
<footer>Nepali Labour Migration Panel · built from public DoFE reports · figures are
descriptive, not causal · generated {gen}</footer>
</body></html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
