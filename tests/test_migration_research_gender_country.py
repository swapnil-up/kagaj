"""Tests for the deep country-level gender analysis module."""

import json
import math

import pytest

pytest.importorskip("pandas")

from migration_parser.research import patterns_gender_country as pgcy
from migration_parser.research.datasets import (
    country_gender_year,
    country_year,
    load_panel,
)


@pytest.fixture(scope="module")
def report():
    return pgcy.build()


def _walk_floats(value):
    if isinstance(value, float):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_floats(item)


def test_build_has_required_top_level_keys(report):
    assert set(report) >= {
        "meta", "annual", "country_deep", "country_trajectories",
        "country_ranks", "distribution", "convergence",
        "contribution_decomposition", "growth_divergence",
        "share_size_growth", "robustness",
    }
    meta = report["meta"]
    assert meta["base_fy"] == pgcy.BASE_FY
    assert meta["latest_fy"] == pgcy.LATEST_FY
    assert meta["partial_fy"] == pgcy.PARTIAL_FY
    assert meta["partial_fy_excluded"] is True
    assert meta["min_volume"] == pgcy.MIN_VOLUME
    assert meta["caveats"]


def test_annual_totals_reconcile_to_gender_builders(report):
    cg = country_gender_year()
    cy = country_year()
    annual = {row["fiscal_year"]: row for row in report["annual"]}
    for fiscal_year, row in annual.items():
        cg_total = int(cg.loc[cg["fiscal_year"] == fiscal_year, "count"].sum())
        cy_total = int(cy.loc[cy["fiscal_year"] == fiscal_year, "count"].sum())
        assert row["female"] + row["male"] == row["total"]
        assert row["total"] == cg_total
        assert row["country_year_total"] == cy_total
        assert row["reconciles_with_country_year"] is True


def test_partial_fiscal_year_is_excluded_from_trend_outputs(report):
    assert pgcy.PARTIAL_FY not in [
        row["fiscal_year"] for row in report["annual"]]
    years = report["country_trajectories"]["years"]
    assert pgcy.PARTIAL_FY not in years
    for row in report["distribution"]["by_year"]:
        assert row["fiscal_year"] != pgcy.PARTIAL_FY
    for block in report["convergence"]["threshold_variants"]:
        assert all(pair is not None for pair in block["pairs"])
    for block in report["robustness"]["windows"]:
        assert block["start_fiscal_year"] != pgcy.PARTIAL_FY
        assert block["end_fiscal_year"] != pgcy.PARTIAL_FY
    assert report["annual"][-1]["fiscal_year"] == pgcy.LATEST_FY


def test_country_thresholds_and_shares_are_valid(report):
    block = report["country_deep"]
    assert block["min_volume"] == pgcy.MIN_VOLUME
    assert block["destinations"]
    for row in block["destinations"]:
        assert row["latest_total"] >= pgcy.MIN_VOLUME
        assert row["base_total"] >= 0
        assert row["latest_female"] >= 0
        assert row["latest_male"] >= 0
        for key in ("base_female_share_pct", "latest_female_share_pct"):
            assert row[key] is None or 0.0 <= row[key] <= 100.0
        change = row["female_share_change_pp"]
        assert change is None or -100.0 <= change <= 100.0
        for key in ("female_growth_pct", "male_growth_pct",
                    "total_growth_pct", "female_minus_male_growth_pp"):
            assert row[key] is None or math.isfinite(row[key])


def test_growth_fields_handle_zero_base_safely(report):
    for row in report["country_deep"]["destinations"]:
        if row["base_female"] == 0:
            assert row["female_growth_pct"] is None
        if row["base_male"] == 0:
            assert row["male_growth_pct"] is None
        if row["base_total"] == 0:
            assert row["total_growth_pct"] is None
            assert row["base_female_share_pct"] is None


