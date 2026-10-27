"""Tests for the deep destination analysis module."""

import json
import math

import pytest

pytest.importorskip("pandas")

from migration_parser.research import datasets
from migration_parser.research.patterns_destinations import (
    ACTIVE_THRESHOLD,
    BASE_FY,
    LATEST_FY,
    PARTIAL_FY,
    build,
)


@pytest.fixture(scope="module")
def report():
    return build()


def test_country_year_has_unique_fiscal_year_country_keys():
    cy = datasets.country_year()
    assert not cy.duplicated(["fiscal_year", "country"]).any()
    pivot = cy.pivot_table(index="fiscal_year", columns="country",
                           values="count", aggfunc="sum")
    assert pivot.columns.is_unique


def test_rank_panel_has_unique_keys_and_valid_shares(report):
    seen = set()
    for block in report["rank_panel"]:
        assert block["fiscal_year"] != PARTIAL_FY
        assert len(block["rows"]) <= 15
        for row in block["rows"]:
            key = (block["fiscal_year"], row["country"])
            assert key not in seen
            seen.add(key)
            assert 0 <= row["share_pct"] <= 100
        shares = [row["share_pct"] for row in block["rows"]]
        assert shares == sorted(shares, reverse=True)
        assert sum(shares) <= 100.0001


def test_recovery_decomposition_sums_to_total_change(report):
    recovery = report["recovery"]
    parts = recovery["decomposition"]
    assert parts["sums_correctly"]
    assert parts["accounted_change"] == recovery["total_change"]
    assert parts["unexplained"] == 0
    assert (parts["continuing"] + parts["entrants"] + parts["exits"]
            == recovery["total_change"])
    contributions = sum(row["contribution"]
                        for row in recovery["contributions"])
    assert contributions == recovery["total_change"]
    assert recovery["total_change"] == (recovery["total_latest"]
                                        - recovery["total_pre"])


def test_concentration_contributions_sum_to_hhi_change(report):
    concentration = report["concentration"]
    assert concentration["sums_correctly"]
    assert abs(concentration["sum_of_contributions"]
               - concentration["hhi_change"]) < 1e-6
    contributions = sum(row["squared_share_contribution"]
                        for row in concentration["contributions"])
    assert math.isclose(contributions,
                        concentration["hhi_change"], abs_tol=1e-5)
    assert 0 <= concentration["hhi_pre"] <= 1
    assert 0 <= concentration["hhi_latest"] <= 1
    for row in concentration["contributions"]:
        assert 0 <= row["pre_share_pct"] <= 100
        assert 0 <= row["latest_share_pct"] <= 100
        assert -1 <= row["squared_share_contribution"] <= 1


def test_partial_fiscal_year_is_excluded_from_trends(report):
    assert report["meta"]["partial_fy"] == PARTIAL_FY
    assert report["meta"]["partial_excluded"] is True
    assert PARTIAL_FY not in report["meta"]["fiscal_years"]
    for block in report["rank_panel"]:
        assert block["fiscal_year"] != PARTIAL_FY
    for row in report["rank_stability"]:
        assert row["from"] != PARTIAL_FY and row["to"] != PARTIAL_FY
    for row in report["turnover"]["transitions"]:
        assert row["from"] != PARTIAL_FY and row["to"] != PARTIAL_FY
    assert report["recovery"]["latest"] == LATEST_FY
    assert report["concentration"]["latest"] == LATEST_FY
    assert PARTIAL_FY not in report["volatility"]["years"]
    for row in report["outliers"]["positive"] + report["outliers"]["negative"]:
        assert row["from"] != PARTIAL_FY and row["to"] != PARTIAL_FY


def test_volatility_and_outliers_are_in_range(report):
    volatility = report["volatility"]
    assert volatility["destinations"]
    for row in volatility["destinations"]:
        assert row["cv"] is None or row["cv"] >= 0
        assert 0 <= row["max_drawdown_pct"] <= 100
        assert 0 <= row["latest_share_pct"] <= 100
    for key, block in volatility["counts_above_threshold"].items():
        assert block["count"] == len(block["countries"])
    positives = report["outliers"]["positive"]
    negatives = report["outliers"]["negative"]
    assert positives and negatives
    assert positives[0]["robust_z"] >= positives[-1]["robust_z"]
    assert negatives[0]["robust_z"] <= negatives[-1]["robust_z"]
    for row in positives + negatives:
        assert row["previous"] >= report["meta"]["thresholds"]["growth_min_base"]
        assert row["current"] >= report["meta"]["thresholds"]["growth_min_base"]


def test_turnover_documents_threshold_and_valid_jaccard(report):
    turnover = report["turnover"]
    assert turnover["threshold"] == ACTIVE_THRESHOLD
    assert turnover["threshold"] == report["meta"]["thresholds"]["active_destination"]
    for row in turnover["transitions"]:
        assert 0 <= row["jaccard"] <= 1
        assert row["top10_overlap"] + row["top10_churn"] <= 10
        for item in row["new"] + row["retired"]:
            assert item["count"] >= ACTIVE_THRESHOLD


def test_rank_stability_spearman_is_valid(report):
    for row in report["rank_stability"]:
        assert row["spearman"] is None or -1 <= row["spearman"] <= 1


def test_output_is_json_serializable(report):
    encoded = json.dumps(report, allow_nan=False)
    decoded = json.loads(encoded)
    assert decoded["meta"]["base_fy"] == BASE_FY
    assert set(decoded) >= {
        "meta", "rank_panel", "rank_stability", "turnover", "recovery",
        "concentration", "volatility", "outliers",
    }
