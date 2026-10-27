"""Tests for the time/seasonality and historical-series research module."""

import json
import math

import pytest

pytest.importorskip("pandas")

from migration_parser.research import datasets
from migration_parser.research.patterns_time import (
    ANNUAL_GAP_TOLERANCE,
    BS_MONTHS,
    LATEST_FY,
    PARTIAL_FY,
    build,
)


@pytest.fixture(scope="module")
def report():
    return build()


def test_report_is_json_serializable(report):
    encoded = json.dumps(report, allow_nan=False)
    assert len(encoded) > 1000
    for key in (
        "meta", "modern_monthly_coverage", "modern_seasonality",
        "archive_monthly_coverage", "archive_seasonality",
        "structural_breaks", "deaths",
    ):
        assert key in report


def test_modern_monthly_2082_83_reconciles_to_annual(report):
    coverage = report["modern_monthly_coverage"]
    latest = coverage["latest_reconciliation"]
    assert latest["fiscal_year"] == LATEST_FY
    assert latest["complete_monthly"]
    assert latest["n_periods"] == 12
    assert latest["n_docs"] == 12
    assert latest["distinct_months"] == 12
    assert latest["within_tolerance"]
    assert latest["gap"] is not None
    assert latest["annual_total"] and latest["monthly_sum"]
    gap_share = latest["gap"] / latest["annual_total"]
    assert gap_share <= ANNUAL_GAP_TOLERANCE
    assert latest["gap"] == abs(latest["annual_total"] - latest["monthly_sum"])


def test_modern_seasonality_shares_and_index_ranges(report):
    season = report["modern_seasonality"]
    assert season["fiscal_year"] == LATEST_FY
    assert season["complete_monthly"]
    assert len(season["monthly"]) == 12
    shares = [m["share_pct"] for m in season["monthly"]]
    indices = [m["index"] for m in season["monthly"]]
    assert math.isclose(sum(shares), 100.0, abs_tol=0.01)
    assert math.isclose(sum(indices) / len(indices), 100.0, abs_tol=0.01)
    assert all(0 <= s <= 100 for s in shares)
    assert all(i >= 0 for i in indices)
    assert season["peak"]["count"] == max(m["count"] for m in season["monthly"])
    assert season["trough"]["count"] == min(m["count"] for m in season["monthly"])
    assert season["volatility_cv_pct"] >= 0
    assert season["total"] == sum(m["count"] for m in season["monthly"])
    assert set(season["months_covered"]) == set(BS_MONTHS)
    assert len(season["months_covered"]) == 12


def test_incomplete_and_partial_years_are_flagged_not_trended(report):
    coverage = report["modern_monthly_coverage"]["fiscal_years"]
    by_fy = {row["fiscal_year"]: row for row in coverage}
    assert by_fy[PARTIAL_FY]["partial"]
    assert by_fy[PARTIAL_FY]["complete_monthly"] is False
    assert by_fy["2081/82"]["complete_monthly"] is False
    assert set(report["modern_monthly_coverage"]["incomplete_fiscal_years"]) == {
        "2081/82", PARTIAL_FY,
    }
    for block in report["structural_breaks"].values():
        assert PARTIAL_FY not in block["years"]
        assert block["best"]["split_after"] in block["years"]
        assert block["best"]["split_before"] in block["years"]


def test_archive_scope_selection_is_deterministic(report):
    coverage = report["archive_monthly_coverage"]
    assert coverage["n_periods"] > 0
    assert coverage["n_docs"] == coverage["n_periods"]
    seen = set()
    for year in coverage["years"]:
        assert year["n_periods"] == len(year["periods"])
        assert year["n_missing"] == 12 - len(set(year["present_months"]))
        assert set(year["missing_months"]) == set(BS_MONTHS) - set(year["present_months"])
        for period in year["periods"]:
            key = (year["bs_year"], period["bs_month"])
            assert key not in seen
            seen.add(key)
            if "final_approved" in period["available_scopes"]:
                assert period["scope"] == "final_approved"
            else:
                assert period["scope"] == "month"
            assert period["count"] > 0
    assert coverage["dropped_candidates"] == []


def test_archive_seasonality_reports_missingness(report):
    season = report["archive_seasonality"]
    assert season["n_years"] >= 5
    assert season["missingness_flagged"]
    assert len(season["monthly"]) == 12
    assert season["peak"] and season["trough"]
    assert season["peak"]["index"] >= season["trough"]["index"]
    assert season["complete_year_count"] == 0
    assert all(m["n_years"] <= season["n_years"] for m in season["monthly"])
    assert any(year["n_missing"] > 0
               for year in report["archive_monthly_coverage"]["years"])


def test_deaths_and_per_approval_fields(report):
    deaths = report["deaths"]
    assert deaths["selected_series_key"]
    assert deaths["annual"]
    years = [row["fiscal_year"] for row in deaths["annual"]]
    assert len(years) == len(set(years))
    assert deaths["matched"]
    for row in deaths["matched"]:
        assert row["deaths"] > 0
        assert row["safe_approvals"] > 0
        assert row["deaths_per_100k"] > 0
        assert math.isclose(
            row["deaths_per_100k"],
            round(row["deaths"] / row["safe_approvals"] * 100000, 2),
            abs_tol=0.01,
        )
        assert row["approx_bs_fiscal_year"]
    assert deaths["unmatched_years"]
    assert all(row["deaths_per_100k"] is None
               for row in deaths["unmatched_years"])
    assert sum(row["deaths"] for row in deaths["annual"]) == sum(
        row["deaths"] for row in deaths["matched"]
    ) + sum(row["deaths"] for row in deaths["unmatched_years"])


def test_deaths_use_one_series_key_only(report):
    deaths = report["deaths"]
    ser = datasets.series()
    block = ser[(ser["series_key"] == deaths["selected_series_key"])
                & (ser["metric"] == "deaths") & (ser["gender"] == "total")]
    grouped = block.groupby("fiscal_year")["count"].sum()
    expected = {str(fy): int(value) for fy, value in grouped.items()}
    got = {row["fiscal_year"]: row["deaths"] for row in deaths["annual"]}
    assert got == expected
    selected = [s for s in deaths["sources"] if s["selected"]]
    assert len(selected) == 1
    assert selected[0]["series_key"] == deaths["selected_series_key"]
