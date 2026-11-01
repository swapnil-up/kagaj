"""Integrity checks for the committed crime dataset."""

from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).resolve().parent.parent / "datasets" / "crime"
MONTH_RE = r"^\d{4}-\d{2}$"


@pytest.fixture(scope="module")
def violent():
    path = DATA / "violent_monthly.csv.gz"
    if not path.exists():
        pytest.skip("crime dataset not built")
    return pd.read_csv(path, dtype={"month": str})


def test_violent_monthly_unique_and_well_formed(violent):
    assert not violent.duplicated(
        subset=["month", "chart_kind", "offense", "province"]
    ).any()
    assert violent["month"].str.fullmatch(MONTH_RE).all()
    assert (violent["value"] >= 0).all()
    assert set(violent["chart_kind"]) == {"heinous", "serious"}


def test_violent_national_matches_province_detail(violent):
    national = pd.read_csv(DATA / "violent_national.csv.gz", dtype={"month": str})
    detail = violent.assign(ex=violent["province"] != "kathmandu_valley")
    recomputed = (
        detail.groupby(["month", "chart_kind", "offense"], as_index=False)
        .agg(total=("value", "sum"), ex=("value", lambda s: s[detail.loc[s.index, "ex"]].sum()))
    )
    merged = national.merge(recomputed, on=["month", "chart_kind", "offense"])
    assert len(merged) == len(national)
    assert (merged["value"] == merged["total"]).all()
    assert (merged["value_ex_valley"] == merged["ex"]).all()


def test_total_cases_unique_and_positive():
    totals = pd.read_csv(DATA / "total_cases_monthly.csv.gz", dtype={"month": str})
    assert not totals.duplicated(subset=["month", "province"]).any()
    assert totals["month"].str.fullmatch(MONTH_RE).all()
    assert (totals["value"] > 0).all()


def test_annual_one_row_per_fy_series():
    annual = pd.read_csv(DATA / "annual_totals.csv", dtype={"fy": str})
    assert not annual.duplicated(subset=["fy", "series"]).any()
    assert set(annual["series"]) <= {"registered", "disposed", "pending"}
    assert (annual["value"] >= 0).all()


def test_provenance_columns_and_derived_months(violent):
    assert {"basis", "method", "confidence"} <= set(violent.columns)
    assert violent["method"].notna().all()
    assert violent["confidence"].notna().all()
    assert set(violent["method"]) <= {
        "chart_labels", "text_labels", "cumulative_difference",
    }
    derived = violent[violent["basis"] == "derived"]
    assert sorted(derived["month"].unique()) == ["2079-03", "2079-04", "2079-05"]
    assert (derived["value"] >= 0).all()


def test_derived_and_text_label_values(violent):
    heinous = violent[violent["chart_kind"] == "heinous"]

    def total(month, offense):
        return int(heinous[(heinous["month"] == month) & (heinous["offense"] == offense)]["value"].sum())

    assert total("2079-03", "murder") == 42
    assert total("2079-04", "rape") == 239
    assert total("2079-05", "murder") == 45
    assert total("2079-06", "rape") == 147


def test_partial_chart_is_flagged():
    status = pd.read_csv(DATA / "month_status.csv.gz", dtype={"month": str})
    partial = status[status["partial_chart"]]
    assert list(partial["month"]) == ["2083-05"]
    assert list(partial["chart_kind"]) == ["serious"]
    serious = pd.read_csv(DATA / "violent_monthly.csv.gz", dtype={"month": str})
    row = serious[(serious["month"] == "2083-05") & (serious["chart_kind"] == "serious")]
    assert set(row["offense"]) == {"attempted_murder"}


def test_supporting_tables_are_consistent():
    coverage = pd.read_csv(DATA / "category_coverage.csv.gz", dtype={"month": str})
    availability = pd.read_csv(DATA / "offense_availability.csv.gz")
    revisions = pd.read_csv(DATA / "total_case_revisions.csv.gz", dtype={"month": str})
    rates = pd.read_csv(DATA / "annual_rates.csv", dtype={"fy": str})
    assert int(availability["months_reported"].sum()) == len(coverage)
    assert (coverage["provinces_reported"] > 0).all()
    assert revisions["values"].notna().all()
    assert rates["population"].gt(25_000_000).all()
    assert rates["registered_per_100k"].between(100, 250).all()


def test_national_totals_are_continuous():
    national = pd.read_csv(DATA / "total_cases_national.csv.gz", dtype={"month": str})
    months = sorted(national["month"].unique())
    assert months[0] == "2078-07"
    assert months[-1] == "2083-06"
    assert len(months) == 60
    assert {"province_sum", "line_labels"} <= set(national["method"])
    assert int((national["method"] == "line_labels").sum()) == 9
    assert (national["value"] > 0).all()
    revisions = pd.read_csv(DATA / "national_total_revisions.csv.gz", dtype={"month": str})
    assert revisions["values"].notna().all()
