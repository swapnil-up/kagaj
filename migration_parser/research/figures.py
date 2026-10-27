"""Paper-style figures for the Phase 1 migration pattern book."""

from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams["font.family"] = ["Noto Sans Devanagari", "DejaVu Sans"]

INK = "#1f2933"
MUTED = "#7b8794"
GRID = "#e4e7eb"
ACCENT = "#c0392b"
ACCENT2 = "#2b6cb0"
GREEN = "#27ae60"
PALETTE = ["#c0392b", "#e67e22", "#27ae60", "#2980b9", "#8e44ad",
           "#16a085", "#d35400", "#7f8c8d", "#f39c12", "#2c3e50"]


def _style(ax, title: str, ylabel: str | None = None):
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    ax.set_title(title, color=INK, fontsize=10.5, fontweight="bold", loc="left")
    if ylabel:
        ax.set_ylabel(ylabel, color=MUTED, fontsize=8.5)


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _kfmt(value, _pos=None):
    value = float(value)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}k"
    return f"{int(value)}"


def annual_volume(annual: list[dict]) -> str:
    labels = [r["fiscal_year"] for r in annual]
    values = [r["count"] for r in annual]
    colors = [ACCENT if r.get("partial") else ACCENT2 for r in annual]
    fig, ax = plt.subplots(figsize=(8.6, 3.4))
    ax.bar(labels, values, color=colors, width=0.72)
    ax.plot(range(len(values)), values, color=MUTED, lw=1.1, zorder=3)
    for i, value in enumerate(values):
        ax.annotate(_kfmt(value), (i, value), textcoords="offset points",
                    xytext=(0, 4), ha="center", fontsize=7.5, color=INK)
    _style(ax, "Approved labour permits by fiscal year", "approvals")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.yaxis.set_major_formatter(_kfmt)
    return _png(fig)


def concentration(annual: list[dict]) -> str:
    annual = [r for r in annual if not r.get("partial")]
    labels = [r["fiscal_year"] for r in annual]
    hhi = [r["hhi"] for r in annual]
    top10 = [r["top10_share_pct"] for r in annual]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.4, 3.2))
    ax1.plot(labels, hhi, marker="o", color=ACCENT, lw=1.6)
    _style(ax1, "Destination concentration (HHI)", "HHI")
    ax1.set_xticks(range(len(labels)))
    ax1.set_xticklabels(labels, rotation=45, ha="right")
    ax1.set_ylim(bottom=0)
    ax2.plot(labels, top10, marker="o", color=ACCENT2, lw=1.6)
    _style(ax2, "Share of top 10 destinations", "% of approvals")
    ax2.set_xticks(range(len(labels)))
    ax2.set_xticklabels(labels, rotation=45, ha="right")
    ax2.set_ylim(0, 100)
    return _png(fig)


def destination_index(index: dict) -> str:
    years = index["years"]
    fig, ax = plt.subplots(figsize=(8.6, 3.8))
    for name, color in zip(index["series"], PALETTE):
        values = index["series"][name]
        ax.plot(years, values, marker="o", ms=3, lw=1.4, color=color, label=name)
    ax.axhline(100, color=MUTED, lw=0.8, ls="--")
    _style(ax, f"Destination trajectories (index, {index['base']} = 100)",
           "index")
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years, rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=7, ncol=2)
    return _png(fig)


def recovery_scatter(rows: list[dict]) -> str:
    if not rows:
        return ""
    x = [r["pre_share_pct"] for r in rows]
    y = [r["growth_pct"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 4.0))
    ax.scatter(x, y, s=28, color=ACCENT2, alpha=0.85)
    ax.axhline(0, color=MUTED, lw=0.8)
    for row in rows:
        if abs(row["growth_pct"]) > 100 or row["pre_share_pct"] > 20:
            ax.annotate(row["country"], (row["pre_share_pct"], row["growth_pct"]),
                        textcoords="offset points", xytext=(3, 3), fontsize=7,
                        color=INK)
    _style(ax, "Recovery from pre-COVID level", "growth from FY2079/80 (%)")
    ax.set_xlabel("pre-COVID share of approvals (%)", color=MUTED, fontsize=8.5)
    ax.set_xscale("symlog")
    ax.grid(axis="x", color=GRID, lw=0.7)
    return _png(fig)


