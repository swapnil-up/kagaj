"""Tests for the deeper origin-district research module."""

import json
import math

import pytest

pytest.importorskip("pandas")

from migration_parser.research import datasets, patterns_districts


@pytest.fixture(scope="module")
def report():
    return patterns_districts.build()


def test_build_is_json_serializable_and_has_required_keys(report):
    payload = json.dumps(report)
    assert json.loads(payload)["meta"]["first_fy"] == "2074/75"
    for key in (
        "meta",
        "annual_concentration",
        "convergence",
        "transitions",
        "contributions",
        "volatility",
        "provinces",
        "gender",
    ):
        assert key in report


def test_district_keys_are_unique():
    dist = datasets.district_year()
    dgen = datasets.district_gender_year()
    assert not dist.duplicated(["fiscal_year", "district"]).any()
    assert not dgen.duplicated(["fiscal_year", "district", "gender"]).any()
    assert not (dist["count"] < 0).any()
    assert not (dgen["count"] < 0).any()


def test_partial_fiscal_year_is_excluded(report):
    partial = "2083/84"
    assert partial not in report["meta"]["fiscal_years"]
    assert report["meta"]["latest_fy"] == "2082/83"
    assert all(row["fiscal_year"] != partial
               for row in report["annual_concentration"])
    assert all(row["fiscal_year"] != partial
               for row in report["convergence"]["sigma"])
    assert all(row["fiscal_year"] != partial
               for row in report["provinces"]["by_year"])
    assert all(row["fiscal_year"] != partial
               for row in report["gender"]["annual_national"])


def test_annual_concentration_ranges(report):
    rows = report["annual_concentration"]
    assert rows
    for row in rows:
        assert 0 < row["hhi"] <= 1
        assert 0 <= row["top5_share_pct"] <= 100
        assert 0 <= row["top10_share_pct"] <= 100
        assert row["top5_share_pct"] <= row["top10_share_pct"] + 1e-6
        assert row["active_districts"] > 0
        assert 0 < row["top_district_share_pct"] <= 100
        assert row["top_district"]


def test_convergence_outputs_are_finite(report):
    conv = report["convergence"]
    beta = conv["beta"]
    assert beta["n"] >= 3
    for key in ("slope", "intercept", "stderr", "p_value", "r_squared"):
        assert beta[key] is not None
        assert math.isfinite(beta[key])
    assert 0 <= beta["r_squared"] <= 1
    assert 0 <= beta["p_value"] <= 1

    sigma = conv["sigma"]
    assert len(sigma) == len(report["meta"]["fiscal_years"])
    for row in sigma:
        assert row["cv"] is not None and math.isfinite(row["cv"])
        assert row["cv"] >= 0
        assert row["n"] > 0

    assert conv["sigma_change"] is not None
    assert math.isfinite(conv["sigma_change"])
    mobility = conv["mobility"]
    assert mobility["n"] > 2
    assert -1 <= mobility["spearman"] <= 1
    assert 0 <= mobility["mobility"] <= 2
    assert mobility["mean_abs_rank_change"] is not None


def test_decile_transition_rows_are_normalized(report):
    trans = report["transitions"]["deciles"]
    counts = trans["counts"]
    shares = trans["shares"]
    assert len(counts) == 10
    assert all(len(row) == 10 for row in counts)
    assert trans["n"] > 0
    assert 0 <= trans["persistence_rate"] <= 1
    for index, (count_row, share_row) in enumerate(zip(counts, shares)):
        assert sum(count_row) == trans["row_totals"][index]
        total = sum(count_row)
        if total:
            assert math.isclose(sum(share_row), 1.0, rel_tol=1e-4)
            assert all(0 <= value <= 1 for value in share_row)
        else:
            assert all(value is None for value in share_row)


def test_contributions_reconcile_national_growth(report):
    contrib = report["contributions"]
    assert contrib["rows"]
    assert contrib["national_change"] == (
        contrib["latest_total"] - contrib["initial_total"])
    total_share = sum(row["contribution_pct"] for row in contrib["rows"])
    assert math.isclose(total_share, 100.0, rel_tol=1e-4)
    assert all(row["change"] > 0 for row in contrib["top_positive"])
    assert all(row["change"] < 0 for row in contrib["top_negative"])
    assert len({row["district"] for row in contrib["rows"]}) == len(
        contrib["rows"])


def test_volatility_respects_base_and_is_sorted(report):
    vol = report["volatility"]
    assert vol["n_considered"] > 0
    assert vol["most_volatile"]
    assert vol["least_volatile"]
    for row in vol["most_volatile"] + vol["least_volatile"]:
        assert row["initial_count"] >= vol["min_initial_count"]
        assert math.isfinite(row["log_growth_sd"])
        assert row["log_growth_sd"] >= 0
        assert row["cv"] is None or row["cv"] >= 0
    most = [row["log_growth_sd"] for row in vol["most_volatile"]]
    least = [row["log_growth_sd"] for row in vol["least_volatile"]]
    assert most == sorted(most, reverse=True)
    assert least == sorted(least)


def test_province_aggregation_shares_sum_to_one(report):
    prov = report["provinces"]
    assert prov["by_year"]
    assert prov["change"]
    for row in prov["by_year"]:
        assert row["total"] > 0
        assert sum(row["shares_pct"].values()) == pytest.approx(100.0,
                                                                abs=1e-2)
    for row in prov["change"]:
        assert row["province"]
        assert math.isfinite(row["growth_pct"])
        assert math.isfinite(row["share_change_pp"])


def test_gender_metrics_are_bounded(report):
    gen = report["gender"]
    assert gen["annual_national"]
    for row in gen["annual_national"]:
        assert 0 <= row["female_share_pct"] <= 100
        assert row["male"] + row["female"] == row["total"]
    assert gen["n"] > 0
    for row in gen["latest_share"]:
        assert row["initial_total"] >= gen["min_total"]
        assert row["latest_total"] >= gen["min_total"]
        assert 0 <= row["initial_female_share_pct"] <= 100
        assert 0 <= row["latest_female_share_pct"] <= 100
        assert math.isfinite(row["change_pp"])
