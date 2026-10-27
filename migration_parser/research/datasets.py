"""Canonical, single-basis data builders for migration research.

Every builder starts from the additive-only panel and applies the same two
guards: ``analysis_safe`` by default, and one granularity per fiscal year.
Aggregates and printed totals are never included.
"""

from __future__ import annotations

from pathlib import Path

from ..analysis import fiscal_year_panel
from ..analysis import load_panel as _load_panel
from ..paths import MIGRATION_ARCHIVE_PANEL, MIGRATION_DIR

BOOL_COLUMNS = (
    "analysis_safe",
    "analysis_safe_permissive",
    "channel_reviewed",
    "entity_resolved",
    "period_override",
    "verified",
)


def _truthy(values):
    return values.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _coerce(df):
    if "count" in df:
        df["count"] = df["count"].astype("int64")
    for col in BOOL_COLUMNS:
        if col in df:
            df[col] = _truthy(df[col])
    return df


def load_panel(path: str | Path | None = None, *, safe: bool = True):
    """Load the tracked additive panel, optionally keeping only safe rows."""
    df = _coerce(_load_panel(path))
    if safe:
        df = df[df["analysis_safe"]].copy()
    return df.reset_index(drop=True)


def _single_basis(df, prefer: str):
    out = fiscal_year_panel(df, prefer=prefer).copy()
    out["basis"] = out["granularity"].map(
        {"year": "annual", "month": "monthly", "measure": "measure"}
    )
    return out


def _detail_rows(df, *, section: str, gender: str | None,
                 resolved_only: bool) -> object:
    out = df[(df["section"] == section) & (df["row_type"] == "detail")].copy()
    if gender is not None:
        out = out[out["gender"] == gender]
    if resolved_only:
        out = out[out["entity_resolved"]]
    return out


def country_year(df=None, *, safe: bool = True, prefer: str = "annual",
                 resolved_only: bool = True):
    """Destination × fiscal-year totals, one granularity per fiscal year."""
    panel = load_panel(safe=safe) if df is None else _coerce(df.copy())
    d = _detail_rows(panel, section="country", gender="total",
                     resolved_only=resolved_only)
    d = _single_basis(d, prefer)
    out = (d.groupby(["reconciled_fiscal_year", "name_canonical"], as_index=False)
           .agg(count=("count", "sum"), iso3=("iso3", "first"),
                basis=("basis", "first")))
    return out.rename(columns={"reconciled_fiscal_year": "fiscal_year",
                               "name_canonical": "country"}).sort_values(
        ["fiscal_year", "count"], ascending=[True, False]).reset_index(drop=True)


def country_gender_year(df=None, *, safe: bool = True, prefer: str = "annual",
                        resolved_only: bool = True):
    """Destination × fiscal-year × sex totals, one granularity per fiscal year."""
    panel = load_panel(safe=safe) if df is None else _coerce(df.copy())
    d = _detail_rows(panel, section="country", gender=None,
                     resolved_only=resolved_only)
    d = d[d["gender"].isin(["male", "female"])]
    d = _single_basis(d, prefer)
    out = (d.groupby(["reconciled_fiscal_year", "name_canonical", "gender"],
                     as_index=False)
           .agg(count=("count", "sum"), iso3=("iso3", "first"),
                basis=("basis", "first")))
    return out.rename(columns={"reconciled_fiscal_year": "fiscal_year",
                               "name_canonical": "country"}).sort_values(
        ["fiscal_year", "country", "gender"]).reset_index(drop=True)


def country_channel_year(df=None, *, safe: bool = True,
                         prefer: str = "annual", resolved_only: bool = True):
    """Destination × fiscal-year × channel totals, one granularity per year."""
    panel = load_panel(safe=safe) if df is None else _coerce(df.copy())
    d = _detail_rows(panel, section="country", gender="total",
                     resolved_only=resolved_only)
    d = _single_basis(d, prefer)
    out = (d.groupby(["reconciled_fiscal_year", "name_canonical",
                      "channel_canonical"], as_index=False)
           .agg(count=("count", "sum"), basis=("basis", "first")))
    return out.rename(columns={"reconciled_fiscal_year": "fiscal_year",
                               "name_canonical": "country"}).sort_values(
        ["fiscal_year", "country", "channel_canonical"]).reset_index(drop=True)


def district_year(df=None, *, safe: bool = True, prefer: str = "annual",
                  resolved_only: bool = True):
    """Origin district × fiscal-year totals, one granularity per fiscal year."""
    panel = load_panel(safe=safe) if df is None else _coerce(df.copy())
    d = _detail_rows(panel, section="district", gender="total",
                     resolved_only=resolved_only)
    d = _single_basis(d, prefer)
    out = (d.groupby(["reconciled_fiscal_year", "name_canonical",
                      "province"], as_index=False)
           .agg(count=("count", "sum"), basis=("basis", "first")))
    return out.rename(columns={"reconciled_fiscal_year": "fiscal_year",
                               "name_canonical": "district"}).sort_values(
        ["fiscal_year", "count"], ascending=[True, False]).reset_index(drop=True)


def _repair_known_district_gender_swaps(d: pd.DataFrame) -> pd.DataFrame:
    """Undo two source-table male/female reversals.

    BS 2075/76 (report2020 annex XIII) and the individual-re-entry columns in
    BS 2078/79 have male and female printed in reverse order. The remaining
    cells in those tables reconcile with the country tables after the swap.
    """
    swap = (
        (d["reconciled_fiscal_year"] == "2075/76")
        | ((d["reconciled_fiscal_year"] == "2078/79")
           & (d["channel_canonical"] == "individual_reentry"))
    )
    swap &= d["gender"].isin(["male", "female"])
    if swap.any():
        d = d.copy()
        d.loc[swap, "gender"] = d.loc[swap, "gender"].map(
            {"male": "female", "female": "male"})
    return d


def district_gender_year(df=None, *, safe: bool = True,
                         prefer: str = "annual", resolved_only: bool = True):
    """Origin district × fiscal-year × sex totals, one basis per year."""
    panel = load_panel(safe=safe) if df is None else _coerce(df.copy())
    d = _detail_rows(panel, section="district", gender=None,
                     resolved_only=resolved_only)
    d = d[d["gender"].isin(["male", "female"])]
    d = _repair_known_district_gender_swaps(d)
    d = _single_basis(d, prefer)
    out = (d.groupby(["reconciled_fiscal_year", "name_canonical", "province",
                      "gender"], as_index=False)
           .agg(count=("count", "sum"), basis=("basis", "first")))
    return out.rename(columns={"reconciled_fiscal_year": "fiscal_year",
                               "name_canonical": "district"}).sort_values(
        ["fiscal_year", "district", "gender"]).reset_index(drop=True)


def archive_panel(path: str | Path | None = None, *, safe: bool = True):
    """Load the separate archive.org monthly panel without joining channels."""
    import pandas as pd

    target = Path(path) if path else MIGRATION_ARCHIVE_PANEL
    df = pd.read_csv(target, dtype={"count": "Int64", "sn": "string"},
                     low_memory=False)
    df = _coerce(df)
    if safe:
        df = df[df["analysis_safe"]].copy()
    return df.reset_index(drop=True)


def series(path: str | Path | None = None):
    """Load the historical metric series with numeric counts and no summing."""
    import pandas as pd

    target = Path(path) if path else MIGRATION_DIR / "series.csv"
    df = pd.read_csv(target, dtype={"count": "float64"})
    df["count"] = pd.to_numeric(df["count"], errors="coerce")
    return df