def female_trend(female: dict) -> str:
    rows = [r for r in female["annual"] if not r.get("partial")]
    labels = [r["fiscal_year"] for r in rows]
    shares = [r["female_share_pct"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 3.2))
    ax.plot(labels, shares, marker="o", color="#c2185b", lw=1.7)
    for i, value in enumerate(shares):
        ax.annotate(f"{value:.1f}%", (i, value), textcoords="offset points",
                    xytext=(0, 5), ha="center", fontsize=7.5, color=INK)
    _style(ax, "Female share of approved permits", "% of approvals")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylim(0, max(shares) * 1.25)
    return _png(fig)


def female_destinations(rows: list[dict]) -> str:
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: r["female_share_pct"])
    fig, ax = plt.subplots(figsize=(8.6, 4.0))
    ax.barh([r["entity"] for r in rows],
            [r["female_share_pct"] for r in rows], color="#c2185b")
    for i, row in enumerate(rows):
        ax.annotate(f"{row['female_share_pct']:.0f}% (n={row['total']:,})",
                    (row["female_share_pct"], i), va="center", xytext=(4, 0),
                    textcoords="offset points", fontsize=7.5, color=INK)
    _style(ax, "Female share by destination, FY2082/83", "% female")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, 100)
    return _png(fig)


def channel_mix(channels: dict) -> str:
    rows = [r for r in channels["by_year"] if not r.get("partial")]
    columns = channels["columns"]
    labels = [r["fiscal_year"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 3.6))
    bottom = pd.Series(0.0, index=range(len(rows)))
    for col, color in zip(columns, PALETTE):
        values = pd.Series([r["channels"].get(col, 0) for r in rows])
        ax.bar(labels, values, bottom=bottom, color=color, label=col, width=0.72)
        bottom = bottom + values
    _style(ax, "Approval-channel composition (% of safe annual approvals)",
           "% of approvals")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, fontsize=7, ncol=3)
    return _png(fig)


def district_concentration(rows: list[dict]) -> str:
    labels = [r["fiscal_year"] for r in rows]
    top10 = [r["top10_share_pct"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 3.2))
    ax.plot(labels, top10, marker="o", color=GREEN, lw=1.7)
    for i, value in enumerate(top10):
        ax.annotate(f"{value:.0f}%", (i, value), textcoords="offset points",
                    xytext=(0, 5), ha="center", fontsize=7.5, color=INK)
    _style(ax, "Origin concentration: top 10 districts", "% of approvals")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylim(0, max(top10) * 1.25)
    return _png(fig)


def district_convergence(points: list[dict], spearman) -> str:
    if not points:
        return ""
    x = [p["initial_share_pct"] for p in points]
    y = [p["growth_pct"] for p in points]
    fig, ax = plt.subplots(figsize=(8.6, 4.0))
    ax.scatter(x, y, s=26, color=GREEN, alpha=0.8)
    ax.axhline(0, color=MUTED, lw=0.8)
    for point in points:
        if point["initial_share_pct"] > 4 or point["growth_pct"] > 300:
            ax.annotate(point["district"], (point["initial_share_pct"],
                                             point["growth_pct"]),
                        textcoords="offset points", xytext=(3, 3), fontsize=7)
    _style(ax, f"District convergence (Spearman = {spearman})",
           "growth FY2074/75 to FY2082/83 (%)")
    ax.set_xlabel("initial share of district approvals (%)", color=MUTED, fontsize=8.5)
    ax.grid(axis="x", color=GRID, lw=0.7)
    return _png(fig)