def test_contribution_decomposition_is_internally_consistent(report):
    block = report["contribution_decomposition"]
    component_sum = (
        block["within_country_pp"]
        + block["country_composition_pp"]
        + block["interaction_pp"]
    )
    assert abs(component_sum - block["aggregate_change_pp"]) < 1e-3
    assert abs(component_sum - block["components_sum_pp"]) < 1e-3
    assert abs(block["latest_female_share_pct"]
               - block["base_female_share_pct"]
               - block["aggregate_change_pp"]) < 1e-3
    row_within = sum(row["within_pp"] for row in block["ranking"])
    row_total = sum(row["total_contribution_pp"] for row in block["ranking"])
    assert abs(row_within - block["within_country_pp"]) < 1e-3
    assert abs(row_total - block["aggregate_change_pp"]) < 1e-3
    top_sum = sum(row["within_pp"] for row in
                  block["largest_within_increases"][:pgcy.TOP_CONTRIBUTORS])
    assert abs(top_sum - block["top_positive_within_pp"]) < 1e-3
    assert block["largest_within_increases"]


def test_rank_tables_and_trajectories_are_populated(report):
    trajectories = report["country_trajectories"]
    assert trajectories["destinations"]
    assert len(trajectories["destinations"]) <= pgcy.TOP_DESTINATIONS
    for row in trajectories["destinations"]:
        assert len(row["series"]) == len(trajectories["years"])
        for point in row["series"]:
            assert point["female_share_pct"] is None or (
                0.0 <= point["female_share_pct"] <= 100.0)

    ranks = report["country_ranks"]
    assert ranks["by_latest_female_share"]
    assert ranks["by_female_share_change"]
    shares = [row["latest_female_share_pct"]
              for row in ranks["by_latest_female_share"]]
    assert shares == sorted(shares, reverse=True)
    changes = [row["female_share_change_pp"]
               for row in ranks["by_female_share_change"]]
    assert changes == sorted(changes, reverse=True)


def test_robustness_threshold_variants_are_present(report):
    robustness = report["robustness"]
    thresholds = [row["threshold"] for row in robustness["threshold_variants"]]
    assert thresholds == list(pgcy.THRESHOLD_VARIANTS)
    assert robustness["default_threshold"] == pgcy.MIN_VOLUME
    assert len(robustness["windows"]) == 3
    assert robustness["small_destinations"]["n_countries"] >= 0
    for row in robustness["threshold_variants"]:
        assert 0 <= row["latest_share_of_national_total_pct"] <= 100
        assert row["n_countries"] >= 0


def test_distribution_and_convergence_are_populated(report):
    distribution = report["distribution"]
    assert distribution["by_year"]
    for row in distribution["by_year"]:
        if row["n_countries"] == 0:
            continue
        assert row["min_female_share_pct"] <= row["max_female_share_pct"]
        assert (row["min_female_share_pct"] <= row["median_female_share_pct"]
                <= row["max_female_share_pct"])
    volatility = distribution["volatility_persistence"]
    assert volatility["destinations"]
    assert volatility["n_countries"] == len(volatility["destinations"])

    convergence = report["convergence"]
    assert convergence["default"]["n_countries"] >= 2
    for block in convergence["threshold_variants"]:
        assert -1 <= (block["correlation"] or 0) <= 1


def test_growth_divergence_reports_aggregate_gap(report):
    block = report["growth_divergence"]
    overall = block["overall"]
    assert overall["female_growth_pct"] is not None
    assert overall["male_growth_pct"] is not None
    assert abs(
        overall["female_minus_male_growth_pp"]
        - (overall["female_growth_pct"] - overall["male_growth_pct"])
    ) < 0.1
    assert block["n_countries_compared"] >= 0
    assert isinstance(block["female_up_male_down"], list)
    assert isinstance(block["female_down_male_up"], list)


def test_public_outputs_have_no_nan_or_inf(report):
    for value in _walk_floats(report):
        assert math.isfinite(value)
    encoded = json.dumps(report, allow_nan=False)
    decoded = json.loads(encoded)
    assert decoded["meta"]["base_fy"] == pgcy.BASE_FY
    assert decoded["country_deep"]["destinations"]
