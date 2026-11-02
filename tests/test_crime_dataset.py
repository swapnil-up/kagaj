"""Integrity checks for the committed crime dataset."""

from pathlib import Path

import pandas as pd
import pytest

from crime.schema import match_offense, match_offense_exact

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
    province_national = national[national["source"] == "province_sum"]
    detail = violent.assign(ex=violent["province"] != "kathmandu_valley")
    recomputed = (
        detail.groupby(["month", "chart_kind", "offense"], as_index=False)
        .agg(total=("value", "sum"), ex=("value", lambda s: s[detail.loc[s.index, "ex"]].sum()))
    )
    merged = province_national.merge(recomputed, on=["month", "chart_kind", "offense"])
    assert len(merged) == len(province_national)
    assert (merged["value"] == merged["total"]).all()
    assert (merged["value_ex_valley"] == merged["ex"]).all()


def test_2075_national_table_backfills_missing_offences():
    national = pd.read_csv(DATA / "violent_national.csv.gz", dtype={"month": str})
    rows = national[
        (national["month"] == "2075-11") & (national["source"] == "table_labels")
    ].set_index("offense")
    assert rows["value"].astype(int).to_dict() == {
        "murder": 40,
        "attempted_murder": 62,
        "trafficking": 24,
        "suicide_abetment": 5,
        "kidnapping": 11,
        "assault": 13,
    }
    assert (rows["provinces_reported"] == 0).all()
    assert rows["value_ex_valley"].isna().all()
    rape = national[(national["month"] == "2075-11") & (national["offense"] == "rape")]
    assert len(rape) == 1
    assert rape.iloc[0]["source"] == "province_sum"
    assert int(rape.iloc[0]["value"]) == 155


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
    assert list(partial["month"]) == ["2075-11", "2083-05"]
    assert list(partial["chart_kind"]) == ["heinous", "serious"]
    serious = pd.read_csv(DATA / "violent_monthly.csv.gz", dtype={"month": str})
    row = serious[(serious["month"] == "2083-05") & (serious["chart_kind"] == "serious")]
    assert set(row["offense"]) == {"attempted_murder"}


def test_2075_rape_backfilled_from_legacy_chart(violent):
    rows = violent[(violent["month"] == "2075-11") & (violent["chart_kind"] == "heinous")]
    assert set(rows["offense"]) == {"rape"}
    assert len(rows) == 8
    assert int(rows["value"].sum()) == 155
    values = rows.set_index("province")["value"].astype(int).to_dict()
    assert values == {
        "kathmandu_valley": 16,
        "koshi": 35,
        "madhesh": 22,
        "bagmati": 10,
        "gandaki": 16,
        "lumbini": 29,
        "karnali": 8,
        "sudurpashchim": 19,
    }


def test_offense_matching_rejects_traffic_labels():
    assert match_offense_exact("जबरजस्ती करणी") == "rape"
    assert match_offense_exact("जवरजस्ती करणी") == "rape"
    assert match_offense_exact("ज्यान मार्ने उद्योग") == "attempted_murder"
    assert match_offense_exact("आत्म हत्या गर्न दुरुत्साहन गरेको") == "suicide_abetment"
    assert match_offense_exact("कुटपिट अंगभंग") == "assault"
    assert match_offense_exact("जबरजस्ती करणी उद्योग") is None
    assert match_offense("सवारी ज्यान सम्बन्धी कसूर") is None
    assert match_offense("सडक दुर्घटना") is None


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