def monthly_line(rows: list[dict], title: str) -> str:
    if not rows:
        return ""
    dates = pd.to_datetime([r["start"] for r in rows])
    values = [r["count"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 3.3))
    ax.plot(dates, values, marker="o", ms=3, lw=1.5, color=ACCENT2)
    _style(ax, title, "approvals")
    ax.yaxis.set_major_formatter(_kfmt)
    fig.autofmt_xdate(rotation=30)
    return _png(fig)


def archive_line(rows: list[dict]) -> str:
    if not rows:
        return ""
    labels = [r["period_bs"] for r in rows]
    values = [r["count"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 3.4))
    ax.bar(range(len(labels)), values, color=ACCENT2, width=0.72)
    _style(ax, "Archive monthly approvals (selected scope)", "approvals")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=90, fontsize=6)
    ax.yaxis.set_major_formatter(_kfmt)
    return _png(fig)


def deaths_line(rows: list[dict]) -> str:
    if not rows:
        return ""
    labels = [r["fiscal_year"] for r in rows]
    values = [r["deaths"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 3.2))
    ax.plot(labels, values, marker="o", color=ACCENT, lw=1.5)
    for i, value in enumerate(values):
        ax.annotate(str(value), (i, value), textcoords="offset points",
                    xytext=(0, 5), ha="center", fontsize=7, color=INK)
    _style(ax, "Reported deaths of migrant workers", "deaths")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    return _png(fig)


def destination_rank_heatmap(rank_panel: list[dict]) -> str:
    if not rank_panel:
        return ""
    years = [r["fiscal_year"] for r in rank_panel]
    latest = rank_panel[-1]["rows"]
    names = [r["country"] for r in latest[:10]]
    matrix = []
    for name in names:
        row = []
        for panel in rank_panel:
            share = next((x["share_pct"] for x in panel["rows"]
                          if x["country"] == name), 0.0)
            row.append(share)
        matrix.append(row)
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    image = ax.imshow(matrix, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years, rotation=45, ha="right")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            ax.text(j, i, f"{value:.0f}" if value else "–", ha="center",
                    va="center", fontsize=7,
                    color="white" if value > 20 else INK)
    ax.set_title("Destination shares: latest top 10", color=INK, fontsize=10.5,
                 fontweight="bold", loc="left")
    fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02, label="share (%)")
    return _png(fig)


def recovery_waterfall(recovery: dict) -> str:
    rows = recovery.get("top_positive", [])[:8] + recovery.get("top_negative", [])[:1]
    if not rows:
        return ""
    rows = list(reversed(rows))
    labels = [r["country"] for r in rows]
    values = [r["contribution"] for r in rows]
    colors = [GREEN if v >= 0 else ACCENT for v in values]
    fig, ax = plt.subplots(figsize=(8.6, 3.8))
    ax.barh(labels, values, color=colors)
    for i, value in enumerate(values):
        ax.annotate(f"{value:+,}", (value, i), va="center",
                    xytext=(4 if value >= 0 else -4, 0),
                    textcoords="offset points", ha="left" if value >= 0 else "right",
                    fontsize=7.5, color=INK)
    _style(ax, "Contribution to approval growth, FY2079/80 to FY2082/83",
           "change in approvals")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.xaxis.set_major_formatter(_kfmt)
    return _png(fig)


def female_shift_waterfall(shift: dict) -> str:
    labels = ["Within destination", "Destination composition", "Interaction"]
    values = [shift["within_destination_pp"], shift["destination_composition_pp"],
              shift["interaction_residual_pp"]]
    colors = [GREEN if v >= 0 else ACCENT for v in values]
    fig, ax = plt.subplots(figsize=(7.4, 3.1))
    ax.bar(labels, values, color=colors, width=0.6)
    for i, value in enumerate(values):
        ax.annotate(f"{value:+.2f} pp", (i, value), textcoords="offset points",
                    xytext=(0, 4 if value >= 0 else -12), ha="center",
                    fontsize=8, color=INK)
    _style(ax, "Shift-share of the female approval share", "percentage points")
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8)
    return _png(fig)


