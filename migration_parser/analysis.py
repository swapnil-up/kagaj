"""Analysis-side helpers for the migration panel.

Two traps this module makes hard to fall into:

* **Reporting windows are ~4 weeks, not calendar months.** DoFE labels a report by
  its BS month, but the actual window is printed as an exact AD range. Joining an
  external date series on "month" silently misaligns; :func:`merge_periods` joins on
  ``period_ad_start``/``period_ad_end`` instead.
* **Monthly and annual rows coexist.** Within a fiscal year, the twelve monthly
  documents and the annual roll-up describe the same quantity. Summing both
  double-counts; :func:`fiscal_year_panel` returns one row-per-FY basis.

The primary file ``panel_canonical.csv.gz`` is already additive-only (component
detail rows), so ordinary ``groupby`` sums are safe; these helpers cover the
period and granularity dimensions on top of that.
"""
from __future__ import annotations

from pathlib import Path

from .paths import MIGRATION_DIR

__all__ = ["load_panel", "load_rollup", "period_windows", "merge_periods",
           "fiscal_year_panel"]


def load_panel(path: str | Path | None = None):
    """Load the primary additive-only panel as a pandas DataFrame."""
    import pandas as pd

    path = Path(path) if path else MIGRATION_DIR / "panel_canonical.csv.gz"
    df = pd.read_csv(path, dtype={"count": "Int64", "sn": "string"})
    return df


def load_rollup(path: str | Path | None = None):
    """Load the non-additive rollup companion (aggregates/totals/measures)."""
    import pandas as pd

    path = Path(path) if path else MIGRATION_DIR / "panel_rollup.csv.gz"
    return pd.read_csv(path, dtype={"count": "Int64", "sn": "string"})


def period_windows(path: str | Path | None = None):
    """Load the tracked ``period_windows.csv`` lookup as a DataFrame."""
    import pandas as pd

    path = Path(path) if path else MIGRATION_DIR / "period_windows.csv"
    win = pd.read_csv(path).dropna(subset=["period_ad_start", "period_ad_end"])
    win["start"] = pd.to_datetime(win["period_ad_start"])
    win["end"] = pd.to_datetime(win["period_ad_end"])
    return win


def merge_periods(df, date_col: str, *, path: str | Path | None = None):
    """Attach the DoFE reporting window that contains each row's date.

    Uses ``period_ad_start``/``period_ad_end`` interval containment, not the printed
    BS month. Rows whose date falls in no window get ``NaN`` window fields and
    ``window_matched=False``. Returns ``df`` with the window columns appended
    (``period_bs``, ``fiscal_year``, ``period_ad_start``, ``period_ad_end``,
    ``doc_id`` and ``window_matched``).
    """
    import pandas as pd

    win = period_windows(path)
    left = df.copy()
    left["_d"] = pd.to_datetime(left[date_col])
    cols = ["period_bs", "fiscal_year", "period_ad_start", "period_ad_end", "doc_id",
            "start", "end"]
    merged = pd.merge_asof(
        left.sort_values("_d"),
        win[cols].sort_values("start"),
        left_on="_d", right_on="start", direction="backward",
    )
    merged["window_matched"] = merged["end"].notna() & (merged["_d"] <= merged["end"])
    for c in ("start", "end", "_d"):
        merged = merged.drop(columns=c)
    return merged.reset_index(drop=True)


def fiscal_year_panel(df, *, prefer: str = "annual"):
    """Return rows on a single per-fiscal-year basis to avoid month+annual double count.

    For any fiscal year that has BOTH monthly and annual component rows, keep only
    the ``prefer`` granularity (``"annual"`` by default; pass ``"month"`` to prefer
    the monthly documents). Fiscal years with only one granularity are untouched.
    """
    if prefer not in ("annual", "month"):
        raise ValueError("prefer must be 'annual' or 'month'")
    fy = df["reconciled_fiscal_year"]
    months = set(fy[df["granularity"] == "month"])
    years = set(fy[df["granularity"] == "year"])
    overlap = months & years
    drop_kind = "month" if prefer == "annual" else "year"
    drop = (df["granularity"] == drop_kind) & fy.isin(overlap)
    return df[~drop].copy()
