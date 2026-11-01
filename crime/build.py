"""Aggregate parsed bulletins into the committed crime dataset."""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .schema import MONTH_NAMES, OFFENSES, fiscal_year  # noqa: E402
from .scrape import PDF_DIR, load_manifest, sha256  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PARSED = ROOT / "output" / "crime" / "parsed"
OUT = ROOT / "datasets" / "crime"
CHARTS = OUT / "charts"

HEINOUS_CORE = ["murder", "trafficking", "rape", "kidnapping"]
SERIOUS_CORE = [
    "attempted_murder", "suicide_abetment", "abortion",
    "dacoity", "burglary", "assault",
]
VALLEY = "kathmandu_valley"


def _git_revision() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def load_parsed() -> list[dict]:
    rows = []
    for path in sorted(PARSED.glob("*.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def derive_cumulative(violent: pd.DataFrame) -> pd.DataFrame:
    keys = ["chart_kind", "offense", "province"]
    cumulative = {
        month: frame
        for month, frame in violent[violent["basis"] == "cumulative"].groupby("month")
    }
    monthly = {
        month: frame
        for month, frame in violent[violent["basis"].isin(["monthly", "derived"])].groupby("month")
    }
    derived = []
    windows = violent[violent["basis"] == "cumulative"].groupby("window")
    for _, frame in windows:
        previous = None
        previous_window = None
        for month in sorted(frame["month"].unique()):
            current = frame[frame["month"] == month]
            window = current["window"].iloc[0]
            if previous is not None and previous_window == window:
                base = previous
            else:
                base = monthly.get(_prev_month(month))
            if base is None:
                previous, previous_window = current, window
                continue
            merged = current.merge(base, on=keys, how="left", suffixes=("", "_prev"))
            if merged["value_prev"].isna().any():
                previous, previous_window = current, window
                continue
            merged["value"] = merged["value"] - merged["value_prev"]
            merged["month"] = month
            merged["fy"] = fiscal_year(int(month[:4]), int(month[5:7]))
            merged["basis"] = "derived"
            merged["method"] = "cumulative_difference"
            merged["confidence"] = "high"
            derived.append(merged[current.columns])
            monthly[month] = merged[current.columns]
            previous, previous_window = current, window
    if not derived:
        return violent.iloc[0:0].copy()
    return pd.concat(derived, ignore_index=True)


def _prev_month(month: str) -> str:
    year, number = int(month[:4]), int(month[5:7])
    if number == 1:
        return f"{year - 1}-12"
    return f"{year}-{number - 1:02d}"


def build_frames(parsed: list[dict]) -> dict[str, pd.DataFrame]:
    violent_rows = []
    total_rows = []
    annual_rows = []
    for bulletin in parsed:
        issue = bulletin["issue"]
        for rec in bulletin["violent"]:
            rec.setdefault("method", "chart_labels")
            rec.setdefault("confidence", "high")
            violent_rows.append(rec)
        for rec in bulletin["monthly_totals"]:
            total_rows.append(rec)
        for rec in bulletin["annual"]:
            annual_rows.append(rec)

    violent = pd.DataFrame(violent_rows)
    totals = pd.DataFrame(total_rows)
    if not totals.empty:
        totals = (
            totals.sort_values("as_of")
            .drop_duplicates(subset=["month", "province"], keep="first")
            .reset_index(drop=True)
        )
    annual = pd.DataFrame(annual_rows)

    derived = derive_cumulative(violent)
    if not derived.empty:
        violent = pd.concat([violent, derived], ignore_index=True)
    violent = violent[violent["basis"].isin(["monthly", "derived"])].copy()

    violent["offense_en"] = violent["offense"].map(lambda k: OFFENSES[k][0])
    violent["ex_valley"] = violent["province"] != VALLEY

    national = (
        violent.groupby(["month", "fy", "offense", "offense_en", "chart_kind"], as_index=False)
        .agg(
            value=("value", "sum"),
            provinces_reported=("province", "nunique"),
            value_ex_valley=("value", lambda s: s[violent.loc[s.index, "ex_valley"]].sum()),
            basis=("basis", lambda s: "+".join(sorted(set(s)))),
            method=("method", lambda s: "+".join(sorted(set(s)))),
            categories_reported=("offense", "nunique"),
        )
    )
    national["categories_expected"] = national["chart_kind"].map(
        {"heinous": len(HEINOUS_CORE), "serious": len(SERIOUS_CORE)}
    )
    national["complete_categories"] = (
        national["categories_reported"] == national["categories_expected"]
    )
    return {
        "violent": violent,
        "national": national,
        "totals": totals,
        "annual": annual,
        "totals_raw": pd.DataFrame(total_rows),
        "national_raw": pd.DataFrame(
            [rec for bulletin in parsed for rec in bulletin.get("national_totals", [])]
        ),
        "annual_raw": pd.DataFrame(annual_rows),
    }


def complete_annual(annual: pd.DataFrame) -> pd.DataFrame:
    if annual.empty:
        return annual
    annual = annual.dropna(subset=["value"]).copy()
    annual["end_year"] = annual["fy"].str.slice(5, 9).astype(int)
    annual["end_ym"] = annual["end_year"] * 12 + 3
    annual["as_of_ym"] = annual["as_of"].str.slice(0, 4).astype(int) * 12 + annual["as_of"].str.slice(5, 7).astype(int)
    annual["complete"] = annual["as_of_ym"] >= annual["end_ym"] + 1
    annual = annual.sort_values("as_of_ym")
    latest_as_of = annual.groupby("fy")["as_of_ym"].transform("max")
    latest = annual[annual["as_of_ym"] == latest_as_of]
    latest = latest.drop_duplicates(subset=["fy", "series"], keep="last")
    return latest.drop(columns=["end_year", "end_ym", "as_of_ym"]).sort_values(["fy", "series"])


def build_revisions(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    totals = frames["totals_raw"]
    if totals.empty:
        total_rev = pd.DataFrame(
            columns=["month", "province", "observations", "as_of_first", "as_of_last",
                     "values", "differs"]
        )
    else:
        def joined(series: pd.Series) -> str:
            return ";".join(str(v) for v in sorted(series.unique()))

        total_rev = (
            totals.groupby(["month", "province"], as_index=False)
            .agg(
                observations=("value", "size"),
                as_of_first=("as_of", "min"),
                as_of_last=("as_of", "max"),
                values=("value", joined),
                distinct=("value", "nunique"),
            )
        )
        total_rev["differs"] = total_rev["distinct"] > 1
        total_rev = total_rev.drop(columns=["distinct"])

    annual = frames["annual_raw"]
    if annual.empty:
        annual_rev = pd.DataFrame(
            columns=["fy", "series", "observations", "as_of_first", "as_of_last",
                     "values", "differs"]
        )
    else:
        def joined_annual(series: pd.Series) -> str:
            return ";".join(str(int(v)) for v in sorted(series.dropna().unique()))

        annual_rev = (
            annual.dropna(subset=["value"])
            .groupby(["fy", "series"], as_index=False)
            .agg(
                observations=("value", "size"),
                as_of_first=("as_of", "min"),
                as_of_last=("as_of", "max"),
                values=("value", joined_annual),
                distinct=("value", "nunique"),
            )
        )
        annual_rev["differs"] = annual_rev["distinct"] > 1
        annual_rev = annual_rev.drop(columns=["distinct"])
    return total_rev, annual_rev


def build_national_totals(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    totals = frames["totals"]
    province = (
        totals.groupby("month", as_index=False)
        .agg(
            fy=("fy", "first"),
            value=("value", "sum"),
            as_of=("as_of", "min"),
            issue_no=("issue_no", "first"),
            source_url=("source_url", "first"),
        )
    )
    province["method"] = "province_sum"
    line = frames["national_raw"]
    if line.empty:
        line = province.iloc[0:0].copy()
    else:
        line = (
            line.sort_values("as_of")
            .drop_duplicates(subset=["month"], keep="first")
            [["month", "fy", "value", "as_of", "method", "issue_no", "source_url"]]
        )
        line = line[~line["month"].isin(province["month"])]
    national = pd.concat([province, line], ignore_index=True)
    return national.sort_values("month").reset_index(drop=True)


def build_national_revisions(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    totals = frames["totals"]
    province = totals.groupby("month", as_index=False).agg(value=("value", "sum"))
    province["source"] = "province_sum"
    line = frames["national_raw"]
    if line.empty:
        line = province.iloc[0:0].copy()
    else:
        line = line[["month", "value"]].copy()
        line["source"] = "line_labels"
    observations = pd.concat([province[["month", "value", "source"]], line], ignore_index=True)
    rows = []
    for month, group in observations.groupby("month"):
        values = sorted(group["value"].unique())
        rows.append(
            {
                "month": month,
                "sources": ";".join(sorted(group["source"].unique())),
                "values": ";".join(str(int(v)) for v in values),
                "differs": len(values) > 1,
            }
        )
    return pd.DataFrame(rows).sort_values("month")


def build_coverage(violent: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    coverage = (
        violent.groupby(["month", "fy", "chart_kind", "offense", "offense_en"], as_index=False)
        .agg(provinces_reported=("province", "nunique"), value=("value", "sum"))
    )
    coverage["reported"] = True

    availability = (
        violent.groupby(["chart_kind", "offense", "offense_en"], as_index=False)
        .agg(
            months_reported=("month", "nunique"),
            first_month=("month", "min"),
            last_month=("month", "max"),
            provinces_reported=("province", "nunique"),
        )
    )

    status = (
        violent.groupby(["month", "fy", "chart_kind"], as_index=False)
        .agg(
            offenses_reported=("offense", "nunique"),
            provinces_reported=("province", "nunique"),
            rows=("value", "size"),
            basis=("basis", lambda s: "+".join(sorted(set(s)))),
            method=("method", lambda s: "+".join(sorted(set(s)))),
        )
    )
    status["partial_chart"] = status["offenses_reported"] <= 1
    return (
        coverage.sort_values(["month", "chart_kind", "offense"]),
        status.sort_values(["month", "chart_kind"]),
        availability.sort_values(["chart_kind", "offense"]),
    )


def _save_gz(frame: pd.DataFrame, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        frame.to_csv(handle, index=False)
    return path


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "legend.frameon": False,
            "figure.facecolor": "white",
        }
    )


def chart_annual(annual: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    fys = [fy for fy in sorted(annual["fy"].unique()) if fy >= "2075/76"]
    x = range(len(fys))
    width = 0.26
    series = [("registered", "Cases registered", "#1f3b73", -width),
              ("disposed", "Cases disposed", "#c84b31", 0.0)]
    for key, label, color, offset in series:
        subset = annual[annual["series"] == key].set_index("fy").reindex(fys)
        if subset["value"].isna().all():
            continue
        bars = ax.bar(
            [i + offset for i in x],
            subset["value"],
            width=width,
            color=color,
            label=label,
        )
        for i, (bar, complete) in enumerate(zip(bars, subset["complete"])):
            if not bool(complete) and pd.notna(complete):
                bar.set_hatch("//")
                bar.set_alpha(0.55)
    ax.set_xticks(list(x), fys)
    ax.set_ylabel("Cases")
    ax.set_title("Nepal Police: total cases registered and disposed, by fiscal year")
    ax.legend(loc="upper left", ncol=3)
    ax.margins(x=0.02)
    fig.text(
        0.01, 0.01,
        "Fiscal year runs Shrawan–Ashad. Each year uses the latest bulletin that reports it.\n"
        "Faded bars mark years not yet complete at that bulletin's cut-off.",
        fontsize=7, color="#555",
    )
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    path = CHARTS / "annual_totals.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_monthly(national: pd.DataFrame, offenses: list[str], title: str, name: str) -> Path:
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    colors = ["#1f3b73", "#c84b31", "#2e7d32", "#6a1b9a", "#ef6c00", "#00838f"]
    plot = national.assign(plot_month=pd.to_datetime(national["month"] + "-01"))
    months = pd.date_range(plot["plot_month"].min(), plot["plot_month"].max(), freq="MS")
    for idx, offense in enumerate(offenses):
        subset = (
            plot[plot["offense"] == offense]
            .set_index("plot_month")["value_ex_valley"]
            .reindex(months)
        )
        if subset.notna().sum() == 0:
            continue
        ax.plot(
            months,
            subset,
            marker="o",
            markersize=2.5,
            linewidth=1.5,
            color=colors[idx % len(colors)],
            label=OFFENSES[offense][0],
        )
    ax.set_title(title)
    ax.set_ylabel("Cases (excl. Kathmandu Valley)")
    ax.legend(loc="upper left", ncol=3, fontsize=8)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    ax.margins(x=0.01)
    fig.tight_layout()
    path = CHARTS / name
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_fy_violent(national: pd.DataFrame) -> Path:
    core = HEINOUS_CORE + SERIOUS_CORE
    subset = national[national["offense"].isin(core)].copy()
    grouped = (
        subset.groupby(["fy", "offense"], as_index=False)
        .agg(value=("value_ex_valley", "sum"), months=("month", "nunique"))
    )
    months_by_fy = subset.groupby("fy")["month"].nunique().to_dict()
    fys = sorted(grouped["fy"].unique())
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    bottom = [0] * len(fys)
    colors = ["#1f3b73", "#5c6bc0", "#c84b31", "#ef6c00", "#6a1b9a",
              "#2e7d32", "#00838f", "#b71c1c", "#4e342e", "#7b1fa2"]
    for idx, offense in enumerate(core):
        values = (
            grouped[grouped["offense"] == offense].set_index("fy").reindex(fys)["value"].fillna(0)
        )
        bars = ax.bar(fys, values, bottom=bottom, color=colors[idx],
                      label=OFFENSES[offense][0], width=0.62)
        for bar, fy in zip(bars, fys):
            if months_by_fy.get(fy, 0) < 12:
                bar.set_alpha(0.45)
        bottom = [b + v for b, v in zip(bottom, values)]
    for i, fy in enumerate(fys):
        ax.text(i, bottom[i] + 40, f"{months_by_fy.get(fy, 0)}/12", ha="center", fontsize=7, color="#555")
    ax.set_ylabel("Cases (excl. Kathmandu Valley)")
    ax.set_title("Reported violent crime by fiscal year (sum of monthly charts)")
    ax.set_ylim(0, max(bottom) * 1.18)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.10), ncol=5, fontsize=7.5)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    fig.text(
        0.01, 0.01,
        "Figures above bars show months with data out of 12; faded years are incomplete. "
        "Kathmandu Valley excluded.",
        fontsize=7, color="#555",
    )
    fig.tight_layout(rect=(0, 0.10, 1, 1))
    path = CHARTS / "violent_by_fiscal_year.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_total_cases(totals: pd.DataFrame) -> Path:
    national = totals.assign(plot_month=pd.to_datetime(totals["month"] + "-01"))
    national = national.groupby("plot_month", as_index=False)["value"].sum().sort_values("plot_month")
    months = pd.date_range(national["plot_month"].min(), national["plot_month"].max(), freq="MS")
    values = national.set_index("plot_month")["value"].reindex(months)
    fig, ax = plt.subplots(figsize=(8.6, 3.7))
    ax.plot(months, values, color="#1f3b73", linewidth=1.6)
    ax.set_title("Total cases registered nationwide, by month")
    ax.set_ylabel("Cases")
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    fig.text(
        0.01, 0.01,
        "Source: CID monthly bulletins. Province totals used where available; 9 months read from quarterly line charts.",
        fontsize=7, color="#555",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    path = CHARTS / "total_cases_monthly.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def build() -> dict:
    _style()
    parsed = load_parsed()
    frames = build_frames(parsed)
    violent = frames["violent"]
    national = frames["national"]
    totals = frames["totals"]
    national_totals = build_national_totals(frames)
    annual = complete_annual(frames["annual"])

    violent_cols = [
        "month", "fy", "chart_kind", "offense", "offense_en", "province", "value",
        "basis", "method", "confidence", "issue_no", "page", "source_url",
    ]
    _save_gz(violent[violent_cols].sort_values(["month", "chart_kind", "offense", "province"]),
             "violent_monthly.csv.gz")
    _save_gz(
        national[["month", "fy", "chart_kind", "offense", "offense_en", "value",
                  "value_ex_valley", "provinces_reported", "categories_reported",
                  "categories_expected", "complete_categories", "basis", "method"]]
        .sort_values(["month", "chart_kind", "offense"]),
        "violent_national.csv.gz",
    )
    _save_gz(
        totals[["month", "fy", "province", "value", "as_of", "issue_no", "source_url"]]
        .sort_values(["month", "province"]),
        "total_cases_monthly.csv.gz",
    )
    _save_gz(
        national_totals[["month", "fy", "value", "as_of", "method", "issue_no", "source_url"]],
        "total_cases_national.csv.gz",
    )
    annual_path = OUT / "annual_totals.csv"
    annual[["fy", "series", "value", "as_of", "complete", "n_series", "source_url"]].to_csv(
        annual_path, index=False
    )

    fy = (
        national[national["offense"].isin(HEINOUS_CORE + SERIOUS_CORE)]
        .groupby(["fy", "chart_kind", "offense", "offense_en"], as_index=False)
        .agg(value=("value_ex_valley", "sum"), months_reported=("month", "nunique"))
    )
    _save_gz(fy.sort_values(["fy", "chart_kind", "offense"]), "violent_by_fy.csv.gz")

    coverage, status, availability = build_coverage(violent)
    _save_gz(coverage, "category_coverage.csv.gz")
    _save_gz(status, "month_status.csv.gz")
    _save_gz(availability, "offense_availability.csv.gz")
    total_rev, annual_rev = build_revisions(frames)
    _save_gz(total_rev, "total_case_revisions.csv.gz")
    annual_rev.to_csv(OUT / "annual_revisions.csv", index=False)
    national_rev = build_national_revisions(frames)
    _save_gz(national_rev, "national_total_revisions.csv.gz")

    population = pd.read_csv(OUT / "population_nepal.csv", dtype={"fy": str})
    rates = (
        annual[annual["series"] == "registered"][["fy", "value", "complete"]]
        .rename(columns={"value": "registered_cases"})
        .merge(population[["fy", "population", "source"]], on="fy", how="left")
    )
    rates["registered_per_100k"] = (
        rates["registered_cases"] / rates["population"] * 100_000
    ).round(1)
    rates.to_csv(OUT / "annual_rates.csv", index=False)

    CHARTS.mkdir(parents=True, exist_ok=True)
    chart_annual(annual)
    chart_monthly(national, HEINOUS_CORE, "Heinous crimes reported per month", "heinous_monthly.png")
    chart_monthly(national, SERIOUS_CORE, "Serious crimes reported per month", "serious_monthly.png")
    chart_fy_violent(national)
    if not national_totals.empty:
        chart_total_cases(national_totals)

    artifacts = [
        "violent_monthly.csv.gz", "violent_national.csv.gz", "violent_by_fy.csv.gz",
        "total_cases_monthly.csv.gz", "total_cases_national.csv.gz", "annual_totals.csv",
        "category_coverage.csv.gz", "month_status.csv.gz", "offense_availability.csv.gz",
        "total_case_revisions.csv.gz", "national_total_revisions.csv.gz", "annual_revisions.csv",
        "population_nepal.csv", "annual_rates.csv",
        "charts/annual_totals.png", "charts/heinous_monthly.png",
        "charts/serious_monthly.png", "charts/violent_by_fiscal_year.png",
        "charts/total_cases_monthly.png",
    ]
    manifest = {row["month_key"]: row for row in load_manifest()}
    build_info = {
        "git_revision": _git_revision(),
        "bulletins_parsed": len(parsed),
        "months_with_violent": int(violent["month"].nunique()),
        "months_with_totals": int(totals["month"].nunique()) if not totals.empty else 0,
        "months_with_national_totals": int(national_totals["month"].nunique()),
        "violent_rows": int(len(violent)),
        "fiscal_years": sorted(annual["fy"].unique().tolist()),
        "caveats": [
            "Kathmandu Valley is excluded from cross-month comparisons because some serious-crime charts omit it.",
            "Months whose heinous or serious chart is missing/partial are reported as gaps, not zeros.",
            "The five-year annual chart is a separate series; fiscal years are matched across bulletins by latest as-of date.",
            "2078 bulletins and 2079 Baishakh use an older layout without province-by-offence charts.",
            "2079 Asar-Shrawan-Bhadra are derived by differencing consecutive cumulative charts; the 2079 Ashoj heinous chart is read from text labels over a raster background.",
            "2083 Bhadra serious chart is partial in the source PDF (only attempted murder is plotted).",
        ],
        "artifacts": {
            name: {
                "sha256": sha256(OUT / name),
                "bytes": (OUT / name).stat().st_size,
            }
            for name in artifacts
            if (OUT / name).exists()
        },
        "pdf_sha256": {
            key: sha256(PDF_DIR / f"{key}.pdf")
            for key in sorted(manifest)
            if (PDF_DIR / f"{key}.pdf").exists()
        },
    }
    (OUT / "build.json").write_text(json.dumps(build_info, ensure_ascii=False, indent=2), encoding="utf-8")
    return build_info