def destination_female_dumbbell(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: r["latest_total"], reverse=True)[:12]
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: r["latest_female_share_pct"])
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    for i, row in enumerate(rows):
        ax.plot([row["base_female_share_pct"], row["latest_female_share_pct"]],
                [i, i], color=GRID, lw=2)
        ax.scatter(row["base_female_share_pct"], i, color=MUTED, s=28, zorder=3)
        ax.scatter(row["latest_female_share_pct"], i, color="#c2185b", s=32,
                   zorder=4)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r["country"] for r in rows])
    _style(ax, "Female share by destination: base vs latest", "% female")
    ax.set_xlim(left=0)
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    return _png(fig)


def channel_destination_stack(comp: dict) -> str:
    rows = comp.get("top_destinations", [])[:10]
    channels = list(comp.get("channels", ["g2g", "individual_new",
                                          "individual_reentry",
                                          "recruiting_agency"]))
    if not rows:
        return ""
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    labels = [r["country"] for r in rows][::-1]
    bottom = pd.Series(0.0, index=range(len(rows)))
    for col, color in zip(channels, PALETTE):
        values = pd.Series([r["channels"].get(col, {}).get("share_pct", 0)
                            for r in rows][::-1])
        ax.barh(labels, values, left=bottom, color=color, label=col)
        bottom = bottom + values
    _style(ax, "Approval-channel mix by destination, FY2082/83", "% of approvals")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, 100)
    ax.legend(frameon=False, fontsize=7, ncol=3, loc="lower center",
              bbox_to_anchor=(0.5, -0.22))
    return _png(fig)


def district_transition(transitions: dict) -> str:
    deciles = transitions.get("deciles", {})
    shares = deciles.get("shares", [])
    if not shares:
        return ""
    labels = deciles.get("row_labels", [])
    fig, ax = plt.subplots(figsize=(6.4, 5.0))
    image = ax.imshow(shares, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlabel("latest decile", color=MUTED, fontsize=8.5)
    ax.set_ylabel("initial decile", color=MUTED, fontsize=8.5)
    for i, row in enumerate(shares):
        for j, value in enumerate(row):
            if value >= 0.1:
                ax.text(j, i, f"{value:.0%}", ha="center", va="center",
                        fontsize=6.5,
                        color="white" if value > 0.55 else INK)
    ax.set_title("District decile transition, FY2074/75 to FY2082/83",
                 color=INK, fontsize=10, fontweight="bold", loc="left")
    fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02, label="row share")
    return _png(fig)


def province_change(change: list[dict]) -> str:
    if not change:
        return ""
    rows = sorted(change, key=lambda r: r["share_change_pp"])
    fig, ax = plt.subplots(figsize=(8.6, 3.4))
    values = [r["share_change_pp"] for r in rows]
    colors = [GREEN if v >= 0 else ACCENT for v in values]
    ax.barh([r["province"].title() for r in rows], values, color=colors)
    for i, value in enumerate(values):
        ax.annotate(f"{value:+.1f} pp", (value, i), va="center",
                    xytext=(4 if value >= 0 else -4, 0),
                    textcoords="offset points", ha="left" if value >= 0 else "right",
                    fontsize=7.5)
    _style(ax, "Province share change, FY2074/75 to FY2082/83",
           "percentage points")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    ax.axvline(0, color=MUTED, lw=0.8)
    return _png(fig)


def modern_seasonality(season: dict) -> str:
    rows = season.get("monthly", [])
    if not rows:
        return ""
    labels = [r["bs_month"] for r in rows]
    counts = [r["count"] for r in rows]
    indices = [r["index"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 3.4))
    ax.bar(labels, counts, color=ACCENT2, width=0.72)
    ax2 = ax.twinx()
    ax2.plot(labels, indices, color=ACCENT, marker="o", lw=1.3)
    ax2.axhline(100, color=MUTED, lw=0.8, ls="--")
    _style(ax, "Monthly approvals and seasonal index, FY2082/83", "approvals")
    ax.yaxis.set_major_formatter(_kfmt)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax2.set_ylabel("index (year mean = 100)", color=MUTED, fontsize=8.5)
    ax2.tick_params(colors=MUTED, labelsize=8)
    return _png(fig)


def archive_coverage_heatmap(coverage: dict) -> str:
    years = coverage.get("years", [])
    if not years:
        return ""
    months = ["Baishakh", "Jestha", "Ashar", "Shrawan", "Bhadra", "Ashwin",
              "Kartik", "Mangsir", "Poush", "Magh", "Falgun", "Chaitra"]
    month_index = {name: i for i, name in enumerate(months)}
    matrix = [[0 for _ in months] for _ in years]
    for i, year in enumerate(years):
        for period in year.get("periods", []):
            j = month_index.get(period.get("bs_month"))
            if j is not None:
                matrix[i][j] = 2 if period.get("scope") == "final_approved" else 1
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    from matplotlib.colors import ListedColormap
    image = ax.imshow(matrix, aspect="auto",
                      cmap=ListedColormap(["#f5f6f8", "#9ecae1", "#2b6cb0"]),
                      vmin=0, vmax=2)
    ax.set_xticks(range(len(months)))
    ax.set_xticklabels(months, rotation=45, ha="right")
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels([str(y["bs_year"]) for y in years])
    ax.set_title("Archive monthly coverage (blue = final_approved, light = month)",
                 color=INK, fontsize=10, fontweight="bold", loc="left")
    return _png(fig)


def break_scan(breaks: dict) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.4))
    for ax, key, color in zip(axes, ("annual_approvals", "destination_hhi"),
                              (ACCENT2, ACCENT)):
        block = breaks.get(key, {})
        rows = block.get("series", [])
        if not rows:
            continue
        labels = [r["fiscal_year"] for r in rows]
        values = [r["count"] if key == "annual_approvals" else r["hhi"]
                  for r in rows]
        ax.plot(labels, values, marker="o", color=color, lw=1.5)
        best = block.get("best")
        if best:
            split = best["split_after"]
            if split in labels:
                idx = labels.index(split)
                ax.axvline(idx + 0.5, color=MUTED, lw=0.8, ls="--")
        _style(ax, "Annual approvals" if key == "annual_approvals"
               else "Destination HHI", "approvals" if key == "annual_approvals"
               else "HHI")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
        if key == "annual_approvals":
            ax.yaxis.set_major_formatter(_kfmt)
    return _png(fig)


def deaths_rate(rows: list[dict]) -> str:
    if not rows:
        return ""
    labels = [r["approx_bs_fiscal_year"] for r in rows]
    values = [r["deaths_per_100k"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 3.2))
    ax.plot(labels, values, marker="o", color=ACCENT, lw=1.5)
    for i, value in enumerate(values):
        ax.annotate(f"{value:.0f}", (i, value), textcoords="offset points",
                    xytext=(0, 5), ha="center", fontsize=7)
    _style(ax, "Reported deaths per 100,000 safe approvals", "deaths per 100k")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    return _png(fig)


def safe_permissive_delta(delta: dict) -> str:
    shares = delta.get("annual_total_share_of_safe_pct", {})
    if not shares:
        return ""
    labels = list(shares)
    values = list(shares.values())
    fig, ax = plt.subplots(figsize=(8.6, 3.2))
    ax.bar(labels, values, color=[ACCENT if v > 5 else ACCENT2 for v in values],
           width=0.72)
    _style(ax, "Permissive-minus-safe annual total", "% of safe total")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    return _png(fig)


def new_reentry_trend(annual: list[dict]) -> str:
    rows = [r for r in annual if r["fiscal_year"] != "2083/84"]
    labels = [r["fiscal_year"] for r in rows]
    new = [r["new_share_pct"] if r.get("new_reported") else None for r in rows]
    reentry = [r["reentry_share_pct"] if r.get("reentry_reported") else None
               for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 3.4))
    ax.plot(range(len(rows)), new, marker="o", color=ACCENT2, lw=1.7,
            label="individual_new")
    ax.plot(range(len(rows)), reentry, marker="o", color=ACCENT, lw=1.7,
            label="individual_reentry")
    _style(ax, "New vs re-entry share of all approvals", "% of approvals")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    return _png(fig)


def new_reentry_country_scatter(rows: list[dict]) -> str:
    data = [r for r in rows if r.get("total_growth_pct") is not None]
    if not data:
        return ""
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    sizes = [max(12, min(220, r["latest_total"] / 2500)) for r in data]
    colors = [ACCENT if r["reentry_share_latest_pct"] >= 50 else ACCENT2
              for r in data]
    ax.scatter([r["total_growth_pct"] for r in data],
               [r["reentry_share_latest_pct"] for r in data],
               s=sizes, color=colors, alpha=0.75)
    for r in data:
        if r["latest_total"] >= 40000 or abs(r["total_growth_pct"]) >= 300:
            ax.annotate(r["country"],
                        (r["total_growth_pct"], r["reentry_share_latest_pct"]),
                        textcoords="offset points", xytext=(3, 3),
                        fontsize=7, color=INK)
    ax.axhline(50, color=MUTED, lw=0.8, ls="--")
    _style(ax, "Re-entry orientation vs destination growth",
           "re-entry share, FY2082/83 (%)")
    ax.set_xlabel("total growth from FY2079/80 (%)", color=MUTED, fontsize=8.5)
    ax.grid(axis="x", color=GRID, lw=0.7)
    return _png(fig)


def new_reentry_top_trajectories(top: dict) -> str:
    destinations = top.get("destinations", [])[:8]
    if not destinations:
        return ""
    fig, ax = plt.subplots(figsize=(8.6, 4.0))
    years = top.get("years", [])
    for row, color in zip(destinations, PALETTE):
        points = {p["fiscal_year"]: p["reentry_share_pct"]
                  for p in row["series"]}
        values = [points.get(fy) for fy in years]
        ax.plot(range(len(years)), values, marker="o", ms=3, lw=1.3,
                color=color, label=row["country"])
    _style(ax, "Re-entry share in the largest destinations",
           "re-entry share (%)")
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years, rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=7, ncol=2)
    return _png(fig)


def gender_country_dumbbell(country_deep: dict) -> str:
    rows = [r for r in country_deep["destinations"]
            if r.get("base_above_threshold")]
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: abs(r["female_share_change_pp"]),
                  reverse=True)[:16]
    rows = sorted(rows, key=lambda r: r["latest_female_share_pct"])
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    for i, row in enumerate(rows):
        base = row["base_female_share_pct"]
        latest = row["latest_female_share_pct"]
        ax.plot([base, latest], [i, i], color=GRID, lw=2.5, zorder=1)
        ax.scatter([base], [i], color=MUTED, s=24, zorder=2)
        ax.scatter([latest], [i], color="#c2185b", s=28, zorder=3)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r["country"] for r in rows], fontsize=7.5)
    _style(ax, "Female share by destination: FY2079/80 vs FY2082/83",
           "% female")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, 100)
    return _png(fig)


def gender_country_convergence(conv: dict) -> str:
    pairs = conv.get("pairs", [])
    if not pairs:
        return ""
    x = [r["base_female_share_pct"] for r in pairs]
    y = [r["change_pp"] for r in pairs]
    fig, ax = plt.subplots(figsize=(8.6, 4.0))
    ax.scatter(x, y, s=28, color="#c2185b", alpha=0.8)
    slope = conv["slope_pp_per_initial_pp"]
    intercept = conv["intercept_pp"]
    xs = [0, 100]
    ax.plot(xs, [intercept + slope * v for v in xs], color=ACCENT2, lw=1.4)
    for r in pairs:
        if abs(r["change_pp"]) >= 20 or r["latest_female_share_pct"] >= 60:
            ax.annotate(r["country"],
                        (r["base_female_share_pct"], r["change_pp"]),
                        textcoords="offset points", xytext=(3, 3),
                        fontsize=7, color=INK)
    ax.axhline(0, color=MUTED, lw=0.8)
    _style(ax, "Female-share convergence across destinations",
           "change in female share (pp)")
    ax.set_xlabel("initial female share, FY2079/80 (%)", color=MUTED,
                  fontsize=8.5)
    ax.grid(axis="x", color=GRID, lw=0.7)
    return _png(fig)


def gender_channel_gap_trend(annual: list[dict]) -> str:
    rows = [r for r in annual if r["fiscal_year"] != "2083/84"]
    labels = [r["fiscal_year"] for r in rows]
    new = [r["channels"]["individual_new"]["female_share_pct"]
           if r["channels"]["individual_new"]["reported"] else None
           for r in rows]
    reentry = [r["channels"]["individual_reentry"]["female_share_pct"]
               if r["channels"]["individual_reentry"]["reported"] else None
               for r in rows]
    fig, ax = plt.subplots(figsize=(8.6, 3.4))
    ax.plot(range(len(rows)), new, marker="o", color=ACCENT2, lw=1.7,
            label="individual_new")
    ax.plot(range(len(rows)), reentry, marker="o", color=ACCENT, lw=1.7,
            label="individual_reentry")
    _style(ax, "Female share within new and re-entry channels", "% female")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    return _png(fig)


def reentry_gender_gap_country(country_table: dict) -> str:
    rows = [r for r in country_table["destinations"]
            if r.get("new_to_reentry_female_gap_pp") is not None]
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: abs(r["new_to_reentry_female_gap_pp"]),
                  reverse=True)[:16]
    rows = sorted(rows, key=lambda r: r["new_to_reentry_female_gap_pp"])
    values = [r["new_to_reentry_female_gap_pp"] for r in rows]
    colors = [ACCENT2 if v >= 0 else ACCENT for v in values]
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    ax.barh([r["country"] for r in rows], values, color=colors)
    ax.axvline(0, color=MUTED, lw=0.8)
    for i, value in enumerate(values):
        ax.annotate(f"{value:+.1f}", (value, i), va="center",
                    xytext=(4 if value >= 0 else -4, 0),
                    textcoords="offset points", ha="left" if value >= 0 else "right",
                    fontsize=7, color=INK)
    _style(ax, "New minus re-entry female share by destination, FY2082/83",
           "percentage points")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    return _png(fig)


def reentry_gender_decomposition(decomp: dict) -> str:
    blocks = [("new + re-entry", decomp.get("new_reentry")),
              ("all four channels", decomp.get("four_channel"))]
    blocks = [(label, block) for label, block in blocks if block]
    if not blocks:
        return ""
    keys = (("within_channel_pp", "within"),
            ("channel_composition_pp", "composition"),
            ("interaction_residual_pp", "interaction"))
    fig, ax = plt.subplots(figsize=(8.6, 3.6))
    width = 0.8 / len(keys)
    for i, (_, block) in enumerate(blocks):
        for j, (key, label) in enumerate(keys):
            ax.bar(i + (j - 1) * width, block[key], width=width,
                   color=PALETTE[j], label=label if i == 0 else None)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_xticks(range(len(blocks)))
    ax.set_xticklabels([b[0] for b in blocks])
    _style(ax, "Female-share change decomposition (pp)", "contribution (pp)")
    ax.legend(frameon=False, fontsize=7, ncol=3)
    return _png(fig)


def outcome_volume(rows: list[dict]) -> str:
    rows = [r for r in rows if not r.get("partial")]
    labels = [r["fiscal_year"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.8, 3.6))
    for key, label, color in (
            ("total_verified", "total verified", ACCENT),
            ("deployment_verified", "deployment (excl. legalization)", ACCENT2),
            ("reviewed_channels", "reviewed channels", GREEN)):
        ax.plot(labels, [r[key] for r in rows], marker="o", ms=3, lw=1.5,
                color=color, label=label)
    _style(ax, "Explicit approval denominators", "approvals")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.yaxis.set_major_formatter(_kfmt)
    ax.legend(frameon=False, fontsize=7.5, ncol=1)
    return _png(fig)


def reviewed_share(rows: list[dict]) -> str:
    rows = [r for r in rows if not r.get("partial")]
    labels = [r["fiscal_year"] for r in rows]
    values = [r["reviewed_share_of_total_pct"] for r in rows]
    fig, ax = plt.subplots(figsize=(8.8, 3.2))
    ax.bar(labels, values, color=[ACCENT if v < 95 else ACCENT2 for v in values],
           width=0.72)
    for i, value in enumerate(values):
        ax.annotate(f"{value:.1f}%", (i, value), textcoords="offset points",
                    xytext=(0, 4), ha="center", fontsize=7.5, color=INK)
    _style(ax, "Reviewed-channel share of total verified approvals",
           "% of total")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylim(0, 105)
    return _png(fig)


def growth_denominator_scatter(rows: list[dict]) -> str:
    data = [r for r in rows
            if r.get("deployment_growth_pct") is not None
            and r.get("reviewed_growth_pct") is not None]
    if not data:
        return ""
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    sizes = [max(12, min(220, r["latest_deployment_verified"] / 2500))
             for r in data]
    colors = [ACCENT if (r["sign_flip"] or r["small_base"]) else ACCENT2
              for r in data]
    ax.scatter([r["deployment_growth_pct"] for r in data],
               [r["reviewed_growth_pct"] for r in data],
               s=sizes, color=colors, alpha=0.75)
    lo = min(min(r["deployment_growth_pct"], r["reviewed_growth_pct"])
             for r in data)
    hi = max(max(r["deployment_growth_pct"], r["reviewed_growth_pct"])
             for r in data)
    ax.plot([lo, hi], [lo, hi], color=MUTED, lw=0.8, ls="--")
    ax.set_xscale("symlog", linthresh=100)
    ax.set_yscale("symlog", linthresh=100)
    for r in data:
        if r["small_base"] or r["sign_flip"] or r["latest_deployment_verified"] >= 40000:
            ax.annotate(r["country"],
                        (r["deployment_growth_pct"], r["reviewed_growth_pct"]),
                        textcoords="offset points", xytext=(3, 3),
                        fontsize=7, color=INK)
    _style(ax, "Country growth: deployment vs reviewed-channel denominator",
           "reviewed-channel growth (%)")
    ax.set_xlabel("deployment growth from FY2079/80 (%)", color=MUTED,
                  fontsize=8.5)
    ax.grid(axis="x", color=GRID, lw=0.7)
    return _png(fig)


def deployment_recovery_scatter(rows: list[dict]) -> str:
    data = [r for r in rows if r["base_deployment_verified"] > 0]
    if not data:
        return ""
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    sizes = [max(12, min(220, r["latest_deployment_verified"] / 2500))
             for r in data]
    colors = [ACCENT if r["small_base"] else ACCENT2 for r in data]
    ax.scatter([r["base_deployment_verified"] for r in data],
               [r["deployment_growth_pct"] for r in data],
               s=sizes, color=colors, alpha=0.75)
    ax.axhline(0, color=MUTED, lw=0.8)
    for r in data:
        if r["small_base"] or r["latest_deployment_verified"] >= 40000:
            ax.annotate(r["country"],
                        (r["base_deployment_verified"],
                         r["deployment_growth_pct"]),
                        textcoords="offset points", xytext=(3, 3),
                        fontsize=7, color=INK)
    _style(ax, "Deployment-verified recovery from FY2079/80",
           "deployment growth (%)")
    ax.set_xlabel("base deployment approvals", color=MUTED, fontsize=8.5)
    ax.set_xscale("symlog", linthresh=100)
    ax.grid(axis="x", color=GRID, lw=0.7)
    return _png(fig)
